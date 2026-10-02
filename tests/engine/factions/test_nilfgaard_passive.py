from gwent_engine.core.actions import PassAction
from gwent_engine.core.events import FactionPassiveTriggeredEvent, RoundEndedEvent
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    MONSTERS_DECK_ID,
    NILFGAARD_DECK_ID,
    build_in_round_game_state,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_nilfgaard_vs_non_nilfgaard_tie_becomes_a_win() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PLAYER_ONE_ID,
        player_one_deck_id=MONSTERS_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )
    state, _ = apply_action(state, PassAction(player_id=PLAYER_ONE_ID))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).gems_remaining == 1
    assert next_state.player(PLAYER_TWO_ID).gems_remaining == 2
    assert next_state.current_player == PLAYER_TWO_ID
    assert isinstance(events[1], FactionPassiveTriggeredEvent)
    assert events[1].player_id == PLAYER_TWO_ID
    assert isinstance(events[2], RoundEndedEvent)
    assert events[2].winner == PLAYER_TWO_ID


def test_nilfgaard_vs_nilfgaard_tie_remains_a_draw() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PLAYER_ONE_ID,
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )
    state, _ = apply_action(state, PassAction(player_id=PLAYER_ONE_ID))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).gems_remaining == 1
    assert next_state.player(PLAYER_TWO_ID).gems_remaining == 1
    assert all(not isinstance(event, FactionPassiveTriggeredEvent) for event in events)
    assert isinstance(events[1], RoundEndedEvent)
    assert events[1].winner is None
