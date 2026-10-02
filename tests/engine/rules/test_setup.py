from gwent_engine.core import GameStatus, Phase
from gwent_engine.core.actions import StartGameAction
from gwent_engine.core.events import CardsDrawnEvent, GameStartedEvent, StartingPlayerChosenEvent
from gwent_engine.core.reducer import apply_action

from tests.engine.support import (
    SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
    build_sample_game_state,
    build_started_game_state,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID, IdentityRandom


def test_start_game_draws_opening_hands_and_sets_mulligan_phase() -> None:
    initial_state = build_sample_game_state()
    initial_player_one_deck_size = len(initial_state.player(PLAYER_ONE_ID).deck)
    initial_player_two_deck_size = len(initial_state.player(PLAYER_TWO_ID).deck)

    next_state, events = apply_action(
        initial_state,
        StartGameAction(starting_player=PLAYER_TWO_ID),
        rng=IdentityRandom(),
    )

    player_one = next_state.player(PLAYER_ONE_ID)
    player_two = next_state.player(PLAYER_TWO_ID)

    assert next_state.phase == Phase.MULLIGAN
    assert next_state.status == GameStatus.IN_PROGRESS
    assert next_state.starting_player == PLAYER_TWO_ID
    assert next_state.round_starter == PLAYER_TWO_ID
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
    assert events[0].player_id == PLAYER_TWO_ID
    assert events[2].card_instance_ids == player_one.hand
    assert events[3].card_instance_ids == player_two.hand


def test_start_game_uses_explicit_starting_player_input() -> None:
    initial_state = build_sample_game_state()

    next_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=IdentityRandom(),
    )

    assert next_state.current_player is None
    assert next_state.starting_player == PLAYER_ONE_ID


def test_skellige_transform_and_avenger_fixture_deck_supports_opening_draw() -> None:
    started_state, _ = build_started_game_state(
        player_one_deck_id=SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
        player_two_deck_id=SKELLIGE_TRANSFORM_AND_AVENGER_DECK_ID,
    )

    assert len(started_state.player(started_state.players[0].player_id).hand) == 10
    assert len(started_state.player(started_state.players[1].player_id).hand) == 10
