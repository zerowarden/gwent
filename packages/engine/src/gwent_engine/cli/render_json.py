from __future__ import annotations

from typing import cast

from gwent_engine.ai.action_ids import ActionPayloadValue, action_payload
from gwent_engine.cli.models import CliMetadata
from gwent_engine.core.actions import GameAction


def metadata_to_dict(metadata: CliMetadata) -> dict[str, object]:
    payload: dict[str, object] = {
        "game_id": str(metadata.game_id),
        "p1_id": str(metadata.player_one_id),
        "p2_id": str(metadata.player_two_id),
        "p1_deck_id": str(metadata.player_one_deck_id),
        "p2_deck_id": str(metadata.player_two_deck_id),
        "p1_leader_id": str(metadata.player_one_leader_id),
        "p2_leader_id": str(metadata.player_two_leader_id),
        "p1_leader_name": metadata.player_one_leader_name,
        "p2_leader_name": metadata.player_two_leader_name,
        "rng_name": metadata.rng_name,
        "pending_choice_encountered": metadata.pending_choice_encountered,
    }
    if metadata.player_one_actor is not None:
        payload["p1_actor"] = metadata.player_one_actor
    if metadata.player_two_actor is not None:
        payload["p2_actor"] = metadata.player_two_actor
    return payload


def action_to_dict(action: GameAction) -> dict[str, object]:
    payload = action_payload(action)
    type_name = cast(str, payload["type"])
    if type_name == "ResolveMulligansAction":
        selections = cast(
            tuple[tuple[str, tuple[str, ...]], ...],
            payload["selections"],
        )
        return {
            "type": type_name,
            "selections": [
                {"player_id": player_id, "cards_to_replace": list(cards)}
                for player_id, cards in selections
            ],
        }
    return {key: _json_field(value) for key, value in payload.items()}


def _json_field(value: ActionPayloadValue) -> object:
    if isinstance(value, tuple):
        return list(value)
    return None if value == "" else value
