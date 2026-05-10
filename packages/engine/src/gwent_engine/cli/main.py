from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from gwent_shared.error_translation import recover_exception
from rich.console import Console

from gwent_engine.cli.args import parse_args
from gwent_engine.cli.bot_matches import (
    available_leaders,
    available_sample_decks,
    run_bot_match_cli,
)
from gwent_engine.cli.html_report import write_bot_match_review
from gwent_engine.cli.interactive import prompt_bot_match_selection
from gwent_engine.core.errors import IllegalActionError


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    mode = cast(str, args.mode)
    return recover_exception(
        lambda: _run_report_mode(mode=mode),
        (IllegalActionError, RuntimeError, ValueError),
        _cli_failure,
    )


def _run_report_mode(*, mode: str) -> int:
    if mode != "bot-match":
        raise ValueError(f"Unsupported CLI mode: {mode!r}")
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
