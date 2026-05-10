from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping

from rich import box
from rich.console import Console, Group
from rich.json import JSON
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from gwent_engine.cli.models import CliRun, CliStep
from gwent_engine.cli.presenters import (
    event_type_name,
    metadata_items,
    pending_choice_items,
    render_action_label,
    round_ended_event,
    summarize_action,
    summarize_event,
    winner_text,
)
from gwent_engine.cli.view_formatters import board_row_label, card_list_text
from gwent_engine.core import GameStatus
from gwent_engine.core.events import RoundEndedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.serialize import game_state_to_dict

P1_STYLE = "bold blue"
P2_STYLE = "bold red"
VALUE_STYLE = "bold dark_orange3"


def render_human(
    run: CliRun,
    *,
    console: Console | None = None,
    show_state: bool = False,
) -> None:
    active_console = console or Console()
    active_console.print(Rule(f"Gwent CLI Run: {run.scenario_name}", style="bold cyan"))
    active_console.print(_build_metadata_panel(run))
    active_console.print(Rule("Action Trace", style="bold white"))
    for step in run.steps:
        _render_step(
            step,
            run=run,
            console=active_console,
            card_names_by_instance_id=run.card_names_by_instance_id,
            card_values_by_instance_id=run.card_values_by_instance_id,
        )
    if run.pending_choice_state is not None and run.pending_choice_state.pending_choice is not None:
        active_console.print(Rule("Pending Choice", style="bold magenta"))
        active_console.print(_build_pending_choice_panel(run))
    active_console.print(Rule("Final Summary", style="bold green"))
    active_console.print(_build_summary_table(run.final_state))
    active_console.print(
        _build_board_table(
            run.final_state,
            run,
            run.final_strengths_by_instance_id,
        )
    )
    active_console.print(_build_hand_table(run.final_state, run))
    active_console.print(_build_deck_table(run.final_state, run))
    if show_state:
        active_console.print(Rule("Final State JSON", style="bold white"))
        active_console.print(JSON(json.dumps(game_state_to_dict(run.final_state), indent=2)))


def _build_metadata_panel(run: CliRun) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    for label, value in (
        ("Scenario", run.scenario_name),
        *metadata_items(run.metadata),
    ):
        table.add_row(label, _stylize_player_ids(value))
    return Panel(table, title="Metadata", border_style="cyan")


