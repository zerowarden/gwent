from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import AbilityKind, CardType, Zone
from gwent_engine.core.events import AvengerSummonedEvent, AvengerSummonQueuedEvent, GameEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    PendingAvengerSummon,
)
from gwent_engine.rules.players import replace_player
from gwent_engine.rules.state_ops import append_to_row


def resolve_leave_battlefield_triggers(
    state: GameState,
    removed_cards: tuple[CardInstance, ...],
    *,
    card_registry: CardRegistry,
    event_id_start: int,
    queue_for_next_round: bool,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    current_state = state
    events: list[GameEvent] = []
    for removed_card in removed_cards:
        definition = card_registry.get(removed_card.definition_id)
        if (
            definition.card_type != CardType.UNIT
            or AbilityKind.AVENGER not in definition.ability_kinds
            or definition.avenger_summon_definition_id is None
            or removed_card.row is None
            or removed_card.battlefield_side is None
        ):
            continue
        summon = PendingAvengerSummon(
            source_card_instance_id=removed_card.instance_id,
            summoned_definition_id=definition.avenger_summon_definition_id,
            owner=removed_card.owner,
            battlefield_side=removed_card.battlefield_side,
            row=removed_card.row,
        )
        if queue_for_next_round:
            current_state = replace(
                current_state,
                pending_avenger_summons=(*current_state.pending_avenger_summons, summon),
            )
            events.append(
                AvengerSummonQueuedEvent(
                    event_id=event_id_start + len(events),
                    player_id=removed_card.owner,
                    source_card_instance_id=removed_card.instance_id,
                    summoned_definition_id=summon.summoned_definition_id,
                    affected_row=removed_card.row,
                )
            )
            continue
        current_state, summon_event = _summon_from_pending(
            current_state,
            summon=summon,
            event_id=event_id_start + len(events),
        )
        events.append(summon_event)
    return current_state, tuple(events)


def resolve_pending_avenger_summons_at_round_start(
    state: GameState,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    current_state = state
    events: list[GameEvent] = []
    queued_summons = current_state.pending_avenger_summons
    for summon in queued_summons:
        current_state, summon_event = _summon_from_pending(
            current_state,
            summon=summon,
            event_id=current_state.event_counter + len(events) + 1,
        )
        events.append(summon_event)
    if queued_summons:
        current_state = replace(current_state, pending_avenger_summons=())
    return current_state, tuple(events)


def _summon_from_pending(
    state: GameState,
    *,
    summon: PendingAvengerSummon,
    event_id: int,
) -> tuple[GameState, AvengerSummonedEvent]:
    next_generated_card_counter = state.generated_card_counter + 1
    summoned_card_instance_id = CardInstanceId(
        f"generated_{summon.summoned_definition_id}_{next_generated_card_counter}"
    )
    summoned_card = CardInstance(
        instance_id=summoned_card_instance_id,
        definition_id=summon.summoned_definition_id,
        owner=summon.owner,
        zone=Zone.BATTLEFIELD,
        row=summon.row,
        battlefield_side=summon.battlefield_side,
    )
    battlefield_player = state.player(summon.battlefield_side)
    updated_battlefield_player = replace(
        battlefield_player,
        rows=append_to_row(battlefield_player.rows, summon.row, summoned_card_instance_id),
    )
    next_state = replace(
        state,
        players=replace_player(state.players, updated_battlefield_player),
        card_instances=(*state.card_instances, summoned_card),
        generated_card_counter=next_generated_card_counter,
    )
    return (
        next_state,
        AvengerSummonedEvent(
            event_id=event_id,
            player_id=summon.owner,
            source_card_instance_id=summon.source_card_instance_id,
            summoned_card_instance_id=summoned_card_instance_id,
            summoned_definition_id=summon.summoned_definition_id,
            affected_row=summon.row,
        ),
    )
