from __future__ import annotations

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import CardType, FactionId, Row
from gwent_engine.core.ids import CardDefinitionId

# Placeholder definition used only inside derived search simulations. Opponent
# hidden zones and other unknown slots are collapsed to this definition so the
# simulation never carries card identities the observing player could not see.
SIMULATION_HIDDEN_CARD_DEFINITION = CardDefinition(
    definition_id=CardDefinitionId("simulation_hidden_card"),
    name="Hidden Card",
    faction=FactionId.SCOIATAEL,
    card_type=CardType.UNIT,
    base_strength=5,
    allowed_rows=(Row.CLOSE,),
)


def provision_simulation_registry(card_registry: CardRegistry) -> CardRegistry:
    if SIMULATION_HIDDEN_CARD_DEFINITION.definition_id in card_registry:
        return card_registry
    return CardRegistry.from_definitions((*tuple(card_registry), SIMULATION_HIDDEN_CARD_DEFINITION))
