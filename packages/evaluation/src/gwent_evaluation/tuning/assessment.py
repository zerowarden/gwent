"""Predeclared repeated optimizer assessment with one frozen held-out nomination."""

import argparse
from collections.abc import Mapping
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import cast

from gwent_engine.ai.arena.catalog import load_policy_bot
from gwent_engine.ai.policy_artifacts import PolicyArtifact, PolicyStatus
from gwent_shared.extract import expect_int, expect_sequence, expect_str
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.agents import candidate_from_artifact
from gwent_evaluation.execution import EvidencePolicy, execute_run
from gwent_evaluation.html_report import document, table
from gwent_evaluation.models import SpecError, SuitePurpose
from gwent_evaluation.provenance import canonical_digest, default_repository_root
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.replay import reproduce_case
from gwent_evaluation.storage import RunConflictError, atomic_write_text, read_record_mapping
from gwent_evaluation.tuning.selection import (
    SelectionResult,
    finalize_study,
    select_challenger,
    verify_selection,
)
from gwent_evaluation.tuning.specs import load_study_spec
from gwent_evaluation.tuning.storage import (
    exclusive_writer,
    read_checked_document,
    write_checked_document,
)
from gwent_evaluation.tuning.study import load_completed_study
from gwent_evaluation.tuning.study_report import write_study_report
from gwent_evaluation.tuning.workflow import run_tuning


