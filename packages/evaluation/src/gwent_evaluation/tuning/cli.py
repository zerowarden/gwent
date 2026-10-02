"""Tuning command presentation and path defaults; controllers own scientific decisions."""

import argparse
import os
import sys
from collections.abc import Iterator
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import cast

from gwent_shared.extract import expect_mapping
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.models import SpecError
from gwent_evaluation.progress import Progress, TerminalProgress, stage
from gwent_evaluation.provenance import default_repository_root
from gwent_evaluation.tuning.assessment import assessment_parser
from gwent_evaluation.tuning.html import write_plan_html
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.ranges import ranges_parser
from gwent_evaluation.tuning.selection import finalize_study, select_challenger, verify_selection
from gwent_evaluation.tuning.specs import load_study_spec, plan_study
from gwent_evaluation.tuning.study_report import optimization_directory, write_study_report
from gwent_evaluation.tuning.throughput import throughput_parser
from gwent_evaluation.tuning.workflow import run_tuning


def _path(variable: str, default: Path) -> Path:
    return Path(os.environ.get(variable) or default).expanduser()


def default_spec() -> Path:
    return _path("GWENT_TUNING_SPEC", default_repository_root() / "experiments/tuning/pilot.json")


def output_root() -> Path:
    return _path("GWENT_TUNING_OUTPUT_ROOT", default_repository_root() / ".output/tuning")


def _study(args: argparse.Namespace) -> StudySpec:
    study = load_study_spec(
        cast(Path | None, args.spec) or default_spec(), repository_root=default_repository_root()
    )
    identifier = cast(str | None, args.study_id) or os.environ.get("GWENT_TUNING_STUDY_ID")
    return study if not identifier else replace(study, study_id=identifier)


def _root(args: argparse.Namespace, study: StudySpec | None = None) -> Path:
    explicit = cast(Path | None, getattr(args, "study", None))
    if explicit is not None:
        return explicit
    identifier = cast(str | None, args.study_id) or os.environ.get("GWENT_TUNING_STUDY_ID")
    if not identifier:
        identifier = (
            study or load_study_spec(default_spec(), repository_root=default_repository_root())
        ).study_id
    if Path(identifier).name != identifier or identifier in {".", ".."}:
        raise SpecError("Study ID must be a single directory name.")
    return (cast(Path | None, args.output_root) or output_root()) / identifier


def tuning_parsers() -> Iterator[tuple[str, argparse.ArgumentParser]]:
    for name, help_text in (
        ("plan", "Show resolved inputs and match budgets; play no games."),
        ("run", "Run or resume sensitivity, optimization, and validation."),
        ("report", "Rebuild HTML charts, JSON and Markdown from recorded evidence; play no games."),
        ("select", "Freeze finalists and select using validation only."),
        ("verify", "Run correctness checks for the frozen challenger."),
        ("finalize", "Confirm only the frozen challenger on held-out cases."),
    ):
        parser = argparse.ArgumentParser(description=help_text)
        if name in {"plan", "run"}:
            _ = parser.add_argument(
                "spec",
                nargs="?",
                type=Path,
                help="Default: GWENT_TUNING_SPEC or experiments/tuning/pilot.json.",
            )
        else:
            _ = parser.add_argument(
                "study",
                nargs="?",
                type=Path,
                help="Workflow or optimization directory; defaults to output root / study ID.",
            )
        _ = parser.add_argument(
            "--study-id", help="Directory ID; defaults to GWENT_TUNING_STUDY_ID or the spec ID."
        )
        _ = parser.add_argument(
            "--output-root", type=Path, help="Default: GWENT_TUNING_OUTPUT_ROOT or .output/tuning."
        )
        _ = parser.add_argument(
            "--json", action="store_true", help="Print machine-readable JSON to stdout."
        )
        _ = parser.add_argument(
            "--no-progress", action="store_true", help="Disable progress on stderr."
        )
        if name in {"run", "select", "verify", "finalize"}:
            _ = parser.add_argument("--recover-lock", action="store_true")
        parser.set_defaults(handler=command)
        yield name, parser

    yield "ranges", ranges_parser()
    yield "assessment", assessment_parser()
    yield "throughput", throughput_parser()


def _print_plan(study: StudySpec, root: Path) -> None:
    print(f"Study: {study.study_id} ({study.mode.value})\nOutput: {root}")
    print(
        f"Source: {study.optimization.repository.commit}; "
        + f"clean={study.optimization.repository.is_clean_checkout}"
    )
    print(f"Incumbent: {study.incumbent.digest()}")
    for name, manifest in (
        ("Optimization", study.optimization),
        ("Validation", study.validation),
        ("Held-out test", study.test),
    ):
        suite = manifest.suite
        print(
            f"{name}: {suite.suite_id}; {len(manifest.planned_case_ids):,} "
            + f"games/candidate; seeds={suite.seeds}"
        )
        print(
            f"  Opponents: {', '.join(a.agent_id for a in suite.opponents)}; decks: "
            + f"{suite.deck_pairs}"
        )
    for optimizer in study.optimizers:
        print(
            f"{optimizer.method.value}: {optimizer.proposal_budget} proposals; "
            + f"seed={optimizer.seed}; batch={optimizer.batch_size}"
        )
    counts = study.match_counts()
    print(
        f"Game budget: optimization ≤{counts['optimization_matches']:,}; validation "
        + f"≤{counts['maximum_validation_matches']:,}; test "
        + f"≤{counts['maximum_test_matches']:,}; separate sensitivity "
        + f"≤{counts['separate_pilot_match_budget']:,}."
    )
    print("Tunable fields (incumbent; inclusive bounds):")
    for parameter in study.parameter_space.parameters:
        print(
            f"  {parameter.name}: "
            + f"{getattr(study.incumbent.baseline.weights, parameter.name):g}; "
            + f"[{parameter.lower:g}, {parameter.upper:g}]"
        )
    print(
        f"Promotion: test gain ≥{study.selection.minimum_test_improvement:.1%}; "
        + f"{study.bootstrap.confidence_level:.0%} paired interval lower >0; stratum "
        + f"decline ≤{study.selection.maximum_stratum_decline:.1%}; correctness checks pass."
    )
    print("No games played. run stops after validation; verify and finalize are explicit steps.")


