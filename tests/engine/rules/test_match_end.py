from gwent_engine.core import Phase, Row
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import GameEvent, MatchEndedEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    NILFGAARD_DECK_ID,
    build_in_round_game_state,
    first_hand_unit_for_row,
)


def test_match_ends_when_a_player_loses_the_second_gem() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )

    events: tuple[GameEvent, ...] = ()
    for _ in range(2):
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
        state, _ = apply_action(
            state,
            PassAction(player_id=PlayerId("p2")),
        )
        state, events = apply_action(
            state,
            PassAction(player_id=PlayerId("p1")),
            card_registry=card_registry,
        )

    assert state.phase == Phase.MATCH_ENDED
    assert state.match_winner == PlayerId("p1")
    assert state.current_player is None
    assert state.player(PlayerId("p2")).gems_remaining == 0
    match_end = next(event for event in events if isinstance(event, MatchEndedEvent))
    assert match_end.winner == PlayerId("p1")
