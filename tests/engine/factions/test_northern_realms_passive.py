from dataclasses import replace

from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import CardsDrawnEvent, FactionPassiveTriggeredEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import GameState
from gwent_engine.rules.players import replace_player

from ..scenario_builder import card, rows, scenario
from ..support import (
    NORTHERN_REALMS_DECK_ID,
    NORTHERN_REALMS_SIEGE_HORN_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_DECK_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    build_in_round_game_state,
)


def test_northern_realms_draws_one_card_on_round_win() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NORTHERN_REALMS_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    initial_deck_size = len(state.player(PlayerId("p1")).deck)
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=state.player(PlayerId("p1")).hand[0],
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(state, PassAction(player_id=PlayerId("p2")))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
    )

    assert len(next_state.player(PlayerId("p1")).hand) == 10
    assert len(next_state.player(PlayerId("p1")).deck) == initial_deck_size - 1
    assert isinstance(events[3], FactionPassiveTriggeredEvent)
    assert events[3].player_id == PlayerId("p1")
    assert isinstance(events[4], CardsDrawnEvent)
    assert events[4].card_instance_ids == (state.player(PlayerId("p1")).deck[0],)


def test_northern_realms_does_nothing_if_deck_is_empty() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NORTHERN_REALMS_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    state = _deplete_player_deck(state, PlayerId("p1"))
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=state.player(PlayerId("p1")).hand[0],
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(state, PassAction(player_id=PlayerId("p2")))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
    )

    assert len(next_state.player(PlayerId("p1")).hand) == 9
    assert len(next_state.player(PlayerId("p1")).deck) == 0
    assert all(
        not (isinstance(event, FactionPassiveTriggeredEvent) and event.player_id == PlayerId("p1"))
        for event in events
    )
    assert all(not isinstance(event, CardsDrawnEvent) for event in events)


def test_northern_realms_does_not_draw_above_max_hand_size() -> None:
    card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NORTHERN_REALMS_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )[1]
    state = (
        scenario("northern_realms_full_hand_no_draw")
        .current_player(PLAYER_TWO_ID)
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NORTHERN_REALMS,
            leader_id=NORTHERN_REALMS_SIEGE_HORN_LEADER_ID,
            hand=tuple(
                card(
                    f"p1_full_hand_reserve_{index}",
                    "scoiatael_mahakaman_defender",
                )
                for index in range(1, 18)
            ),
            deck=(
                card(
                    "p1_bonus_draw_blocked_by_full_hand",
                    "northern_realms_blue_stripes_commando",
                ),
            ),
            board=rows(close=[card("p1_siege_winner_on_close_row", "northern_realms_trebuchet")]),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
        )
        .build()
    )
    state, _ = apply_action(state, PassAction(player_id=PlayerId("p2")))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
    )

    assert len(next_state.player(PlayerId("p1")).hand) == 17
    assert (
        CardInstanceId("p1_bonus_draw_blocked_by_full_hand")
        in next_state.player(PlayerId("p1")).deck
    )
    assert all(
        not (isinstance(event, FactionPassiveTriggeredEvent) and event.player_id == PlayerId("p1"))
        for event in events
    )
    assert all(not isinstance(event, CardsDrawnEvent) for event in events)


def _deplete_player_deck(state: GameState, player_id: PlayerId) -> GameState:
    player = state.player(player_id)
    deck_card_ids = set(player.deck)
    updated_player = replace(
        player,
        deck=(),
        discard=player.discard + player.deck,
    )
    updated_players = replace_player(state.players, updated_player)
    updated_cards = tuple(
        replace(card, zone=Zone.DISCARD) if card.instance_id in deck_card_ids else card
        for card in state.card_instances
    )
    return replace(state, players=updated_players, card_instances=updated_cards)
