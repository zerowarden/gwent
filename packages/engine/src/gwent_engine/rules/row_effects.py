from dataclasses import dataclass

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, EffectSourceCategory, Row
from gwent_engine.core.ids import CardInstanceId, LeaderId, PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.rules.card_abilities import card_has_ability


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
    return _row_has_special_effect(
        state,
        card_registry,
        player_id,
        row,
        ability_kind=AbilityKind.COMMANDERS_HORN,
    )


def row_has_special_mardroeme(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    return _row_has_special_effect(
        state,
        card_registry,
        player_id,
        row,
        ability_kind=AbilityKind.MARDROEME,
    )


def _row_has_special_effect(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
    *,
    ability_kind: AbilityKind,
) -> bool:
    return (
        special_row_effect_card_id(
            state,
            card_registry,
            player_id,
            row,
            ability_kind=ability_kind,
        )
        is not None
    )


def row_has_active_mardroeme(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
) -> bool:
    if row_has_special_mardroeme(state, card_registry, player_id, row):
        return True
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
