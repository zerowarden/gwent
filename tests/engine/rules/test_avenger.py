from dataclasses import replace

import pytest
from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction, ResolveChoiceAction
from gwent_engine.core.events import AvengerSummonedEvent, AvengerSummonQueuedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
)


@pytest.mark.parametrize(
    ("source_definition_id", "source_row", "summoned_definition_id"),
    (
        ("neutral_avenger_cow", Row.RANGED, "neutral_bovine_defense_force"),
        ("skellige_kambi", Row.CLOSE, "skellige_hemdall"),
    ),
)
def test_avenger_card_removed_during_live_round_summons_immediately(
    source_definition_id: str,
    source_row: Row,
    summoned_definition_id: str,
) -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    source_card_id = CardInstanceId(f"p1_{source_definition_id}_source")
    decoy_card_id = CardInstanceId(f"p1_decoy_against_{source_definition_id}")
    board = (
        rows(close=[card(str(source_card_id), source_definition_id)])
        if source_row == Row.CLOSE
        else rows(ranged=[card(str(source_card_id), source_definition_id)])
    )
    state = (
        scenario(f"avenger_live_round_{source_definition_id}")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            hand=(card(str(decoy_card_id), "neutral_decoy"),),
            board=board,
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )

    pending_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    assert events == ()
    assert pending_state.pending_choice is not None

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(source_card_id,),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    source_card = next_state.card(source_card_id)
    assert source_card.zone == Zone.HAND
    summoned_card = next(
        card for card in next_state.card_instances if card.definition_id == summoned_definition_id
    )
    assert summoned_card.instance_id != source_card_id
    assert summoned_card.zone == Zone.BATTLEFIELD
    assert summoned_card.row == source_row
    assert summoned_card.battlefield_side == PLAYER_ONE_ID
    assert next_state.pending_avenger_summons == ()
    assert any(
        isinstance(event, AvengerSummonedEvent)
        and event.source_card_instance_id == source_card_id
        and event.summoned_definition_id == summoned_definition_id
        for event in events
    )


@pytest.mark.parametrize(
    ("source_definition_id", "source_row", "summoned_definition_id"),
    (
        ("neutral_avenger_cow", Row.RANGED, "neutral_bovine_defense_force"),
        ("skellige_kambi", Row.CLOSE, "skellige_hemdall"),
    ),
)
def test_avenger_card_removed_during_round_cleanup_queues_then_summons_next_round(
    source_definition_id: str,
    source_row: Row,
    summoned_definition_id: str,
) -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    source_card_id = CardInstanceId(f"p1_{source_definition_id}_cleanup_source")
    board = (
        rows(close=[card(str(source_card_id), source_definition_id)])
        if source_row == Row.CLOSE
        else rows(ranged=[card(str(source_card_id), source_definition_id)])
    )
    base_state = (
        scenario(f"avenger_cleanup_{source_definition_id}")
        .current_player(PLAYER_TWO_ID)
        .turn_order(starting_player=PLAYER_ONE_ID, round_starter=PLAYER_ONE_ID)
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            board=board,
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )
    player_one = replace(base_state.player(PLAYER_ONE_ID), has_passed=True)
    player_two = replace(base_state.player(PLAYER_TWO_ID), has_passed=False)
    state = replace(
        base_state,
        players=(player_one, player_two),
        current_player=PLAYER_TWO_ID,
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    source_card = next_state.card(source_card_id)
    assert source_card.zone == Zone.DISCARD
    summoned_card = next(
        card for card in next_state.card_instances if card.definition_id == summoned_definition_id
    )
    assert summoned_card.instance_id != source_card_id
    assert summoned_card.zone == Zone.BATTLEFIELD
    assert summoned_card.row == source_row
    assert summoned_card.battlefield_side == PLAYER_ONE_ID
    assert next_state.pending_avenger_summons == ()
    assert any(
        isinstance(event, AvengerSummonQueuedEvent)
        and event.source_card_instance_id == source_card_id
        and event.summoned_definition_id == summoned_definition_id
        for event in events
    )
    assert any(
        isinstance(event, AvengerSummonedEvent)
        and event.source_card_instance_id == source_card_id
        and event.summoned_definition_id == summoned_definition_id
        for event in events
    )
