"""Regenerable study reports over checked journals and ordinary evaluation records."""

from collections.abc import Mapping
from pathlib import Path
from statistics import median
from typing import cast

from gwent_engine.ai.policy_artifacts import PolicyArtifact
from gwent_shared.extract import expect_mapping
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.execution import candidate_manifest
from gwent_evaluation.models import SpecError
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.reporting import build_run_report
from gwent_evaluation.storage import (
    RunConflictError,
    RunStore,
    atomic_write_text,
    read_record_mapping,
)
from gwent_evaluation.tuning.latency import load_latency
from gwent_evaluation.tuning.models import StudyMode, StudySpec
from gwent_evaluation.tuning.report_models import LIMITATIONS, StudyReport
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.specs import study_from_dict
from gwent_evaluation.tuning.storage import JournalEntry, StudyStore, read_checked_document
from gwent_evaluation.tuning.verification import require_verification


def _mapping(value: object) -> Mapping[str, object]:
    return expect_mapping(value, context="study report evidence", error_factory=SpecError)


def optimization_directory(root: Path) -> Path:
    """Accept the complete workflow, historical pilot, or optimization directory."""
    if (root / "study.json").exists():
        return root / "optimization"
    if (root / "inputs/study.json").exists():
        return root / "data/optimization"
    return root


def _journal(root: Path) -> tuple[Mapping[str, object], tuple[JournalEntry, ...]]:
    snapshot = _mapping(read_checked_document(root / "snapshot.json")["snapshot"])
    store = StudyStore(root, verification_only=True)
    with store.writer():
        store.prepare(snapshot)
        return snapshot, store.entries


def _method_reports(
    study: StudySpec, entries: tuple[JournalEntry, ...]
) -> tuple[Mapping[str, object], ...]:
    trials = [e.payload for e in entries if e.kind == "trial"]
    reference = next((_mapping(t["trial"]) for t in trials if t["method"] is None), None)
    reports: list[Mapping[str, object]] = []
    for settings in study.optimizers:
        proposals = {
            cast(int, _mapping(candidate["proposal"])["index"]): (
                entry.payload["population"],
                _mapping(candidate["proposal"])["coordinates"],
            )
            for entry in entries
            if entry.kind == "ask" and entry.payload["method"] == settings.method.value
            for candidate in map(_mapping, cast(list[object], entry.payload["candidates"]))
        }
        rows = [t for t in trials if t["method"] == settings.method.value]
        best = None if reference is None else cast(float, reference["score"])
        work = 0
        unique: set[str] = set()
        curve: list[dict[str, object]] = []
        for index, row in enumerate(rows, 1):
            trial = _mapping(row["trial"])
            score = cast(float, trial["score"])
            best = score if best is None else max(best, score)
            work += cast(int, row["fresh_matches"])
            unique.add(cast(str, trial["configuration_digest"]))
            population, coordinates = proposals[cast(int, row["index"])]
            curve.append(
                {
                    "proposals": index,
                    "fresh_matches": work,
                    "best_score": best,
                    "candidate_score": score,
                    "configuration_digest": trial["configuration_digest"],
                    "generation": cast(int, population) + 1,
                    "coordinates": coordinates,
                }
            )
        stop = next(
            (
                e.payload.get("stop")
                for e in entries
                if e.kind == "stop" and e.payload["method"] == settings.method.value
            ),
            None,
        )
        asked = sum(
            len(cast(list[object], e.payload["candidates"]))
            for e in entries
            if e.kind == "ask" and e.payload["method"] == settings.method.value
        )
        reports.append(
            {
                "method": settings.method.value,
                "proposal_budget": settings.proposal_budget,
                "asked_proposals": asked,
                "completed_proposals": len(rows),
                "unique_configurations": len(unique),
                "fresh_matches": work,
                "cache_hits": sum(row["cache_hit"] is True for row in rows),
                "shared_incumbent_matches": 0 if reference is None else reference["completed"],
                "best_score_curve": curve,
                "generations": [
                    {
                        "generation": cast(int, entry.payload["population"]) + 1,
                        "best": max(scores),
                        "median": median(scores),
                        "worst": min(scores),
                    }
                    for entry in entries
                    if entry.kind == "tell" and entry.payload["method"] == settings.method.value
                    for scores in [
                        [
                            1.0 - cast(float, result["fitness"])
                            for result in map(
                                _mapping, cast(list[object], entry.payload["results"])
                            )
                        ]
                    ]
                ],
                "stop": stop,
            }
        )
    return tuple(reports)


