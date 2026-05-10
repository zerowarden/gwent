from __future__ import annotations

from collections.abc import Mapping

from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_TACTICAL_VALUE_POLICY
from gwent_engine.ai.utils import viewer_hand_definition
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import GameAction, PassAction, PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardInstanceId


def action_commitment_value(
    action: GameAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
    leader_value: int = DEFAULT_TACTICAL_VALUE_POLICY.leader_commitment_value,
    units_only: bool = False,
    include_spies: bool = True,
) -> int:
    value = 0
    match action:
        case PassAction():
            pass
        case UseLeaderAbilityAction():
            value = leader_value
        case PlayCardAction(card_instance_id=card_instance_id):
            value = _play_card_commitment_value(
                card_instance_id,
                observation=observation,
                card_registry=card_registry,
                viewer_hand_definitions=viewer_hand_definitions,
                units_only=units_only,
                include_spies=include_spies,
            )
        case _:
            pass
    return value


def _play_card_commitment_value(
    card_instance_id: CardInstanceId,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None,
    units_only: bool,
    include_spies: bool,
) -> int:
    definition = viewer_hand_definition(
        card_instance_id,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    if definition is None:
        return 0
    if units_only and definition.card_type != CardType.UNIT:
        return 0
    if not include_spies and AbilityKind.SPY in definition.ability_kinds:
        return 0
    return definition.base_strength


def estimated_response_value(*, hand_count: int, tempo_per_card: int) -> int:
    return hand_count * tempo_per_card
