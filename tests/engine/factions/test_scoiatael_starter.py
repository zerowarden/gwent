from gwent_engine.core.actions import StartGameAction
from gwent_engine.core.events import FactionPassiveTriggeredEvent, StartingPlayerChosenEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    MONSTERS_DECK_ID,
    SCOIATAEL_DECK_ID,
    IdentityShuffle,
    build_sample_game_state,
)


def test_scoiatael_starter_choice_works() -> None:
    initial_state = build_sample_game_state(
        player_one_deck_id=SCOIATAEL_DECK_ID,
        player_two_deck_id=MONSTERS_DECK_ID,
    )

    next_state, events = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p2")),
        rng=IdentityShuffle(),
    )

    assert next_state.starting_player == PlayerId("p2")
    assert next_state.current_player is None
    assert isinstance(events[0], FactionPassiveTriggeredEvent)
    assert events[0].player_id == PlayerId("p1")
    assert events[0].chosen_player_id == PlayerId("p2")
    assert isinstance(events[1], StartingPlayerChosenEvent)
    assert events[1].player_id == PlayerId("p2")