def _runs(
    root: Path, study: StudySpec, stage: str, entries: tuple[JournalEntry, ...]
) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    committed: dict[str, Mapping[str, object]] = {}
    for entry in entries:
        if entry.kind == "trial":
            trial = _mapping(entry.payload["trial"])
            committed[cast(str, trial["run_root"])] = {
                cast(str, item["case_id"]): item["record_digest"]
                for item in map(_mapping, cast(list[object], trial["results"]))
            }
        elif entry.kind == "evaluation":
            committed[cast(str, entry.payload["run_root"])] = _mapping(entry.payload["results"])
    paths = {str(path.parent.relative_to(root)) for path in (root / "runs").glob("*/manifest.json")}
    paths.update(committed)
    for relative in sorted(paths):
        loaded = RunStore.from_root(root / relative).load()
        if relative in committed and dict(loaded.result_digests) != committed[relative]:
            raise RunConflictError("Committed study results changed or are missing.")
        report = build_run_report(loaded, bootstrap=study.bootstrap)
        configuration = loaded.manifest.suite.candidate.heuristic_configuration
        assert configuration is not None
        template = {
            "optimization": study.optimization,
            "validation": study.validation,
            "confirmation": study.test,
        }.get(stage)
        if template is not None and loaded.manifest != candidate_manifest(
            template, configuration, run_id=loaded.manifest.run_id
        ):
            raise RunConflictError("Recorded run differs from frozen study conditions.")
        rows.append(
            {
                "stage": stage,
                "run": str(root / relative),
                "configuration_digest": configuration.digest(),
                "configuration": configuration.to_dict(),
                "committed": relative in committed,
                "report": record_to_dict(report),
                "candidate_latency": {
                    "status": "not_collected",
                    "samples": 0,
                    "mean_seconds": None,
                },
            }
        )
    return rows


def _sensitivity_latency(root: Path) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for path in sorted((root / "runs").glob("*/manifest.json")):
        store = RunStore.from_root(path.parent)
        loaded = store.load()
        cases = tuple(
            key
            for key, result in loaded.results.items()
            if result.evidence.samples_path is not None
        )
        sampled = store.load(sample_cases=cases)
        durations = [
            sample.duration_seconds
            for case_id, samples in sampled.samples.items()
            for sample in samples
            if sample.actor == sampled.results[case_id].candidate_seat
        ]
        rows.append(
            {
                "control": path.parent.name,
                "candidate_samples": len(durations),
                "candidate_mean_seconds": sum(durations) / len(durations) if durations else None,
                "source": "persisted candidate decision samples on the sensitivity control panel",
            }
        )
    return rows


