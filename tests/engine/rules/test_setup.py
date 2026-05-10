from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import StartGameAction
from gwent_engine.core.events import CardsDrawnEvent, GameStartedEvent, StartingPlayerChosenEvent
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
    IdentityShuffle,
    build_sample_game_state,
    build_started_game_state,
)


def test_start_game_draws_opening_hands_and_sets_mulligan_phase() -> None:
    initial_state = build_sample_game_state()
    initial_player_one_deck_size = len(initial_state.player(PlayerId("p1")).deck)
    initial_player_two_deck_size = len(initial_state.player(PlayerId("p2")).deck)

    next_state, events = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p2")),
        rng=IdentityShuffle(),
    )

    player_one = next_state.player(PlayerId("p1"))
    player_two = next_state.player(PlayerId("p2"))

    assert next_state.phase == Phase.MULLIGAN
    assert next_state.status == GameStatus.IN_PROGRESS
    assert next_state.starting_player == PlayerId("p2")
    assert next_state.round_starter == PlayerId("p2")
    assert next_state.current_player is None
    assert len(player_one.hand) == 10
    assert len(player_two.hand) == 10
    assert len(player_one.deck) == initial_player_one_deck_size - 10
    assert len(player_two.deck) == initial_player_two_deck_size - 10
    assert next_state.event_counter == 4

    assert isinstance(events[0], StartingPlayerChosenEvent)
    assert isinstance(events[1], GameStartedEvent)
    assert isinstance(events[2], CardsDrawnEvent)
    assert isinstance(events[3], CardsDrawnEvent)
    assert events[0].player_id == PlayerId("p2")
    assert events[2].card_instance_ids == player_one.hand
    assert events[3].card_instance_ids == player_two.hand


def test_start_game_uses_explicit_starting_player_input() -> None:
    initial_state = build_sample_game_state()

    next_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p1")),
        rng=IdentityShuffle(),
    )

    assert next_state.current_player is None
    assert next_state.starting_player == PlayerId("p1")


def test_skellige_transform_and_avenger_fixture_deck_supports_opening_draw() -> None:
    started_state, _ = build_started_game_state(
        player_one_deck_id=SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
        player_two_deck_id=SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
    )

    assert len(started_state.player(started_state.players[0].player_id).hand) == 10
    assert len(started_state.player(started_state.players[1].player_id).hand) == 10
