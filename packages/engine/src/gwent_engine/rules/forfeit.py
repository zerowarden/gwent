from dataclasses import replace

from gwent_engine.core.actions import LeaveAction
from gwent_engine.core.events import GameEvent, PlayerLeftEvent
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.rules.round_cleanup import end_match


def apply_leave(
    state: GameState,
    action: LeaveAction,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    first_player, second_player = state.players
    surviving_player_id = next(
        player.player_id for player in state.players if player.player_id != action.player_id
    )
    updated_players = (
        _apply_forfeit_to_player(
            first_player,
            leaving=first_player.player_id == action.player_id,
        ),
        _apply_forfeit_to_player(
            second_player,
            leaving=second_player.player_id == action.player_id,
        ),
    )
    left_event = PlayerLeftEvent(
        event_id=state.event_counter + 1,
        player_id=action.player_id,
    )
    left_state = replace(
        state,
        players=updated_players,
        event_counter=state.event_counter + 1,
    )
    ended_state, match_events = end_match(left_state, winner=surviving_player_id)
    return ended_state, (left_event, *match_events)


def _apply_forfeit_to_player(player: PlayerState, *, leaving: bool) -> PlayerState:
    if not leaving:
        return player
    return replace(player, gems_remaining=0)