def build_study_report(root: Path) -> StudyReport:
    optimization = optimization_directory(root)
    entries: tuple[JournalEntry, ...] = ()
    preflight: SensitivityReport | None = None
    if (optimization / "snapshot.json").exists():
        snapshot, entries = _journal(optimization)
        study = study_from_dict(snapshot["study"])
        preflight = SensitivityReport.from_dict(snapshot["sensitivity"])
    elif (root / "study.json").exists():
        study = study_from_dict(read_checked_document(root / "study.json"))
    elif (root / "inputs/study.json").exists():
        study = study_from_dict(read_checked_document(root / "inputs/study.json"))
    else:
        raise SpecError(f"No frozen study found at {root}.")
    sensitivity_root = root / ("data/sensitivity" if (root / "inputs").exists() else "sensitivity")
    if preflight is None and (sensitivity_root / "report.json").exists():
        preflight = SensitivityReport.from_dict(
            read_record_mapping(sensitivity_root / "report.json")
        )
    if preflight is not None and preflight.study_digest != study.digest():
        raise RunConflictError("Sensitivity report belongs to another study.")
    stage = "optimization_partial" if entries else "preflight"
    engineering = "incomplete"
    reasons: tuple[str, ...] = ()
    if any(e.kind == "complete" for e in entries):
        stage = "optimization_complete"
    halt = next((e for e in entries if e.kind == "halt"), None)
    if halt is not None:
        stage, engineering, reasons = (
            "optimization_stopped",
            "failed",
            (str(halt.payload["detail"]),),
        )
    sensitivity = (
        None
        if preflight is None
        else {**preflight.to_dict(), "candidate_latency": _sensitivity_latency(sensitivity_root)}
    )
    measurement = "not_assessed" if preflight is None else preflight.status
    if preflight is not None and preflight.reasons:
        stage, engineering, reasons = "insufficient_sensitivity", "stopped", preflight.reasons
    if study.mode is StudyMode.SMOKE and preflight is not None:
        stage, engineering = "diagnostic_complete", "complete"
    runs = _runs(optimization, study, "optimization", entries)
    runs.extend(_runs(sensitivity_root, study, "sensitivity", ()))
    validation: Mapping[str, object] | None = None
    confirmation: Mapping[str, object] | None = None
    verification: Mapping[str, object] | None = None
    verdict = "not_assessed"
    selection_root = optimization / "selection"
    for directory, label, kind in (
        (selection_root, "validation", "selection"),
        (selection_root / "confirmation", "confirmation", "confirmation"),
    ):
        if not (directory / "snapshot.json").exists():
            continue
        stage_snapshot, stage_entries = _journal(directory)
        if study_from_dict(stage_snapshot["study"]) != study:
            raise RunConflictError("Stage snapshot belongs to another study.")
        if label == "confirmation" and stage_snapshot.get("selection") != validation:
            raise RunConflictError("Confirmation differs from frozen validation selection.")
        runs.extend(_runs(directory, study, label, stage_entries))
        stage = f"{label}_partial"
        decision = next((e.payload for e in stage_entries if e.kind == kind), None)
        if decision is None:
            continue
        stage, engineering = f"{label}_complete", "complete"
        reasons = tuple(cast(list[str], decision["reasons"]))
        if label == "validation":
            if read_checked_document(directory / "selection.json") != decision:
                raise RunConflictError("Selection differs from its journal.")
            validation = decision
            verdict = (
                "incumbent_retained"
                if decision["selected_digest"] is None
                else "awaiting_confirmation"
            )
        else:
            confirmation = decision
            verdict = "promoted" if decision["promoted"] is True else "incumbent_retained"
    if (selection_root / "verification.json").exists():
        verification = read_checked_document(selection_root / "verification.json")
    if confirmation is not None and confirmation.get("selected_digest") is not None:
        assert validation is not None
        verification = require_verification(selection_root, study, canonical_digest(validation))
    if any(cast(int, _mapping(row["report"])["failed_matches"]) for row in runs):
        engineering = "failed"
    operation = (
        read_record_mapping(root / "operation.json") if (root / "operation.json").exists() else None
    )
    if operation is not None and operation.get("status") in {"failed", "interrupted"}:
        engineering = cast(str, operation["status"])
        reasons += (str(operation.get("detail", "")),)
    artifacts: list[str] = []
    for path in (
        selection_root / "selected-policy.json",
        selection_root / "confirmation/policy.json",
    ):
        if path.exists():
            artifact = PolicyArtifact.load(path)
            if (
                artifact.study_digest != study.digest()
                or validation is None
                or artifact.selection_digest != canonical_digest(validation)
                or artifact.configuration_digest != validation.get("selected_digest")
            ):
                raise RunConflictError("Artifact belongs to another study.")
            artifacts.append(str(path))
    chosen = None if validation is None else validation.get("selected_digest")
    if chosen is None:
        completed = next((entry.payload for entry in entries if entry.kind == "complete"), None)
        if completed is not None:
            # The controller owns score ties and candidate eligibility. Partial
            # runs have no frozen best and must not introduce a second ranking.
            chosen = _mapping(completed["best"])["configuration_digest"]
    selected = next(
        (_mapping(row["configuration"]) for row in runs if row["configuration_digest"] == chosen),
        None,
    )
    weights: Mapping[str, object] = (
        {} if selected is None else _mapping(_mapping(selected["baseline"])["weights"])
    )
    parameters = tuple(
        {
            "name": p.name,
            "lower": p.lower,
            "upper": p.upper,
            "incumbent": cast(float, getattr(study.incumbent.baseline.weights, p.name)),
            "candidate": weights.get(p.name),
        }
        for p in study.parameter_space.parameters
    )
    return StudyReport(
        study.study_id,
        study.digest(),
        stage,
        engineering,
        measurement,
        verdict,
        reasons,
        {
            "study": record_to_dict(study),
            "match_counts": study.match_counts(),
            "displayed_candidate_digest": chosen,
            "selected_latency": load_latency(root, study),
            "operation": operation,
            "fixed_settings": "All configuration outside parameter_space, plus "
            + "implementation and runtime, is frozen.",
            "configuration_comparison_basis": "validation selection, otherwise "
            + "best observed optimization score",
        },
        sensitivity,
        parameters,
        _method_reports(study, entries),
        tuple(runs),
        validation,
        confirmation,
        verification,
        tuple(artifacts),
    )