def _execute(args: argparse.Namespace) -> int:
    name = cast(str, args.tune_command)
    as_json = cast(bool, args.json)
    repository = default_repository_root()
    study = _study(args) if name in {"plan", "run"} else None
    root = _root(args, study)
    if name == "plan":
        assert study is not None
        write_plan_html(study, root)
        if as_json:
            print(dump_pretty_json(plan_study(study)), end="")
        else:
            _print_plan(study, root)
            print(f"HTML plan: {root / 'plan.html'}")
        return 0
    recover = cast(bool, getattr(args, "recover_lock", False))
    if name == "run":
        assert study is not None
        run_tuning(study, output_root=root, repository_root=repository, recover_lock=recover)
    elif name != "report":
        optimization = optimization_directory(root)
        with stage(
            {
                "select": "validation",
                "verify": "correctness checks",
                "finalize": "held-out confirmation",
            }[name]
        ):
            if name == "select":
                _ = select_challenger(
                    optimization, repository_root=repository, recover_lock=recover
                )
            elif name == "verify":
                evidence = verify_selection(
                    optimization, repository_root=repository, recover_lock=recover
                )
                _ = write_study_report(root)
                _ = write_study_report(root, destination=root / "stages/verification")
                if as_json:
                    print(dump_pretty_json(evidence), end="")
                else:
                    print(
                        "Correctness checks: "
                        + f"{'passed' if evidence['passed'] else 'failed'}.\nLog: "
                        + f"{optimization / 'selection/verification.log'}"
                    )
                return 0 if evidence["passed"] else 1
            else:
                _ = finalize_study(optimization, repository_root=repository, recover_lock=recover)
    with stage("report"):
        report = write_study_report(root)
        if name in {"select", "verify", "finalize"}:
            _ = write_study_report(root, destination=root / "stages" / name)
    if as_json:
        print(dump_pretty_json(report.to_dict()), end="")
    else:
        print(
            f"Study: {report.study_id}\nStage: {report.stage}\nEngineering: "
            + f"{report.engineering}\nMeasurement: {report.measurement}\nPolicy: {report.verdict}"
        )
        if report.reasons:
            print("Reasons: " + "; ".join(report.reasons))
        for method in report.methods:
            print(
                f"{method['method']}: "
                + f"{method['completed_proposals']}/{method['proposal_budget']} "
                + f"proposals, {method['unique_configurations']} unique "
                + f"configurations, {method['fresh_matches']} fresh games, "
                + f"{method['cache_hits']} cache hits"
            )
        decision = report.confirmation or report.validation
        if decision is not None:
            print(f"Selected challenger: {decision.get('selected_digest') or 'none'}")
            assessment = decision.get("assessment")
            if assessment is not None:
                details = expect_mapping(
                    assessment, context="confirmation assessment", error_factory=SpecError
                )
                comparison = expect_mapping(
                    details["comparison"], context="comparison", error_factory=SpecError
                )
                interval = expect_mapping(
                    comparison["interval"], context="interval", error_factory=SpecError
                )
                print(
                    f"Test score: incumbent={comparison['reference_score']}; "
                    + f"challenger={comparison['candidate_score']}"
                )
                print(
                    f"Paired improvement: {comparison['mean_difference']}; "
                    + f"interval [{interval['lower']}, {interval['upper']}] "
                    + "(0.02 = 2 percentage points)."
                )
        directory = root if (root / "study.json").exists() else root / "reports/study"
        print(
            f"Read: {directory / 'report.html'}\nMarkdown: {directory / 'report.md'}"
            + f"\nJSON: {directory / 'report.json'}"
        )
        if report.verdict == "awaiting_confirmation":
            print(f"Next: tune verify {root}\nThen: tune finalize {root}")
        elif report.verdict == "incumbent_retained":
            print("Incumbent retained; no improved policy was promoted.")
        for artifact in report.artifacts:
            print(f"Policy artifact: {artifact}")
    return 0


def command(args: argparse.Namespace) -> int:
    if cast(bool, args.no_progress) or cast(str, args.tune_command) == "plan":
        return _execute(args)
    progress = TerminalProgress(sys.stderr)
    output = StringIO()
    try:
        with progress.display(), redirect_stdout(output):
            try:
                result = _execute(args)
            except BaseException:
                progress.update(Progress("tuning", "stopped; see error and study report"))
                raise
    finally:
        print(output.getvalue(), end="")
    return result
