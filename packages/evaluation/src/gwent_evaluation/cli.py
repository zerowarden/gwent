"""Noninteractive evaluation commands.

`run`, `report`, `replay`, and `compare` are the whole M1 surface: M2 consumes
the typed Python API and spec system rather than extending this CLI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from gwent_evaluation.agents import AgentResolutionError
from gwent_evaluation.execution import EvidencePolicy, execute_run
from gwent_evaluation.models import SuiteSpec
from gwent_evaluation.records import StorageError
from gwent_evaluation.replay import (
    ReplayError,
    ReplayOutcome,
    ReproductionOutcome,
    replay_case,
    reproduce_case,
)
from gwent_evaluation.reporting import (
    ReportError,
    compare_runs,
    render_comparison_markdown,
    render_report_markdown,
    report_run,
)
from gwent_evaluation.schedule import ScheduleError
from gwent_evaluation.specs import (
    SpecError,
    load_agent_catalog,
    load_suite_catalog,
)

EXIT_OK = 0
EXIT_DIVERGENCE = 1
EXIT_ERROR = 2

_USER_ERRORS = (
    AgentResolutionError,
    ReportError,
    ReplayError,
    ScheduleError,
    SpecError,
    StorageError,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handler = cast(Callable[[argparse.Namespace], int], args.handler)
    try:
        return int(handler(args))
    except _USER_ERRORS as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gwent_evaluation",
        description="Reproducible Gwent agent evaluation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute a suite and persist a run directory.")
    _ = run_parser.add_argument(
        "catalog",
        nargs="?",
        type=Path,
        default=None,
        help="Suite catalog JSON (default: experiments/suites.json).",
    )
    _ = run_parser.add_argument(
        "--suite",
        default=None,
        help="Suite id inside the catalog; only needed when several are declared.",
    )
    _ = run_parser.add_argument(
        "--agents-catalog",
        type=Path,
        default=None,
        help="Agent catalog JSON (default: experiments/agents.json).",
    )
    _ = run_parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".output/experiments"),
        help="Directory that holds run directories.",
    )
    _ = run_parser.add_argument(
        "--run-id",
        default=None,
        help="Run directory name; reuse it to resume an interrupted run.",
    )
    _ = run_parser.add_argument(
        "--evidence-policy",
        choices=[policy.value for policy in EvidencePolicy],
        default=EvidencePolicy.ALL.value,
        help="Which cases persist privileged trajectory evidence.",
    )
    run_parser.set_defaults(handler=_cmd_run)

    report_parser = subparsers.add_parser(
        "report", help="Rebuild and print the report of a run directory."
    )
    _ = report_parser.add_argument("run", type=Path, help="Run directory.")
    report_parser.set_defaults(handler=_cmd_report)

    replay_parser = subparsers.add_parser("replay", help="Replay one recorded case.")
    _ = replay_parser.add_argument("run", type=Path, help="Run directory.")
    _ = replay_parser.add_argument("--case", required=True, help="Scheduled case id.")
    _ = replay_parser.add_argument(
        "--reproduce",
        action="store_true",
        help="Re-run the declared agents instead of replaying recorded actions.",
    )
    replay_parser.set_defaults(handler=_cmd_replay)

    compare_parser = subparsers.add_parser(
        "compare", help="Compare a reference run with a candidate run."
    )
    _ = compare_parser.add_argument("reference", type=Path, help="Reference run directory.")
    _ = compare_parser.add_argument("candidate", type=Path, help="Candidate run directory.")
    compare_parser.set_defaults(handler=_cmd_compare)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    suites_path = cast(Path | None, args.catalog) or _default_suites_path()
    agents_path = cast(Path | None, args.agents_catalog) or _default_agents_path()
    suites = load_suite_catalog(suites_path, agents=load_agent_catalog(agents_path))
    suite = _select_suite(suites, suite_id=cast(str | None, args.suite), catalog=suites_path)
    run_id = cast(str | None, args.run_id)
    execution = execute_run(
        suite=suite,
        run_id=run_id or _default_run_id(suite.suite_id),
        output_root=cast(Path, args.output_root),
        repository_root=_repository_root(),
        evidence_policy=EvidencePolicy(cast(str, args.evidence_policy)),
    )
    report = report_run(execution.root)
    print(f"run: {execution.root}")
    print(
        f"executed={len(execution.executed_case_ids)} "
        + f"resumed={len(execution.resumed_case_ids)}"
    )
    print(render_report_markdown(report), end="")
    return EXIT_OK


def _cmd_report(args: argparse.Namespace) -> int:
    report = report_run(cast(Path, args.run))
    print(render_report_markdown(report), end="")
    return EXIT_OK


def _cmd_replay(args: argparse.Namespace) -> int:
    run_root = cast(Path, args.run)
    case_id = cast(str, args.case)
    outcome: ReplayOutcome | ReproductionOutcome
    if cast(bool, args.reproduce):
        outcome = reproduce_case(run_root, case_id)
    else:
        replay_outcome = replay_case(run_root, case_id)
        if replay_outcome.prefix_only:
            print(f"prefix_only: {replay_outcome.case_id} did not complete in the recorded run")
        outcome = replay_outcome
    verdict = "yes" if outcome.reproduced else "no"
    print(f"case: {outcome.case_id} termination={outcome.termination.value} reproduced={verdict}")
    for divergence in outcome.divergences:
        print(
            f"  index={divergence.index} field={divergence.field} "
            + f"expected={divergence.expected!r} actual={divergence.actual!r}"
        )
    return EXIT_OK if outcome.reproduced else EXIT_DIVERGENCE


def _cmd_compare(args: argparse.Namespace) -> int:
    comparison = compare_runs(cast(Path, args.reference), cast(Path, args.candidate))
    print(render_comparison_markdown(comparison), end="")
    return EXIT_OK if comparison.compatible else EXIT_DIVERGENCE


def _select_suite(
    suites: dict[str, SuiteSpec],
    *,
    suite_id: str | None,
    catalog: Path,
) -> SuiteSpec:
    if suite_id is None:
        if len(suites) != 1:
            declared = ", ".join(sorted(suites))
            raise SpecError(
                f"{catalog} declares several suites; select one with --suite: {declared}."
            )
        suite_id = next(iter(suites))
    try:
        return suites[suite_id]
    except KeyError as error:
        raise SpecError(f"Unknown suite id {suite_id!r} in {catalog}.") from error


def _default_run_id(suite_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{suite_id}-{timestamp}"


def _default_suites_path() -> Path:
    return _repository_root() / "experiments" / "suites.json"


def _default_agents_path() -> Path:
    return _repository_root() / "experiments" / "agents.json"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


__all__ = ["EXIT_DIVERGENCE", "EXIT_ERROR", "EXIT_OK", "main"]
