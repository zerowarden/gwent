from gwent_engine.core import Row
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    NILFGAARD_DECK_ID,
    build_in_round_game_state,
    first_hand_unit_for_row,
)


def test_no_normal_redraw_occurs_between_rounds() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )
    player_one_initial_hand = len(state.player(PlayerId("p1")).hand)
    player_two_initial_hand = len(state.player(PlayerId("p2")).hand)
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=first_hand_unit_for_row(
                state,
                card_registry,
                PlayerId("p1"),
                Row.CLOSE,
            ),
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(state, PassAction(player_id=PlayerId("p2")))

    next_state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
    )

    assert len(next_state.player(PlayerId("p1")).hand) == player_one_initial_hand - 1
    assert len(next_state.player(PlayerId("p2")).hand) == player_two_initial_hand
    assert len(next_state.player(PlayerId("p1")).deck) == len(state.player(PlayerId("p1")).deck)
    assert len(next_state.player(PlayerId("p2")).deck) == len(state.player(PlayerId("p2")).deck)
