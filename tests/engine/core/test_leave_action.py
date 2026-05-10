import pytest
from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import LeaveAction, StartGameAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import MatchEndedEvent, PlayerLeftEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    IdentityShuffle,
    build_in_round_game_state,
    build_sample_game_state,
)


def test_player_can_leave_before_start_and_lose_the_match() -> None:
    initial_state = build_sample_game_state()

    ended_state, events = apply_action(
        initial_state,
        LeaveAction(player_id=PLAYER_ONE_ID),
    )

    assert ended_state.phase == Phase.MATCH_ENDED
    assert ended_state.status == GameStatus.MATCH_ENDED
    assert ended_state.match_winner == PLAYER_TWO_ID
    assert ended_state.current_player is None
    assert ended_state.player(PLAYER_ONE_ID).gems_remaining == 0
    assert ended_state.player(PLAYER_TWO_ID).gems_remaining == 2
    assert events == (
        PlayerLeftEvent(event_id=1, player_id=PLAYER_ONE_ID),
        MatchEndedEvent(event_id=2, winner=PLAYER_TWO_ID),
    )


def test_player_can_leave_during_mulligan_before_both_players_finish() -> None:
    initial_state = build_sample_game_state()
    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=IdentityShuffle(),
    )

    ended_state, events = apply_action(
        started_state,
        LeaveAction(player_id=PLAYER_TWO_ID),
    )

    assert started_state.phase == Phase.MULLIGAN
    assert ended_state.phase == Phase.MATCH_ENDED
    assert ended_state.match_winner == PLAYER_ONE_ID
    assert isinstance(events[0], PlayerLeftEvent)
    assert isinstance(events[1], MatchEndedEvent)


def test_player_can_leave_during_round_even_when_not_the_current_player() -> None:
    in_round_state, _ = build_in_round_game_state(starting_player=PLAYER_ONE_ID)

    ended_state, events = apply_action(
        in_round_state,
        LeaveAction(player_id=PLAYER_TWO_ID),
    )

    assert in_round_state.current_player == PLAYER_ONE_ID
    assert ended_state.phase == Phase.MATCH_ENDED
    assert ended_state.match_winner == PLAYER_ONE_ID
    assert ended_state.player(PLAYER_TWO_ID).gems_remaining == 0
    assert events[0].event_id == in_round_state.event_counter + 1
    assert events[1].event_id == in_round_state.event_counter + 2


def test_leave_action_is_illegal_after_the_match_has_already_ended() -> None:
    initial_state = build_sample_game_state()
    ended_state, _ = apply_action(
        initial_state,
        LeaveAction(player_id=PLAYER_ONE_ID),
    )

    ## TODO: Fixed unused assignment
    with pytest.raises(IllegalActionError, match="before the match has ended"):
        _ = apply_action(
            ended_state,
            LeaveAction(player_id=PlayerId("p2")),
        )
