import pytest
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import FactionPassiveTriggeredEvent, NextRoundStartedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import GameState
from gwent_engine.factions.passives import resolve_before_round_cleanup

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    MONSTERS_CLOSE_HORN_LEADER_ID,
    MONSTERS_DECK_ID,
    NORTHERN_REALMS_DECK_ID,
    NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
    SCOIATAEL_DECK_ID,
    IndexedRandom,
    build_in_round_game_state,
)


def test_monsters_retains_exactly_one_deterministic_unit() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=MONSTERS_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    monsters_card = _hand_card_for_row(state, card_registry, PlayerId("p1"), Row.CLOSE)
    scoiatael_card = _hand_card_for_row(state, card_registry, PlayerId("p2"), Row.CLOSE)
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=monsters_card,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p2"),
            card_instance_id=scoiatael_card,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=1),
    )

    assert next_state.player(PlayerId("p1")).rows.close == (monsters_card,)
    assert next_state.player(PlayerId("p2")).rows.all_cards() == ()
    assert next_state.card(monsters_card).zone == Zone.BATTLEFIELD
    assert next_state.card(scoiatael_card).zone == Zone.DISCARD
    assert isinstance(events[2], FactionPassiveTriggeredEvent)
    assert events[2].card_instance_id == monsters_card


def test_monsters_does_nothing_when_no_eligible_units_exist() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=MONSTERS_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    assert next_state.player(PlayerId("p1")).rows.all_cards() == ()
    assert next_state.player(PlayerId("p2")).rows.all_cards() == ()
    assert all(
        not (isinstance(event, FactionPassiveTriggeredEvent) and event.player_id == PlayerId("p1"))
        for event in events
    )


def test_passive_event_order_is_deterministic_when_multiple_passives_trigger() -> None:
    card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=MONSTERS_DECK_ID,
        player_two_deck_id=NORTHERN_REALMS_DECK_ID,
    )[1]
    state = (
        scenario("monsters_and_northern_realms_passives_order")
        .player(
            "p1",
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_CLOSE_HORN_LEADER_ID,
            board=rows(close=[card("p1_monsters_frontliner", "monsters_griffin")]),
        )
        .player(
            "p2",
            faction=FactionId.NORTHERN_REALMS,
            leader_id=NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
            deck=[card("p2_northern_realms_deck_top", "northern_realms_ballista")],
            board=rows(siege=[card("p2_northern_realms_sieger", "northern_realms_catapult")]),
        )
        .build()
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    assert [type(event).__name__ for event in events] == [
        "PlayerPassedEvent",
        "RoundEndedEvent",
        "FactionPassiveTriggeredEvent",
        "CardsMovedToDiscardEvent",
        "NextRoundStartedEvent",
    ]
    assert isinstance(events[4], NextRoundStartedEvent)
    assert next_state.current_player == PlayerId("p1")


def _hand_card_for_row(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
    *,
    strongest: bool = True,
) -> CardInstanceId:
    candidates: list[tuple[int, CardInstanceId]] = []
    for card_instance_id in state.player(player_id).hand:
        definition = card_registry.get(state.card(card_instance_id).definition_id)
        if row in definition.allowed_rows and not definition.is_hero:
            candidates.append((definition.base_strength, card_instance_id))
    if candidates:
        candidates.sort(key=lambda item: (item[0], str(item[1])))
        return candidates[-1][1] if strongest else candidates[0][1]
    raise AssertionError(f"No card in {player_id!r} hand can be played to {row!r}.")


@pytest.mark.parametrize("choice_index", [0, 1, 2, 3])
def test_monsters_retention_uses_controlled_non_hero_units_in_mirror_match(
    choice_index: int,
) -> None:
    state = (
        scenario("monsters_controlled_units")
        .player(
            "p1",
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_CLOSE_HORN_LEADER_ID,
            board=rows(
                close=[
                    card("p1_hero", "monsters_imlerith"),
                    card("incoming_spy", "nilfgaard_vattier_de_rideaux", owner="p2"),
                    card("p1_unit", "monsters_griffin"),
                    card("p1_horn", "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            "p2",
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_CLOSE_HORN_LEADER_ID,
            board=rows(
                close=[
                    card("p2_hero", "monsters_imlerith"),
                    card("outgoing_spy", "nilfgaard_vattier_de_rideaux", owner="p1"),
                    card("p2_unit", "monsters_griffin"),
                ]
            ),
        )
        .build()
    )
    retained, events = resolve_before_round_cleanup(
        state, card_registry=CARD_REGISTRY, rng=IndexedRandom(choice_index=choice_index)
    )
    assert len(retained) == len(events) == 2
    for player, eligible in (
        (PlayerId("p1"), {"incoming_spy", "p1_unit"}),
        (PlayerId("p2"), {"outgoing_spy", "p2_unit"}),
    ):
        event = next(
            event
            for event in events
            if isinstance(event, FactionPassiveTriggeredEvent) and event.player_id == player
        )
        assert isinstance(event, FactionPassiveTriggeredEvent)
        assert event.card_instance_id in eligible
        assert event.card_instance_id in retained