def _assessments_markdown(payload: Mapping[str, object] | None) -> list[str]:
    if payload is None:
        return ["Not assessed; no result is inferred from missing evidence."]
    lines = ["Reasons: " + str(payload.get("reasons", [])), ""]
    assessments = cast(list[object], payload.get("assessments", []))
    if payload.get("assessment") is not None:
        assessments = [payload["assessment"]]
    for value in assessments:
        assessment = _mapping(value)
        comparison = _mapping(assessment["comparison"])
        interval = _mapping(comparison["interval"])
        lines.extend(
            [
                f"Candidate: `{assessment['configuration_digest']}`.",
                "",
                f"Paired improvement: {comparison['mean_difference']}; interval: "
                + f"{interval.get('lower')} to {interval.get('upper')}. "
                + f"Valid evidence: {comparison['valid']}; reasons: {assessment['reasons']}.",
                "",
                "| Stratum | Value | Candidate minus incumbent |",
                "| --- | --- | ---: |",
            ]
        )
        for item in cast(list[object], assessment["strata"]):
            row = _mapping(item)
            lines.append(f"| {row['dimension']} | {row['value']} | {row['difference']} |")
        lines.append("")
    return lines


def render_study_markdown(report: StudyReport) -> str:
    lines = [
        f"# Tuning study: {report.study_id}",
        "",
        f"Stage: **{report.stage}**. Engineering: **{report.engineering}**.",
        "",
        f"Measurement: **{report.measurement}**. Policy verdict: **{report.verdict}**.",
        "",
        "Reasons: " + (", ".join(report.reasons) or "none recorded"),
        "",
        "## Parameters",
        "",
        f"Candidate: `{report.inputs['displayed_candidate_digest']}`.",
        "",
        "Comparison basis: " + str(report.inputs["configuration_comparison_basis"]),
        "",
        "| Field | Bounds | Incumbent | Candidate |",
        "| --- | --- | ---: | ---: |",
    ]
    for p in report.parameters:
        lines.append(
            f"| {p['name']} | [{p['lower']}, {p['upper']}] | {p['incumbent']} | {p['candidate']} |"
        )
    lines.extend(
        [
            "",
            "All other settings are frozen; full configuration and provenance are in "
            + "report.json inputs.study.",
            "",
            "## Optimizer work",
            "",
            "Counts exclude the shared incumbent; cache hits are not independent samples.",
            "",
            "| Method | Asked / budget | Completed | Unique | Fresh games | Cache hits | Stop |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for m in report.methods:
        lines.append(
            f"| {m['method']} | {m['asked_proposals']} / {m['proposal_budget']} | "
            + f"{m['completed_proposals']} | {m['unique_configurations']} | "
            + f"{m['fresh_matches']} | {m['cache_hits']} | {m['stop']} |"
        )
    for m in report.methods:
        lines.extend(
            [
                "",
                f"### {m['method']} best-score curve",
                "",
                "| Proposals | Fresh games | Best score (including incumbent) |",
                "| ---: | ---: | ---: |",
            ]
        )
        for point in cast(list[dict[str, object]], m["best_score_curve"]):
            lines.append(
                f"| {point['proposals']} | {point['fresh_matches']} | {point['best_score']} |"
            )
    lines.extend(
        [
            "",
            "## Runs and missing evidence",
            "",
            "| Stage | Configuration | Completed / planned | Failed | Missing | Score |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.runs:
        r = _mapping(row["report"])
        lines.append(
            f"| {row['stage']} | {row['configuration_digest']} | "
            + f"{r['completed_matches']} / {r['planned_matches']} | {r['failed_matches']} | "
            + f"{r['missing_matches']} | {r['balanced_score']} |"
        )
    lines.extend(["", "## Sensitivity", ""])
    if report.sensitivity is None:
        lines.append("Not assessed.")
    else:
        lines.extend(
            [
                f"Status: {report.measurement}; "
                + f"{report.sensitivity['observation_count']} observations. "
                + "Passing demonstrates observable effects, not stronger play.",
                "",
                "| Field | Relative score witnesses | Changed actions | Omitted best actions |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for value in cast(list[object] | tuple[object, ...], report.sensitivity["dimensions"]):
            d = _mapping(value)
            lines.append(
                f"| {d['name']} | {d['relative_score_witnesses']} | "
                + f"{d['final_action_changes']} | {d['best_action_omitted']} |"
            )
    for title, payload in (
        ("Validation (selection affected)", report.validation),
        ("Held-out confirmation", report.confirmation),
    ):
        lines.extend(["", f"## {title}", "", *_assessments_markdown(payload)])
    lines.extend(
        [
            "",
            "## Correctness verification",
            "",
            "Not run."
            if report.verification is None
            else f"Passed: {report.verification['passed']}; "
            + f"exit code: {report.verification['exit_code']}.",
        ]
    )
    lines.extend(
        [
            "",
            "## Matchup breakdowns",
            "",
            "Scores use win=1, draw=0.5, loss=0. Paired intervals above use whole blocks.",
        ]
    )
    for row in report.runs:
        lines.extend(
            [
                "",
                f"### {row['stage']} / {row['configuration_digest']}",
                "",
                "| Dimension | Value | Score |",
                "| --- | --- | ---: |",
            ]
        )
        for value in cast(list[object], _mapping(row["report"])["strata"]):
            stratum = _mapping(value)
            lines.append(
                f"| {stratum['dimension']} | {stratum['value']} | "
                + f"{_mapping(stratum['summary'])['score']} |"
            )
    lines.extend(
        [
            "",
            "## Candidate decision latency",
            "",
            "Summary-only game records do not attribute decision time to a candidate. "
            + "Those timings are explicitly not collected. Separate diagnostics use actual "
            + "candidate decisions; they never enter strategic fitness.",
            "",
        ]
    )
    latency = report.inputs["selected_latency"]
    if latency is None:
        lines.append("Selected/incumbent comparison: not collected.")
    else:
        lines.extend(["```json", dump_pretty_json(_mapping(latency)).rstrip(), "```"])
    if report.sensitivity is not None:
        lines.extend(
            [
                "",
                "Control panel samples:",
                "",
                "```json",
                dump_pretty_json({"controls": report.sensitivity["candidate_latency"]}).rstrip(),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            *(report.artifacts or ("None exported.",)),
            "",
            "## Interpretation limits",
            "",
            *(f"- {item}" for item in LIMITATIONS),
            "",
        ]
    )
    return "\n".join(lines)


def write_study_report(root: Path, *, destination: Path | None = None) -> StudyReport:
    from gwent_evaluation.tuning.html import render_study_html

    report = build_study_report(root)
    # Keep the optimization controller's own report intact for historical roots.
    destination = destination or (
        root if (root / "study.json").exists() else root / "reports/study"
    )
    atomic_write_text(destination / "report.json", dump_pretty_json(report.to_dict()))
    atomic_write_text(destination / "report.md", render_study_markdown(report))
    atomic_write_text(destination / "report.html", render_study_html(report))
    return report
