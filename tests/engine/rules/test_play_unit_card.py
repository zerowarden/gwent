from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import CardPlayedEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import build_in_round_game_state


def test_play_card_moves_unit_from_hand_to_battlefield_row() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))
    player_one_before = state.player(PlayerId("p1"))
    card_to_play = player_one_before.hand[0]

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=card_to_play,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    player_one_after = next_state.player(PlayerId("p1"))
    played_card = next_state.card(card_to_play)

    assert card_to_play not in player_one_after.hand
    assert player_one_after.rows.close == (card_to_play,)
    assert played_card.zone == Zone.BATTLEFIELD
    assert played_card.row == Row.CLOSE
    assert next_state.current_player == PlayerId("p2")
    assert isinstance(events[0], CardPlayedEvent)
    assert events[0].card_instance_id == card_to_play
