"""Content fingerprints of engine states, observations, and events."""

from __future__ import annotations

from gwent_shared.json_payloads import canonical_hexdigest

from gwent_engine.ai.observations import PlayerObservation, player_observation_to_dict
from gwent_engine.core.events import GameEvent
from gwent_engine.core.state import GameState
from gwent_engine.serialize import event_to_dict, game_state_to_dict


def state_fingerprint(state: GameState) -> str:
    return canonical_hexdigest(game_state_to_dict(state))


def observation_fingerprint(observation: PlayerObservation) -> str:
    return canonical_hexdigest(player_observation_to_dict(observation))


def event_fingerprint(event: GameEvent) -> str:
    return canonical_hexdigest(event_to_dict(event))
