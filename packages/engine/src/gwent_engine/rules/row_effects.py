from __future__ import annotations

from dataclasses import dataclass, replace

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, EffectSourceCategory, Row
from gwent_engine.core.events import CardTransformedEvent, GameEvent
from gwent_engine.core.ids import CardInstanceId, LeaderId, PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.rules.state_ops import replace_card_instance


@dataclass(frozen=True, slots=True)
class HornSource:
    source_category: EffectSourceCategory
    source_card_instance_id: CardInstanceId | None = None
    source_leader_id: LeaderId | None = None

    def __post_init__(self) -> None:
        if (self.source_card_instance_id is None) == (self.source_leader_id is None):
            raise ValueError("HornSource must declare exactly one concrete source id.")


def special_ability_kind(definition: CardDefinition) -> AbilityKind:
    if definition.card_type != CardType.SPECIAL:
        raise ValueError("Only special cards declare special effects.")
    if len(definition.ability_kinds) != 1:
        raise ValueError("Special cards must declare exactly one ability_kind.")
    return definition.ability_kinds[0]


def row_has_commanders_horn(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    return horn_source_for_row(state, card_registry, player_id, row) is not None


def row_has_special_commanders_horn(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    return (
        special_row_effect_card_id(
            state,
            card_registry,
            player_id,
            row,
            ability_kind=AbilityKind.COMMANDERS_HORN,
        )
        is not None
    )


def row_has_special_mardroeme(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    return (
        special_row_effect_card_id(
            state,
            card_registry,
            player_id,
            row,
            ability_kind=AbilityKind.MARDROEME,
        )
        is not None
    )


def row_has_active_mardroeme(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    return any(
        card_has_ability(state, card_registry, card_id, AbilityKind.MARDROEME)
        for card_id in state.player(player_id).rows.cards_for(row)
    )


def horn_source_for_row(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> HornSource | None:
    player = state.player(player_id)
    row_card_ids = player.rows.cards_for(row)
    for card_id in row_card_ids:
        if card_has_ability(state, card_registry, card_id, AbilityKind.COMMANDERS_HORN):
            return HornSource(
                source_category=EffectSourceCategory.SPECIAL_CARD,
                source_card_instance_id=card_id,
            )
    if player.leader.horn_row == row:
        return HornSource(
            source_category=EffectSourceCategory.LEADER_ABILITY,
            source_leader_id=player.leader.leader_id,
        )
    for card_id in row_card_ids:
        if card_has_ability(state, card_registry, card_id, AbilityKind.UNIT_COMMANDERS_HORN):
            return HornSource(
                source_category=EffectSourceCategory.UNIT_ABILITY,
                source_card_instance_id=card_id,
            )
    return None


def special_row_effect_card_id(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
    *,
    ability_kind: AbilityKind,
) -> CardInstanceId | None:
    for card_id in state.player(player_id).rows.cards_for(row):
        definition = card_registry.get(state.card(card_id).definition_id)
        if (
            definition.card_type == CardType.SPECIAL
            and len(definition.ability_kinds) == 1
            and definition.ability_kinds[0] == ability_kind
        ):
            return card_id
    return None


def card_has_ability(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    ability_kind: AbilityKind,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return ability_kind in definition.ability_kinds


def apply_berserker_transformations_for_row(
    state: GameState,
    *,
    card_registry: CardRegistry,
    battlefield_side: PlayerId,
    row: Row,
    event_id_start: int,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if not row_has_active_mardroeme(state, card_registry, battlefield_side, row):
        return state, ()

    current_state = state
    events: list[GameEvent] = []
    for card_id in current_state.player(battlefield_side).rows.cards_for(row):
        card = current_state.card(card_id)
        definition = card_registry.get(card.definition_id)
        if (
            definition.card_type != CardType.UNIT
            or AbilityKind.BERSERKER not in definition.ability_kinds
            or definition.transforms_into_definition_id is None
        ):
            continue
        transformed_definition_id = definition.transforms_into_definition_id
        updated_card = replace(card, definition_id=transformed_definition_id)
        current_state = replace(
            current_state,
            card_instances=replace_card_instance(current_state.card_instances, updated_card),
        )
        events.append(
            CardTransformedEvent(
                event_id=event_id_start + len(events),
                player_id=card.owner,
                card_instance_id=card_id,
                previous_definition_id=card.definition_id,
                new_definition_id=transformed_definition_id,
                affected_row=row,
            )
        )
    return current_state, tuple(events)
