"""Human explanations and optimizer charts over the shared study report model."""

from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import cast

from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.html_report import chart, document, percent, table
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.storage import atomic_write_text
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.report_models import StudyReport
from gwent_evaluation.tuning.specs import plan_study


def assessment_html(payload: Mapping[str, object] | None) -> str:
    if payload is None:
        return "<p>Not assessed. No conclusion is inferred from missing games.</p>"
    assessments = cast(list[Mapping[str, object]], payload.get("assessments", []))
    if payload.get("assessment") is not None:
        assessments = [cast(Mapping[str, object], payload["assessment"])]
    rows: list[tuple[object, ...]] = []
    for assessment in assessments:
        comparison = cast(Mapping[str, object], assessment["comparison"])
        interval = cast(Mapping[str, object], comparison["interval"])
        reasons = cast(list[str], assessment["reasons"])
        rows.append(
            (
                str(assessment["configuration_digest"])[7:19],
                percent(comparison["reference_score"]),
                percent(comparison["candidate_score"]),
                percent(comparison["mean_difference"], difference=True),
                f"{percent(interval['lower'], difference=True)} to "
                + percent(interval["upper"], difference=True),
                "; ".join(reason.replace("_", " ") for reason in reasons) or "Passed these checks",
            )
        )
    return (
        '<p class="note">A positive average alone is insufficient. The paired interval must '
        + "exclude zero, and each protected deck/opponent must satisfy the decline limit. "
        + "An interval crossing zero means the improvement remains uncertain.</p>"
        + table(
            ["Candidate", "Original", "Candidate", "Change", "Paired interval", "Decision"], rows
        )
        + f"<p>Stage reasons: {escape(str(payload.get('reasons', [])))}</p>"
    )


def render_study_html(report: StudyReport) -> str:
    series: dict[str, list[Mapping[str, object]]] = {
        str(method["method"]): cast(list[Mapping[str, object]], method["best_score_curve"])
        for method in report.methods
    }
    progress = "<p>Higher scores are better. Curves include the incumbent. "
    progress += "These are optimization results, not evidence of promotion.</p>"
    for axis, label in (("proposals", "Completed proposals"), ("fresh_matches", "Fresh games")):
        progress += chart(
            "Best observed optimization score",
            [
                (
                    name,
                    [(float(cast(float, p[axis])), cast(float, p["best_score"])) for p in points],
                )
                for name, points in series.items()
            ],
            xlabel=label,
            ylabel="Balanced score (0-1)",
        )
    cma = series.get("cma_es", [])
    progress += "<h3>CMA-ES evaluated populations</h3>"
    cma_method = next((m for m in report.methods if m["method"] == "cma_es"), None)
    generations = (
        [] if cma_method is None else cast(list[Mapping[str, object]], cma_method["generations"])
    )
    progress += chart(
        "CMA-ES generation scores",
        [
            (name, [(cast(int, p["generation"]), cast(float, p[name])) for p in generations])
            for name in ("best", "median", "worst")
        ],
        xlabel="Completed generation",
        ylabel="Balanced score (0-1)",
    )
    progress += chart(
        "CMA-ES candidate scores",
        [
            (
                "Candidate score",
                [(cast(int, p["proposals"]), cast(float, p["candidate_score"])) for p in cma],
            )
        ],
        xlabel="Completed proposal",
        ylabel="Balanced score (0-1)",
    )
    progress += "<p>Hover over chart points for values. Parameter charts show evaluated "
    progress += "proposals in generation order, normalized to the declared bounds. "
    progress += "They do not represent CMA covariance or internal distribution means.</p>"
    for index, parameter in enumerate(report.parameters):
        points = [
            (cast(int, p["proposals"]), cast(list[float], p["coordinates"])[index]) for p in cma
        ]
        progress += f"<details><summary>{escape(str(parameter['name']))}</summary>"
        progress += (
            chart(
                str(parameter["name"]),
                [("CMA-ES proposals", points)],
                xlabel="Completed proposal",
                ylabel="Normalized value (0=lower bound, 1=upper bound)",
            )
            + "</details>"
        )
    sensitivity = "<p>Not assessed.</p>"
    if report.sensitivity is not None:
        dimensions = cast(list[Mapping[str, object]], report.sensitivity["dimensions"])
        sensitivity = (
            "<p>Changing a weight can affect decisions without improving play.</p>"
            + table(
                ["Weight", "Score witnesses", "Changed decisions", "Best action omitted"],
                [
                    (
                        d["name"],
                        d["relative_score_witnesses"],
                        d["final_action_changes"],
                        d["best_action_omitted"],
                    )
                    for d in dimensions
                ],
            )
        )
    runs: list[tuple[object, ...]] = []
    for run in report.runs:
        metrics = cast(Mapping[str, object], run["report"])
        runs.append(
            (
                run["stage"],
                str(run["configuration_digest"])[7:19],
                f"{metrics['completed_matches']}/{metrics['planned_matches']}",
                metrics["failed_matches"],
                metrics["missing_matches"],
                percent(metrics["balanced_score"]),
            )
        )
    return document(
        f"Tuning: {report.study_id}",
        f"Stage: {report.stage}. Engineering: {report.engineering}. "
        + f"Measurement: {report.measurement}. Policy: {report.verdict}.",
        [
            (
                "Summary",
                f"<p>{escape('; '.join(report.reasons) or 'No rejection recorded.')}</p>"
                + (
                    '<p><a href="report.json">Full JSON evidence</a> · <a '
                    'href="report.md">Markdown report</a></p>'
                ),
            ),
            ("Sensitivity", sensitivity),
            ("Optimization charts", progress),
            ("Validation", assessment_html(report.validation)),
            ("Held-out confirmation", assessment_html(report.confirmation)),
            (
                "Weights",
                table(
                    ["Parameter", "Lower", "Upper", "Original", "Displayed candidate"],
                    [
                        (p["name"], p["lower"], p["upper"], p["incumbent"], p["candidate"])
                        for p in report.parameters
                    ],
                ),
            ),
            (
                "Game completion",
                table(["Stage", "Candidate", "Completed", "Failed", "Missing", "Score"], runs),
            ),
            (
                "Interpretation",
                (
                    "<p>Fixed decks and opponents limit generalization. Validation is "
                    "used for selection. "
                )
                + (
                    "Only a qualifying held-out confirmation supports promotion. No "
                    "confirmation games "
                )
                + "are required when validation retains the incumbent.</p>",
            ),
        ],
    )


def write_plan_html(study: StudySpec, root: Path) -> None:
    plan = plan_study(study)
    atomic_write_text(root / "plan.json", dump_pretty_json(plan))
    atomic_write_text(
        root / "plan.html",
        document(
            f"Plan: {study.study_id}",
            "No games have been played by this planning command.",
            [
                ("Budgets", table(["Item", "Count"], list(study.match_counts().items()))),
                (
                    "Benchmark",
                    table(
                        ["Stage", "Suite", "Deck pairings", "Seeds", "Games per policy"],
                        [
                            (
                                name,
                                m.suite.suite_id,
                                len(m.suite.deck_pairs),
                                len(m.suite.seeds),
                                len(m.planned_case_ids),
                            )
                            for name, m in [
                                ("Optimization", study.optimization),
                                ("Validation", study.validation),
                                ("Test", study.test),
                            ]
                        ],
                    ),
                ),
                (
                    "Frozen definitions",
                    "<details><summary>Resolved plan and source identity</summary><pre>"
                    + escape(dump_pretty_json({**plan, "study": record_to_dict(study)}))
                    + "</pre></details>",
                ),
            ],
        ),
    )
