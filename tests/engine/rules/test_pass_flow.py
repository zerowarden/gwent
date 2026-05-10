import pytest
from gwent_engine.core import Phase, Row
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import NextRoundStartedEvent, PlayerPassedEvent, RoundEndedEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import SCOIATAEL_DECK_ID, build_in_round_game_state


def test_pass_turn_advances_to_opponent_and_opponent_may_keep_playing() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))

    passed_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )

    assert passed_state.player(PlayerId("p1")).has_passed is True
    assert passed_state.current_player == PlayerId("p2")
    assert passed_state.phase == Phase.IN_ROUND
    assert isinstance(events[0], PlayerPassedEvent)

    player_two_card = passed_state.player(PlayerId("p2")).hand[0]
    next_state, _ = apply_action(
        passed_state,
        PlayCardAction(
            player_id=PlayerId("p2"),
            card_instance_id=player_two_card,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.current_player == PlayerId("p2")


def test_passed_player_cannot_act_again() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))
    passed_state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )
    player_one_card = state.player(PlayerId("p1")).hand[0]

    with pytest.raises(IllegalActionError, match="Passed players cannot act again"):
        _ = apply_action(
            passed_state,
            PlayCardAction(
                player_id=PlayerId("p1"),
                card_instance_id=player_one_card,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )


def test_two_passes_resolve_round_and_start_next_round() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=SCOIATAEL_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    first_pass_state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )

    final_state, events = apply_action(
        first_pass_state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
    )

    assert final_state.phase == Phase.IN_ROUND
    assert final_state.current_player == PlayerId("p1")
    assert isinstance(events[1], RoundEndedEvent)
    assert isinstance(events[3], NextRoundStartedEvent)
