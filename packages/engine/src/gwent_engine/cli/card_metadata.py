from __future__ import annotations

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState


def build_card_metadata_maps(
    state: GameState,
    *,
    card_registry: CardRegistry,
) -> tuple[
    dict[CardInstanceId, str],
    dict[CardInstanceId, int],
    dict[CardInstanceId, str],
    dict[CardInstanceId, bool],
    dict[CardInstanceId, bool],
    dict[CardInstanceId, bool],
    dict[CardInstanceId, bool],
]:
    names: dict[CardInstanceId, str] = {}
    values: dict[CardInstanceId, int] = {}
    kinds: dict[CardInstanceId, str] = {}
    spies: dict[CardInstanceId, bool] = {}
    medics: dict[CardInstanceId, bool] = {}
    horns: dict[CardInstanceId, bool] = {}
    scorches: dict[CardInstanceId, bool] = {}
    for card in state.card_instances:
        definition = card_registry.get(card.definition_id)
        names[card.instance_id] = definition.name
        values[card.instance_id] = definition.base_strength
        kinds[card.instance_id] = _card_kind(definition)
        spies[card.instance_id] = AbilityKind.SPY in definition.ability_kinds
        medics[card.instance_id] = AbilityKind.MEDIC in definition.ability_kinds
        horns[card.instance_id] = (
            AbilityKind.COMMANDERS_HORN in definition.ability_kinds
            or AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds
        )
        scorches[card.instance_id] = (
            AbilityKind.SCORCH in definition.ability_kinds
            or AbilityKind.UNIT_SCORCH_ROW in definition.ability_kinds
        )
    return names, values, kinds, spies, medics, horns, scorches


def _card_kind(definition: CardDefinition) -> str:
    if definition.is_hero:
        return "hero"
    if definition.card_type.value == "special":
        return "special"
    return "unit"
