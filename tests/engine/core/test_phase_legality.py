import pytest
from gwent_engine.core import Row
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    build_in_round_game_state,
    build_sample_game_state,
    build_started_game_state,
)


def test_wrong_player_cannot_act_during_round() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))
    player_one_card = state.player(PlayerId("p1")).hand[0]
    card_name = card_registry.get(state.card(player_one_card).definition_id).name
    with pytest.raises(
        IllegalActionError,
        match=f"Only the current player may act.*Attempted play: {card_name!r}",
    ):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PlayerId("p2"),
                card_instance_id=player_one_card,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )


def test_in_round_actions_are_rejected_outside_in_round_phase() -> None:
    not_started_state = build_sample_game_state()

    with pytest.raises(IllegalActionError, match="IN_ROUND phase"):
        _ = apply_action(
            not_started_state,
            PassAction(player_id=PlayerId("p1")),
        )

    started_state, card_registry = build_started_game_state(starting_player=PlayerId("p1"))
    card_to_play = started_state.player(PlayerId("p1")).hand[0]
    with pytest.raises(IllegalActionError, match="IN_ROUND phase"):
        _ = apply_action(
            started_state,
            PlayCardAction(
                player_id=PlayerId("p1"),
                card_instance_id=card_to_play,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )
