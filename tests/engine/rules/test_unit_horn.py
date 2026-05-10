from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import UnitHornActivatedEvent, UnitHornSuppressedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.row_effects import row_has_commanders_horn
from gwent_engine.rules.scoring import calculate_effective_strength

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_unit_horn_activates_and_doubles_non_hero_units_on_its_row() -> None:
    card_registry = CARD_REGISTRY
    horn_unit_card_id = CardInstanceId("p1_hornmaster_troubadour")
    close_defender_card_id = CardInstanceId("p1_close_defender")
    hero_card_id = CardInstanceId("p1_geralt_hero")
    state = (
        scenario("unit_horn_activates")
        .player(
            PLAYER_ONE_ID,
            hand=(card(horn_unit_card_id, "neutral_dandelion"),),
            board=rows(
                close=[
                    card(close_defender_card_id, "scoiatael_mahakaman_defender"),
                    card(hero_card_id, "neutral_geralt"),
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_skirmisher", "scoiatael_vrihedd_brigade_recruit"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=horn_unit_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert any(isinstance(event, UnitHornActivatedEvent) for event in events)
    assert row_has_commanders_horn(next_state, card_registry, PLAYER_ONE_ID, Row.CLOSE)
    assert calculate_effective_strength(next_state, card_registry, horn_unit_card_id) == 4
    assert calculate_effective_strength(next_state, card_registry, close_defender_card_id) == 10
    assert calculate_effective_strength(next_state, card_registry, hero_card_id) == 15


def test_unit_horn_is_suppressed_when_special_horn_already_affects_the_row() -> None:
    card_registry = CARD_REGISTRY
    horn_unit_card_id = CardInstanceId("p1_hornmaster_troubadour")
    close_defender_card_id = CardInstanceId("p1_close_defender")
    special_horn_card_id = CardInstanceId("p1_close_horn")
    state = (
        scenario("unit_horn_suppressed_by_special_horn")
        .player(
            PLAYER_ONE_ID,
            hand=(card(horn_unit_card_id, "neutral_dandelion"),),
            board=rows(
                close=[
                    card(close_defender_card_id, "scoiatael_mahakaman_defender"),
                    card(special_horn_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_skirmisher", "scoiatael_vrihedd_brigade_recruit"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=horn_unit_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    suppressed_event = next(event for event in events if isinstance(event, UnitHornSuppressedEvent))
    assert suppressed_event.active_source_card_instance_id == special_horn_card_id
    assert calculate_effective_strength(next_state, card_registry, horn_unit_card_id) == 4
    assert calculate_effective_strength(next_state, card_registry, close_defender_card_id) == 10


def test_unit_horn_effect_disappears_when_the_horn_unit_leaves_the_row() -> None:
    card_registry = CARD_REGISTRY
    close_defender_card_id = CardInstanceId("p1_close_defender")
    active_state = (
        scenario("unit_horn_active_state")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card("p1_hornmaster_troubadour", "neutral_dandelion"),
                    card(close_defender_card_id, "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )
    inactive_state = (
        scenario("unit_horn_inactive_state")
        .player(
            PLAYER_ONE_ID,
            hand=(card("p1_hornmaster_troubadour", "neutral_dandelion"),),
            board=rows(close=[card(close_defender_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    assert row_has_commanders_horn(active_state, card_registry, PLAYER_ONE_ID, Row.CLOSE)
    assert not row_has_commanders_horn(inactive_state, card_registry, PLAYER_ONE_ID, Row.CLOSE)
    assert calculate_effective_strength(active_state, card_registry, close_defender_card_id) == 10
    assert calculate_effective_strength(inactive_state, card_registry, close_defender_card_id) == 5