def _freeze(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        if read_checked_document(path) != payload:
            raise RunConflictError(f"Frozen assessment changed: {path}")
    else:
        _ = write_checked_document(path, payload)


def _protocol(path: Path) -> tuple[Path, tuple[tuple[int, int], ...]]:
    raw = read_record_mapping(path)
    if (
        set(raw) != {"schema_version", "study_spec", "optimizer_seeds", "nomination"}
        or type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
    ):
        raise SpecError("Unsupported assessment protocol.")
    if raw["nomination"] != "best_qualifying_validation_score_then_study_id":
        raise SpecError("Unsupported nomination rule.")
    seeds: list[tuple[int, int]] = []
    for item in expect_sequence(
        raw["optimizer_seeds"], context="optimizer seeds", error_factory=SpecError
    ):
        values = tuple(
            expect_int(value, context="optimizer seed", error_factory=SpecError)
            for value in expect_sequence(item, context="seed pair", error_factory=SpecError)
        )
        if len(values) != 2 or min(values) < 0:
            raise SpecError("Each replicate needs nonnegative random and CMA seeds.")
        seeds.append((values[0], values[1]))
    if len(seeds) < 3 or len({seed for pair in seeds for seed in pair}) != 2 * len(seeds):
        raise SpecError("Predeclare at least three independent optimizer seed pairs.")
    spec = expect_str(raw["study_spec"], context="study spec", error_factory=SpecError)
    return path.parent / spec, tuple(seeds)


def nominate(selections: Mapping[str, SelectionResult]) -> str | None:
    candidates: list[tuple[float, str]] = []
    for identifier, selection in selections.items():
        if selection.selected is None:
            continue
        assessment = next(
            item
            for item in selection.assessments
            if item.configuration_digest == selection.selected.digest()
        )
        score = assessment.comparison.candidate_score
        assert score is not None
        candidates.append((-score, identifier))
    return None if not candidates else min(candidates)[1]


def _artifact_check(study_root: Path, output: Path, repository: Path) -> dict[str, object]:
    study, result = load_completed_study(study_root / "optimization", repository_root=repository)
    candidate = next(
        item
        for item in result.outcome.ranked_candidates
        if item.evaluation.trial.configuration_digest != study.incumbent.digest()
    )
    configuration = study.bind(candidate.coordinates)
    artifact = PolicyArtifact(
        configuration,
        PolicyStatus.UNPROMOTED,
        study.digest(),
        canonical_digest({"diagnostic_export": configuration.digest()}),
        canonical_digest(record_to_dict(candidate.evaluation.trial)),
        cast(str, study.optimization.repository.commit),
        cast(str, study.optimization.repository.implementation_digest),
    )
    path = output / "policy.json"
    atomic_write_text(path, dump_pretty_json(artifact.to_dict()))
    _ = load_policy_bot(path, bot_id="standalone-acceptance")
    base = study.optimization.suite
    suite = replace(
        base,
        suite_id="artifact-acceptance",
        purpose=SuitePurpose.SMOKE,
        candidate=candidate_from_artifact(base.candidate, path),
        opponents=(base.opponents[0],),
        deck_pairs=(base.deck_pairs[0],),
        seeds=(91201,),
    )
    run = execute_run(
        suite=suite,
        run_id="reload",
        output_root=output,
        repository_root=repository,
        evidence_policy=EvidencePolicy.ALL,
    )
    reproduced = reproduce_case(run.root, run.results[0].case_id, repository_root=repository)
    if not (reproduced.execution_identity_matches and reproduced.semantics_reproduced):
        raise SpecError("Nondefault artifact did not reproduce exactly through M1.")
    payload: dict[str, object] = {
        "artifact": str(path),
        "configuration_digest": configuration.digest(),
        "runtime_run": str(run.root),
        "reproduction": record_to_dict(reproduced),
        "status": "unpromoted_diagnostic_export",
    }
    atomic_write_text(output / "report.json", dump_pretty_json(payload))
    return payload


def run_assessment(protocol: Path, output: Path, *, recover_lock: bool = False) -> None:
    repository = default_repository_root()
    spec_path, seeds = _protocol(protocol)
    base = load_study_spec(spec_path, repository_root=repository)
    if not base.optimization.repository.is_clean_checkout:
        raise SpecError("Commit the assessment implementation and protocol before execution.")
    studies = tuple(
        replace(
            base,
            study_id=f"assessment-seed-{index}",
            optimizers=tuple(
                replace(settings, seed=seed)
                for settings, seed in zip(base.optimizers, pair, strict=True)
            ),
        )
        for index, pair in enumerate(seeds, 1)
    )
    with exclusive_writer(output, recover_lock=recover_lock):
        _freeze(
            output / "protocol.json",
            {
                "protocol": dict(read_record_mapping(protocol)),
                "studies": [record_to_dict(study) for study in studies],
                "confirmation_rule": "nominate using validation only; no runner-up after rejection",
            },
        )
        selections: dict[str, SelectionResult] = {}
        failures: dict[str, str] = {}
        for study in studies:
            root = output / study.study_id
            print(f"Starting {study.study_id}", flush=True)
            try:
                run_tuning(
                    study, output_root=root, repository_root=repository, recover_lock=recover_lock
                )
                selections[study.study_id] = select_challenger(
                    root / "optimization", repository_root=repository
                )
            except SpecError as error:
                if not str(error).startswith("insufficient_sensitivity:"):
                    raise
                failures[study.study_id] = str(error)
                print(f"Stopped {study.study_id}: {error}", flush=True)
        chosen = nominate(selections)
        # Every seed is reported, and all selection is frozen before any test games.
        _freeze(
            output / "nomination.json",
            {
                "study_id": chosen,
                "selection_digests": {name: result.digest() for name, result in selections.items()},
                "failures": failures,
            },
        )
        confirmation: dict[str, object] | None = None
        if chosen is not None:
            optimization = output / chosen / "optimization"
            if not (optimization / "selection/confirmation/snapshot.json").exists():
                verification = verify_selection(
                    optimization, repository_root=repository, recover_lock=recover_lock
                )
                if verification["passed"] is not True:
                    raise SpecError("Correctness checks failed before held-out confirmation.")
            confirmation = finalize_study(
                optimization, repository_root=repository, recover_lock=recover_lock
            ).to_dict()
        else:
            for identifier in selections:
                _ = finalize_study(
                    output / identifier / "optimization",
                    repository_root=repository,
                    recover_lock=recover_lock,
                )
        artifact = None
        if selections:
            identifier = chosen or next(iter(selections))
            artifact = _artifact_check(output / identifier, output / "artifact-check", repository)
        reports = [write_study_report(output / study.study_id) for study in studies]
        payload = {
            "source_commit": base.optimization.repository.commit,
            "seeds": seeds,
            "nomination": chosen,
            "confirmation": confirmation,
            "failures": failures,
            "replicates": [report.to_dict() for report in reports],
            "artifact_check": artifact,
        }
        atomic_write_text(output / "report.json", dump_pretty_json(payload))
        lines = [
            "# Repeated optimizer assessment",
            "",
            f"Pinned commit: `{base.optimization.repository.commit}`.",
            "",
            f"Held-out nomination: `{chosen}`. All optimizer seeds are reported below.",
            "",
            "| Replicate | Random seed | CMA seed | Stage | Policy verdict |",
            "| --- | ---: | ---: | --- | --- |",
        ]
        for report, pair in zip(reports, seeds, strict=True):
            lines.append(
                f"| [{report.study_id}]({report.study_id}/report.md) | {pair[0]} | {pair[1]} | "
                + f"{report.stage} | {report.verdict} |"
            )
        lines.extend(
            [
                "",
                "Only the nominated challenger may consume the held-out suite. "
                + "Other selected challengers remain unconfirmed. Optimization and validation "
                + "are development evidence; three seeds describe this bounded assessment, "
                + "not universal optimizer superiority.",
                "",
                "## Confirmation",
                "",
                "```json",
                dump_pretty_json(
                    confirmation or {"verdict": "incumbent_retained", "failures": failures}
                ).rstrip(),
                "```",
                "",
            ]
        )
        if artifact is not None:
            lines.extend(
                [
                    "## Runtime acceptance",
                    "",
                    "The nondefault diagnostic artifact reloaded "
                    + "through the engine factory and reproduced through M1 with matching "
                    + "execution identity and semantics.",
                    "",
                    "See [artifact check](artifact-check/report.json).",
                    "",
                ]
            )
        atomic_write_text(output / "report.md", "\n".join(lines))
        write_assessment_html(output)


def write_assessment_html(output: Path) -> None:
    protocol = read_checked_document(output / "protocol.json")
    studies = cast(list[Mapping[str, object]], protocol["studies"])
    reports = [write_study_report(output / str(study["study_id"])) for study in studies]
    links = (
        "<ul>"
        + "".join(
            f'<li><a href="{escape(r.study_id, quote=True)}/report.html">{escape(r.study_id)}: '
            + f"{escape(r.verdict)}</a></li>"
            for r in reports
        )
        + "</ul>"
    )
    rows = [(r.study_id, r.stage, r.verdict) for r in reports]
    atomic_write_text(
        output / "report.html",
        document(
            "Repeated optimizer assessment",
            "All predeclared seeds are shown. "
            + "Open a replicate for CMA-ES charts, validation reasons and weights.",
            [
                ("Replicates", links + table(["Study", "Stage", "Policy verdict"], rows)),
                (
                    "Interpretation",
                    "<p>Optimization and validation are development evidence. "
                    + "A completed retention decision can use zero held-out games. "
                    + "Repeated optimizer seeds do not add independent validation games.</p>",
                ),
            ],
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output", type=Path, default=Path(".output/acceptance/assessment"))
    _ = parser.add_argument(
        "--protocol",
        type=Path,
        default=default_repository_root() / "experiments/tuning/assessment.json",
    )
    _ = parser.add_argument("--recover-lock", action="store_true")
    _ = parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if cast(bool, args.report_only):
        write_assessment_html(cast(Path, args.output))
        return
    run_assessment(
        cast(Path, args.protocol),
        cast(Path, args.output),
        recover_lock=cast(bool, args.recover_lock),
    )


if __name__ == "__main__":
    main()
