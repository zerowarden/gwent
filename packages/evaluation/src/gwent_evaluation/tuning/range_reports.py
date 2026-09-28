"""Presentation of benchmark coverage, one-weight sweeps, and independent rechecks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from typing import cast

from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.html_report import chart, document, percent, table
from gwent_evaluation.metrics import summarize_scores
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.storage import atomic_write_text
from gwent_evaluation.tuning.html import assessment_html
from gwent_evaluation.tuning.models import StudySpec, SweepPoint
from gwent_evaluation.tuning.objective import RecordedEvaluation


def index_sections(rows: Sequence[Mapping[str, object]] = ()) -> list[tuple[str, str]]:
    links = [
        ("Plan", "plan"),
        ("Sensitivity", "sensitivity"),
        ("Benchmark", "benchmark"),
        ("Screening", "screening"),
        ("Recheck", "recheck"),
    ]
    return [
        (
            "Stages",
            "<ul>"
            + "".join(
                f'<li><a href="{directory}/report.html">{name}</a></li>'
                for name, directory in links
            )
            + "</ul>",
        ),
        (
            "Recheck results",
            table(
                ["Weight", "Value tested", "Independent change", "Conclusion"],
                [
                    (
                        r["parameter"],
                        r["value"],
                        percent(r["difference"], difference=True),
                        r["interpretation"],
                    )
                    for r in rows
                ],
            )
            if rows
            else "<p>No completed recheck results yet.</p>",
        ),
        (
            "Interpretation",
            "<p>Rechecks use separate development seeds. They do not authorize promotion. "
            + "Multiple comparisons and interactions between weights limit conclusions. "
            + "Bounds and incumbent weights are never changed automatically. An improving boundary "
            + "value motivates a new experiment; signs remain part of the parameter contract.</p>",
        ),
    ]


def write_report(
    root: Path,
    title: str,
    explanation: str,
    payload: Mapping[str, object],
    sections: Sequence[tuple[str, str]],
) -> None:
    atomic_write_text(root / "report.json", dump_pretty_json(payload))
    atomic_write_text(root / "report.html", document(title, explanation, sections))
    atomic_write_text(
        root / "report.md",
        f"# {title}\n\n{explanation}\n\nRead [the HTML report](report.html) "
        + "for charts and tables, or [JSON](report.json) for full evidence.\n",
    )


def write_range_plan(
    study: StudySpec, points: tuple[SweepPoint, ...], root: Path
) -> dict[str, object]:
    plan: dict[str, object] = {
        "study": record_to_dict(study),
        "points": [record_to_dict(p) for p in points],
        "screening_configurations": len(points) + 1,
        "screening_games": (len(points) + 1) * len(study.optimization.planned_case_ids),
        "maximum_recheck_games": (len(study.parameter_space.parameters) + 1)
        * len(study.validation.planned_case_ids),
        "sensitivity_game_budget": study.sensitivity.max_pilot_matches,
        "held_out_games": 0,
    }
    write_report(
        root / "plan",
        "Range investigation plan",
        (
            "One weight changes at a time. All other settings stay fixed. No "
            "final test games are scheduled."
        ),
        plan,
        [
            (
                "Budget",
                table(
                    ["Item", "Count"],
                    [(k, v) for k, v in plan.items() if k not in {"study", "points"}],
                ),
            ),
            (
                "Sweep values",
                table(
                    ["Weight", "Original", "Values"],
                    [
                        (
                            p.name,
                            getattr(study.incumbent.baseline.weights, p.name),
                            ", ".join(f"{x.value:g}" for x in points if x.parameter == p.name),
                        )
                        for p in study.parameter_space.parameters
                    ],
                ),
            ),
            ("Benchmark", table(["Deck A", "Deck B"], study.optimization.suite.deck_pairs)),
        ],
    )
    return plan


def write_benchmark(root: Path, reference: RecordedEvaluation) -> None:
    groups: dict[tuple[str, str], list[float]] = {}
    for match in reference.loaded.matches:
        result = reference.loaded.results[match.case_id]
        assert result.candidate_score is not None
        groups.setdefault((match.candidate_deck_id, match.opponent_deck_id), []).append(
            result.candidate_score
        )
    rows = [
        (a, b, len(scores), percent(summarize_scores(scores).score))
        for (a, b), scores in sorted(groups.items())
    ]
    write_report(
        root,
        "Incumbent benchmark",
        (
            "These scores describe the original policy in each matchup. They "
            "do not measure deck strength independently of policy. Extreme "
            "scores may leave little room for tuning to change outcomes."
        ),
        record_to_dict(reference.report),
        [
            ("Matchup matrix", table(["Candidate deck", "Opponent deck", "Games", "Score"], rows)),
            (
                "Weighting",
                (
                    "<p>The objective weights complete opponent/deck-pair/seed blocks "
                    "equally. Mirror blocks contain four games and cross-deck blocks "
                    "eight. Matchup scores above are descriptive game averages.</p>"
                ),
            ),
        ],
    )


def write_stage_report(
    root: Path,
    study: StudySpec,
    rows: Sequence[Mapping[str, object]],
    total: int,
    *,
    recheck: bool,
    status: str,
) -> None:
    sections: list[tuple[str, str]] = [
        (
            "Progress",
            f"<p>Status: {escape(status)}. Completed candidates: {len(rows)}/{total}. "
            + (
                "Positive differences favor the candidate. Intervals crossing zero"
                " indicate uncertainty.</p>"
            ),
        )
    ]
    for parameter in study.parameter_space.parameters:
        values = sorted(
            [r for r in rows if r["parameter"] == parameter.name],
            key=lambda r: cast(float, r["value"]),
        )
        if not values:
            continue
        default = cast(float, getattr(study.incumbent.baseline.weights, parameter.name))
        plot = chart(
            parameter.name,
            [
                (
                    "Candidate minus original",
                    sorted(
                        [(default, 0.0)]
                        + [
                            (cast(float, r["value"]), 100 * cast(float, r["difference"]))
                            for r in values
                        ]
                    ),
                )
            ],
            xlabel="Weight value",
            ylabel="Score difference (percentage points)",
        )
        content = table(
            ["Weight value", "Score", "Change", "Paired interval", "Interpretation"],
            [
                (
                    r["value"],
                    percent(r["score"]),
                    percent(r["difference"], difference=True),
                    f"{percent(r['lower'], difference=True)} to "
                    + percent(r["upper"], difference=True),
                    r["interpretation"],
                )
                for r in values
            ],
        )
        sections.append((parameter.name, plot + content))
    if recheck:
        sections.append(
            ("Detailed checks", assessment_html({"assessments": [r["assessment"] for r in rows]}))
        )
    write_report(
        root,
        "Range recheck" if recheck else "Range screening",
        "Independent development seeds; no policy is promoted."
        if recheck
        else "Exploratory comparisons nominate one improving value per weight. "
        + "Intervals are not adjusted for testing many values.",
        {
            "status": status,
            "completed": len(rows),
            "planned": total,
            "rows": list(rows),
            "promotion": "not_assessed",
        },
        sections,
    )
