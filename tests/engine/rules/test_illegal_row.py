import pytest
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import build_in_round_game_state


def test_illegal_row_placement_is_rejected() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))
    player_one = state.player(PlayerId("p1"))
    close_only_card = player_one.hand[0]

    with pytest.raises(IllegalActionError, match="cannot be played to row"):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PlayerId("p1"),
                card_instance_id=close_only_card,
                target_row=Row.SIEGE,
            ),
            card_registry=card_registry,
        )
