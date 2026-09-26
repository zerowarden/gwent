from __future__ import annotations

from gwent_shared.digests import canonical_hexdigest

from gwent_engine.ai.observations import (
    PlayerObservation,
    PublicGameStateView,
    player_observation_to_dict,
    public_game_view_to_dict,
)
from gwent_engine.core.events import GameEvent
from gwent_engine.core.state import GameState
from gwent_engine.serialize import event_to_dict, game_state_to_dict


def state_fingerprint(state: GameState) -> str:
    return _fingerprint_payload(game_state_to_dict(state))


def public_state_fingerprint(view: PublicGameStateView) -> str:
    return _fingerprint_payload(public_game_view_to_dict(view))


def observation_fingerprint(observation: PlayerObservation) -> str:
    return _fingerprint_payload(player_observation_to_dict(observation))


def event_fingerprint(event: GameEvent) -> str:
    return _fingerprint_payload(event_to_dict(event))


def _fingerprint_payload(payload: object) -> str:
    return canonical_hexdigest(payload)
