import pytest
from gwent_engine.core import FactionId, Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import CardTransformedEvent, SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
    PLAYER_ONE_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
)


def test_special_mardroeme_transforms_existing_berserker_on_row() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    berserker_id = CardInstanceId("p1_skellige_berserker_frontliner")
    mardroeme_id = CardInstanceId("p1_skellige_mardroeme_special")
    state = (
        scenario("special_mardroeme_transforms_existing_berserker")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            hand=(card(mardroeme_id, "skellige_mardroeme"),),
            board=rows(close=[card(berserker_id, "skellige_berserker")]),
        )
        .player(
            "p2",
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=mardroeme_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.card(berserker_id).definition_id == "skellige_transformed_vildkaarl"
    assert next_state.card(berserker_id).instance_id == berserker_id
    assert any(
        isinstance(event, SpecialCardResolvedEvent) and event.ability_kind.value == "mardroeme"
        for event in events
    )
    assert any(
        isinstance(event, CardTransformedEvent)
        and event.card_instance_id == berserker_id
        and event.new_definition_id == "skellige_transformed_vildkaarl"
        for event in events
    )


def test_berserker_played_into_special_mardroeme_row_transforms_immediately() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    active_mardroeme_id = CardInstanceId("p1_skellige_mardroeme_active_on_close_row")
    young_berserker_id = CardInstanceId("p1_skellige_young_berserker_reinforcement")
    state = (
        scenario("berserker_played_into_active_mardroeme_row")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            hand=(card(young_berserker_id, "skellige_young_berserker"),),
            board=rows(close=[card(active_mardroeme_id, "skellige_mardroeme")]),
        )
        .player(
            "p2",
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=young_berserker_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert (
        next_state.card(young_berserker_id).definition_id == "skellige_transformed_young_vildkaarl"
    )
    assert next_state.card(young_berserker_id).instance_id == young_berserker_id
    assert any(
        isinstance(event, CardTransformedEvent)
        and event.card_instance_id == young_berserker_id
        and event.new_definition_id == "skellige_transformed_young_vildkaarl"
        for event in events
    )


def test_special_mardroeme_cannot_be_played_on_row_with_special_horn() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    horn_id = CardInstanceId("p1_special_commanders_horn_on_close_row")
    mardroeme_id = CardInstanceId("p1_skellige_mardroeme_special")
    state = (
        scenario("special_mardroeme_illegal_on_horn_row")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            hand=(card(mardroeme_id, "skellige_mardroeme"),),
            board=rows(close=[card(horn_id, "neutral_commanders_horn")]),
        )
        .player(
            "p2",
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="special Horn"):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=mardroeme_id,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
