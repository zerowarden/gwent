from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState


def definition_has_ability(definition: CardDefinition, ability_kind: AbilityKind) -> bool:
    return ability_kind in definition.ability_kinds


def card_has_ability(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    ability_kind: AbilityKind,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return definition_has_ability(definition, ability_kind)
