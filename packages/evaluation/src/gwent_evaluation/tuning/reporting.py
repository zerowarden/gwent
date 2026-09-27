"""Human explanations and tabular exports derived from typed, verified results."""

import csv
from collections.abc import Mapping
from io import StringIO
from pathlib import Path
from shlex import quote
from typing import cast

from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.output import RUN_FILES
from gwent_evaluation.storage import atomic_write_text
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.study import StudyResult


def render_pilot_readme(
    study: StudySpec,
    stages: Mapping[str, str],
    *,
    detail: str | None = None,
    repository_root: Path | None = None,
    output_root: Path | None = None,
    sensitivity: SensitivityReport | None = None,
    result: StudyResult | None = None,
) -> str:
    lines = ["# Weight tuning pilot", "", "| Stage | Status |", "| --- | --- |"]
    lines.extend(f"| {name} | {status} |" for name, status in stages.items())
    if detail:
        lines.extend(["", f"Stopped: {detail}"])
    counts = study.match_counts()
    lines.extend(
        [
            "",
            "## What ran",
            "",
            f"Optimization allows {counts['proposal_slots']} proposals, plus the shared incumbent, "
            + f"at {counts['optimize_per_candidate']} matches per configuration. "
            + "Smoke is a separate execution check. Sensitivity uses a separate control panel. "
            + "Validation and test games are not run, and no configuration is promoted.",
            "",
            "Balanced match scores give a win 1, a draw 0.5, and a loss 0, with equal "
            + "weight for opponent/deck/root blocks. Optimization selects on these same games: "
            + "a gain can reflect noise or overfitting and needs independent validation.",
        ]
    )
    if result is not None:
        incumbent_score = result.incumbent.evaluation.trial.require_eligible_score()
        best_score = result.outcome.best.evaluation.trial.require_eligible_score()
        lines.extend(
            [
                "",
                "## Optimization results",
                "",
                f"Incumbent score: **{incumbent_score:.2%}**. "
                + f"Best observed score: **{best_score:.2%}**. "
                + f"Gain: **{100 * result.outcome.optimization_score_gain:+.2f} pp**.",
                "",
                "| Method | Proposals | Best proposal | Selection including incumbent | Stop |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for method in result.methods:
            proposed = max(
                (t.evaluation.trial.require_eligible_score() for t in method.trials), default=None
            )
            proposed_text = "none" if proposed is None else f"{proposed:.2%}"
            selected = method.outcome.best.evaluation.trial.require_eligible_score()
            lines.append(
                f"| {method.method.value} | {method.outcome.counts.proposals} | {proposed_text} | "
                + f"{selected:.2%} | {method.stop.reason.value} |"
            )
        work = result.outcome.counts
        lines.extend(
            [
                "",
                f"Study lifetime: {work.fresh_matches:,} matches, "
                + f"{work.distinct_configurations} distinct configurations, "
                + f"{work.cache_hits} cache hits. "
                + "The overall total includes the incumbent once. Method totals each include "
                + "that shared incumbent and must not be added together.",
                "",
                "## Selected weights",
                "",
                "Each coefficient multiplies a different feature; magnitudes are not directly "
                + "comparable. Negative coefficients penalize features. Moving a penalty toward "
                + "zero weakens it. Bounds are engineering choices, not proven optimal limits.",
                "",
                "| Weight | Allowed range | Incumbent | Selected best |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        chosen = study.bind(result.outcome.best.coordinates)
        for parameter in study.parameter_space.parameters:
            before = cast(float, getattr(study.incumbent.baseline.weights, parameter.name))
            after = cast(float, getattr(chosen.baseline.weights, parameter.name))
            lines.append(
                f"| {parameter.name} | [{parameter.lower:g}, "
                + f"{parameter.upper:g}] | {before:.5g} | {after:.5g} |"
            )
    if sensitivity is not None:
        lines.extend(
            [
                "",
                "## Sensitivity",
                "",
                f"Status: **{sensitivity.status}**; "
                + f"{sensitivity.planned_matches} scheduled matches "
                + f"and {sensitivity.observation_count} decision observations. "
                + "Passing shows observable effects, not improved playing strength. "
                + "This panel uses different seeds, so its scores are not "
                + "comparable with optimization scores.",
                "",
                "| Control | Score | Changed outcomes | Changed action traces |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for control in sensitivity.controls:
            score = (
                "incomplete" if control.balanced_score is None else f"{control.balanced_score:.2%}"
            )
            lines.append(
                f"| {control.name} | {score} | "
                + f"{control.changed_match_outcomes} | {control.changed_action_traces} |"
            )
        if sensitivity.reasons:
            lines.extend(["", "Gate failures: " + "; ".join(sensitivity.reasons)])
    lines.extend(
        [
            "",
            "## Files and provenance",
            "",
            f"Source commit: `{study.optimization.repository.commit}`. "
            + "Source, runtime, lockfile, and asset digests are frozen in the input snapshots. "
            + "No source checkout or environment is stored here.",
            "",
            "| Path | Meaning |",
            "| --- | --- |",
            "| [inputs/study.json](inputs/study.json) | Immutable resolved study and checksum. |",
            "| [inputs/smoke.json](inputs/smoke.json) | Immutable smoke manifest and checksum. |",
            "| [reports/plan.json](reports/plan.json) | Frozen settings and "
            + "planned budgets; no results. |",
            "| [workflow.json](workflow.json) | Derived stage status, "
            + "reasons, and operational counts. |",
            "| [logs/events.jsonl](logs/events.jsonl) | Operational progress; "
            + "not scientific evidence. |",
            "| `writer.lock` | Persistent process ownership marker; do not delete to unlock. |",
            "| `data/smoke/` | Smoke run in the evaluation format described below. |",
            "| `data/sensitivity/` | Study snapshot, control runs, and sensitivity report. |",
            "| `data/optimization/` | Frozen study/evidence, immutable "
            + "journal, and candidate runs. |",
            "",
            "Inside optimization, `journal/*.json` records incumbent, ask, trial, tell, "
            + "stop, and completion events. `runs/trial-<identity>/` holds match evidence; "
            + "`report.json` is derived. Stage snapshots repeat their required inputs so each "
            + "stage can verify its own evidence independently.",
            "",
            RUN_FILES,
        ]
    )
    if result is not None:
        lines.extend(
            [
                "- [Every proposal and raw weight](reports/trials.csv)",
                "- [Full incumbent and selected configurations](reports/configurations.json)",
                "- [Machine-readable optimization report](data/optimization/report.json)",
            ]
        )
    if sensitivity is not None:
        lines.append("- [Detailed sensitivity witnesses](data/sensitivity/report.json)")
    lines.extend(
        [
            "",
            "## Resume",
            "",
            "Run `make pilot` again from the same clean checkout and pinned environment. "
            + "Completed games are verified and reused. Changed inputs require a different output "
            + "directory or an intentional reset. After process death use "
            + "`python -m gwent_evaluation tune pilot --recover-lock`; a live "
            + "writer cannot be displaced. "
            + "Reports and status are regenerable; inputs, journals, and match records "
            + "must never be edited or silently repaired.",
            "",
        ]
    )
    if repository_root is not None and output_root is not None:
        command = (
            f"make -C {quote(str(repository_root.resolve()))} pilot "
            + f"PILOT_OUTPUT={quote(str(output_root.resolve()))}"
        )
        lines.extend(
            [
                "Recorded checkout and output locations for this run:",
                "",
                "```bash",
                command,
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def write_pilot_exports(root: Path, study: StudySpec, result: StudyResult) -> None:
    configurations = {
        "incumbent": study.incumbent.to_dict(),
        "best": study.bind(result.outcome.best.coordinates).to_dict(),
    }
    configurations.update(
        {
            method.method.value: study.bind(method.outcome.best.coordinates).to_dict()
            for method in result.methods
        }
    )
    atomic_write_text(root / "configurations.json", dump_pretty_json(configurations))
    stream = StringIO()
    names = [parameter.name for parameter in study.parameter_space.parameters]
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "method",
            "proposal_index",
            "score",
            "gain_over_incumbent",
            "cache_hit",
            "configuration_digest",
            *names,
        ],
    )
    writer.writeheader()
    reference = result.incumbent.evaluation.trial.require_eligible_score()
    candidates = [("incumbent", -1, result.incumbent)]
    candidates.extend(
        (method.method.value, index, candidate)
        for method in result.methods
        for index, candidate in enumerate(method.trials)
    )
    for method, index, candidate in candidates:
        trial = candidate.evaluation.trial
        weights = study.bind(candidate.coordinates).baseline.weights
        writer.writerow(
            {
                "method": method,
                "proposal_index": index,
                "score": trial.require_eligible_score(),
                "gain_over_incumbent": trial.require_eligible_score() - reference,
                "cache_hit": candidate.evaluation.cache_hit,
                "configuration_digest": trial.configuration_digest,
                **{name: cast(float, getattr(weights, name)) for name in names},
            }
        )
    atomic_write_text(root / "trials.csv", stream.getvalue())
