from __future__ import annotations

from collections.abc import Mapping, Sequence

from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core.actions import GameAction, LeaveAction
from gwent_engine.core.ids import CardInstanceId


def filter_non_leave_actions(legal_actions: Sequence[GameAction]) -> tuple[GameAction, ...]:
    actions = tuple(legal_actions)
    non_leave_actions = tuple(action for action in actions if not isinstance(action, LeaveAction))
    return non_leave_actions or actions


def build_viewer_hand_definition_index(
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> dict[CardInstanceId, CardDefinition]:
    return {
        card.instance_id: card_registry.get(card.definition_id) for card in observation.viewer_hand
    }


def viewer_hand_definition(
    card_instance_id: CardInstanceId,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> CardDefinition | None:
    if viewer_hand_definitions is not None:
        return viewer_hand_definitions.get(card_instance_id)
    for card in observation.viewer_hand:
        if card.instance_id == card_instance_id:
            return card_registry.get(card.definition_id)
    return None
