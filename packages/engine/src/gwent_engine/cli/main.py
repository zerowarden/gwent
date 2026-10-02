from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console

from gwent_engine.cli.bot_matches import (
    available_leaders,
    available_sample_decks,
    run_bot_match_cli,
)
from gwent_engine.cli.interactive import prompt_bot_match_selection
from gwent_engine.cli.report import write_bot_match_review
from gwent_engine.core.errors import IllegalActionError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic bot-vs-bot Gwent matches for developer inspection."
    )
    _ = parser.add_argument(
        "--mode",
        choices=("bot-match",),
        default="bot-match",
        help="Run the interactive bot match builder.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    _ = parse_args(argv)
    try:
        return _run_bot_match()
    except (IllegalActionError, RuntimeError, ValueError) as exc:
        return _cli_failure(exc)


def _run_bot_match() -> int:
    selection = prompt_bot_match_selection(
        decks=available_sample_decks(),
        leaders=available_leaders(),
    )
    run = run_bot_match_cli(
        player_one_bot_spec=selection.player_one_bot_spec,
        player_two_bot_spec=selection.player_two_bot_spec,
        player_one_deck_id=selection.player_one_deck_id,
        player_two_deck_id=selection.player_two_deck_id,
        player_one_leader_id=selection.player_one_leader_id,
        player_two_leader_id=selection.player_two_leader_id,
        seed=selection.seed,
        starting_player=selection.starting_player,
        include_bot_explanations=True,
    )
    report_path = write_bot_match_review(
        run,
        player_one_bot_spec=selection.player_one_bot_spec,
        player_two_bot_spec=selection.player_two_bot_spec,
        seed=selection.seed,
    )
    _print_report_paths(report_path)
    return 0


def _print_report_paths(report_path: Path) -> None:
    Console().print(f"Review bundle: {report_path.parent}", style="bold cyan")
    Console().print(f"HTML review report: {report_path}", style="bold cyan")


def _cli_failure(exc: BaseException) -> int:
    Console(stderr=True).print(f"CLI run failed: {exc}", style="bold red")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
