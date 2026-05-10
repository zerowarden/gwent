from gwent_engine.ai.hashing import (
    observation_fingerprint,
    public_state_fingerprint,
    state_fingerprint,
)
from gwent_engine.ai.observations import build_player_observation, build_public_game_view
from gwent_engine.serialize import game_state_from_dict, game_state_to_dict

from ..support import PLAYER_ONE_ID, build_in_round_game_state


def test_state_fingerprint_is_stable_across_replay_roundtrip() -> None:
    state, _ = build_in_round_game_state()
    roundtrip_state = game_state_from_dict(game_state_to_dict(state))

    assert state_fingerprint(state) == state_fingerprint(roundtrip_state)


def test_public_and_private_fingerprints_differ_when_hand_information_differs() -> None:
    state, _ = build_in_round_game_state()
    public_view = build_public_game_view(state)
    observation = build_player_observation(state, PLAYER_ONE_ID)

    assert public_state_fingerprint(public_view) != observation_fingerprint(observation)
