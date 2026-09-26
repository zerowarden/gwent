from __future__ import annotations

from gwent_engine.core.actions import GameAction
from gwent_engine.serialize.actions import (
    ActionPayload,
    ActionPayloadValue,
    action_payload,
    action_to_id,
)

ACTION_TYPE_ORDER = {
    "StartGameAction": 0,
    "ResolveMulligansAction": 1,
    "ResolveChoiceAction": 2,
    "PlayCardAction": 3,
    "UseLeaderAbilityAction": 4,
    "PassAction": 5,
    "LeaveAction": 6,
}

__all__ = [
    "ACTION_TYPE_ORDER",
    "ActionPayload",
    "ActionPayloadValue",
    "action_payload",
    "action_sort_key",
    "action_to_id",
]


def action_sort_key(action: GameAction) -> tuple[object, ...]:
    payload = action_payload(action)
    type_name = str(payload["type"])
    return (
        ACTION_TYPE_ORDER[type_name],
        *(payload[key] for key in sorted(payload) if key != "type"),
    )