def _render_step(
    step: CliStep,
    *,
    run: CliRun,
    console: Console,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> None:
    action_row = Table.grid(expand=False, padding=(0, 1))
    action_row.add_column(no_wrap=True)
    action_row.add_column(ratio=1)
    action_row.add_row(
        render_action_label(step.action),
        _stylize_player_ids(
            summarize_action(
                step.action,
                card_names_by_instance_id=card_names_by_instance_id,
                card_values_by_instance_id=card_values_by_instance_id,
            )
        ),
    )
    console.print(action_row)
    for event in step.events:
        event_text = Text("  - ", style="dim")
        _ = event_text.append(f"{event_type_name(event)}: ", style="dim")
        _ = event_text.append_text(
            _stylize_player_ids(
                summarize_event(
                    event,
                    card_names_by_instance_id=card_names_by_instance_id,
                    card_values_by_instance_id=card_values_by_instance_id,
                )
            )
        )
        console.print(event_text)
    preview_state = _round_resolution_preview_state(step)
    if preview_state is not None:
        console.print(_build_round_resolution_preview_panel(step, preview_state, run))


def _build_pending_choice_panel(run: CliRun) -> Panel:
    assert run.pending_choice_state is not None
    choice = run.pending_choice_state.pending_choice
    assert choice is not None
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold magenta")
    table.add_column()
    for label, value in pending_choice_items(
        choice,
        card_names_by_instance_id=run.card_names_by_instance_id,
        card_values_by_instance_id=run.card_values_by_instance_id,
    ):
        table.add_row(label, value)
    return Panel(table, border_style="magenta", title="Pending Choice Snapshot")


def _build_summary_table(
    state: GameState,
    *,
    title: str = "Final Summary",
    winner_label: str = "Match Winner",
    winner_value: Text | None = None,
) -> Table:
    player_one, player_two = state.players
    resolved_winner = _match_winner_text(state) if winner_value is None else winner_value
    current_player = (
        Text("-") if state.current_player is None else _player_id_text(state.current_player)
    )
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("Field", style="bold green")
    table.add_column("Value")
    rows = (
        ("Phase", Text(state.phase.value)),
        ("Status", Text(state.status.value)),
        ("Round", Text(str(state.round_number))),
        ("Current Player", current_player),
        (winner_label, resolved_winner),
        ("Pending Choice", Text("yes" if state.pending_choice is not None else "no")),
        ("Player One Round Wins", Text(str(player_one.round_wins))),
        ("Player Two Round Wins", Text(str(player_two.round_wins))),
        ("Player One Hand", Text(str(len(player_one.hand)))),
        ("Player Two Hand", Text(str(len(player_two.hand)))),
        ("Player One Deck", Text(str(len(player_one.deck)))),
        ("Player Two Deck", Text(str(len(player_two.deck)))),
        ("Player One Discard", Text(str(len(player_one.discard)))),
        ("Player Two Discard", Text(str(len(player_two.discard)))),
        ("Player One Gems", Text(str(player_one.gems_remaining))),
        ("Player Two Gems", Text(str(player_two.gems_remaining))),
    )
    for field, value in rows:
        table.add_row(field, value)
    return table


def _build_board_table(
    state: GameState,
    run: CliRun,
    strengths_by_instance_id: Mapping[CardInstanceId, int],
    *,
    title: str = "Final Board",
) -> Table:
    player_one, player_two = state.players
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("Player", style="bold green")
    table.add_column(board_row_label("Close", active=bool(state.weather.close)))
    table.add_column(board_row_label("Ranged", active=bool(state.weather.ranged)))
    table.add_column(board_row_label("Siege", active=bool(state.weather.siege)))
    table.add_row(
        _player_id_text(player_one.player_id),
        _render_board_card_list(player_one.rows.close, run, strengths_by_instance_id),
        _render_board_card_list(player_one.rows.ranged, run, strengths_by_instance_id),
        _render_board_card_list(player_one.rows.siege, run, strengths_by_instance_id),
    )
    table.add_row(
        _player_id_text(player_two.player_id),
        _render_board_card_list(player_two.rows.close, run, strengths_by_instance_id),
        _render_board_card_list(player_two.rows.ranged, run, strengths_by_instance_id),
        _render_board_card_list(player_two.rows.siege, run, strengths_by_instance_id),
    )
    return table


def _build_hand_table(
    state: GameState,
    run: CliRun,
    *,
    title: str = "Final Hands",
) -> Table:
    return _build_player_card_table(
        state,
        run,
        title=title,
        cards_for_player=lambda player: player.hand,
    )


def _build_deck_table(
    state: GameState,
    run: CliRun,
    *,
    title: str = "Remaining Decks",
) -> Table:
    return _build_player_card_table(
        state,
        run,
        title=title,
        cards_for_player=lambda player: player.deck,
    )


def _build_player_card_table(
    state: GameState,
    run: CliRun,
    *,
    title: str,
    cards_for_player: Callable[[PlayerState], tuple[CardInstanceId, ...]],
) -> Table:
    player_one, player_two = state.players
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("Player", style="bold green")
    table.add_column("Cards")
    table.add_row(
        _player_id_text(player_one.player_id),
        _render_card_list(cards_for_player(player_one), run),
    )
    table.add_row(
        _player_id_text(player_two.player_id),
        _render_card_list(cards_for_player(player_two), run),
    )
    return table


def _render_card_list(card_ids: tuple[CardInstanceId, ...], run: CliRun) -> Text:
    return Text(
        card_list_text(
            card_ids,
            card_names_by_instance_id=run.card_names_by_instance_id,
            card_values_by_instance_id=run.card_values_by_instance_id,
        )
    )


def _render_board_card_list(
    card_ids: tuple[CardInstanceId, ...],
    run: CliRun,
    strengths_by_instance_id: Mapping[CardInstanceId, int],
) -> Text:
    if not card_ids:
        return Text("-")
    text = Text()
    for index, card_id in enumerate(card_ids):
        if index > 0:
            _ = text.append(", ")
        card_name = run.card_names_by_instance_id.get(card_id, str(card_id))
        card_strength = strengths_by_instance_id.get(card_id, 0)
        _ = text.append(f"[{card_name}] ")
        _ = text.append(str(card_strength), style=VALUE_STYLE)
    return text


def _match_winner_text(state: GameState) -> Text:
    if state.status != GameStatus.MATCH_ENDED:
        return Text("pending")
    if state.match_winner is None:
        return Text("draw")
    return _player_id_text(state.match_winner)


def _player_id_text(player_id: PlayerId) -> Text:
    style = P1_STYLE if str(player_id) == "p1" else P2_STYLE if str(player_id) == "p2" else ""
    return Text(str(player_id), style=style)


def _stylize_player_ids(value: str) -> Text:
    text = Text(value, style="bold")
    for match in re.finditer(r"\bp[12]\b", value):
        style = P1_STYLE if match.group(0) == "p1" else P2_STYLE
        text.stylize(style, match.start(), match.end())
    return text


def _round_resolution_preview_state(step: CliStep) -> GameState | None:
    if not any(isinstance(event, RoundEndedEvent) for event in step.events):
        return None
    return step.round_summary_state


def _build_round_resolution_preview_panel(
    step: CliStep,
    state: GameState,
    run: CliRun,
) -> Panel:
    round_label = f"Round {state.round_number}"
    round_end = round_ended_event(step.events)
    if round_end is None:
        winner_value = Text("pending")
    elif round_end.winner is None:
        winner_value = Text(winner_text(round_end.winner))
    else:
        winner_value = _player_id_text(round_end.winner)
    return Panel(
        Group(
            _build_summary_table(
                state,
                title=f"{round_label} Summary",
                winner_label="Round Winner",
                winner_value=winner_value,
            ),
            _build_board_table(
                state,
                run,
                step.round_summary_strengths,
                title=f"{round_label} Board",
            ),
            _build_hand_table(state, run, title=f"{round_label} Hands"),
            _build_deck_table(state, run, title=f"{round_label} Deck"),
        ),
        title=round_label,
        border_style="yellow3",
    )
