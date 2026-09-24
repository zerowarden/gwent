from __future__ import annotations

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.hashing import observation_fingerprint
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core.state import GameState

from ..scenario_builder import ScenarioCard, card, rows, scenario
from ..support import CARD_REGISTRY, LEADER_REGISTRY, PLAYER_ONE_ID

SCENARIO_NAME = "observation_invariance"

_DEFAULT_OPPONENT_HAND = (card("p2_hidden_a", "neutral_geralt"),)
_DEFAULT_OPPONENT_DECK = (card("p2_deck_a", "northern_realms_catapult"),)
_DEFAULT_VIEWER_DECK = (
    card("p1_deck_geralt", "neutral_geralt"),
    card("p1_deck_horn", "neutral_commanders_horn"),
)


def _build_state(
    *,
    opponent_hand: tuple[ScenarioCard, ...] = _DEFAULT_OPPONENT_HAND,
    opponent_deck: tuple[ScenarioCard, ...] = _DEFAULT_OPPONENT_DECK,
    viewer_deck: tuple[ScenarioCard, ...] = _DEFAULT_VIEWER_DECK,
) -> GameState:
    return (
        scenario(SCENARIO_NAME)
        .player(
            "p1",
            hand=[card("p1_hand_archer", "scoiatael_dol_blathanna_archer")],
            deck=list(viewer_deck),
            board=rows(close=[card("p1_board_defender", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            hand=list(opponent_hand),
            deck=list(opponent_deck),
            board=rows(ranged=[card("p2_board_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )


def test_opponent_hidden_hand_identities_do_not_change_observation() -> None:
    state_a = _build_state()
    state_b = _build_state(
        opponent_hand=(card("p2_hidden_b", "skellige_kambi"),),
    )

    observation_a = build_player_observation(state_a, PLAYER_ONE_ID)
    observation_b = build_player_observation(state_b, PLAYER_ONE_ID)

    assert observation_a == observation_b
    assert observation_fingerprint(observation_a) == observation_fingerprint(observation_b)


def test_opponent_hidden_deck_identities_and_order_do_not_change_observation() -> None:
    state_a = _build_state(
        opponent_deck=(
            card("p2_deck_a", "northern_realms_catapult"),
            card("p2_deck_b", "neutral_geralt"),
        )
    )
    state_b = _build_state(
        opponent_deck=(
            card("p2_deck_y", "skellige_kambi"),
            card("p2_deck_x", "neutral_mysterious_elf"),
        )
    )

    observation_a = build_player_observation(state_a, PLAYER_ONE_ID)
    observation_b = build_player_observation(state_b, PLAYER_ONE_ID)

    assert observation_a == observation_b
    assert observation_fingerprint(observation_a) == observation_fingerprint(observation_b)


def test_viewer_future_deck_order_does_not_change_observation() -> None:
    state_a = _build_state(viewer_deck=_DEFAULT_VIEWER_DECK)
    state_b = _build_state(viewer_deck=tuple(reversed(_DEFAULT_VIEWER_DECK)))

    observation_a = build_player_observation(state_a, PLAYER_ONE_ID)
    observation_b = build_player_observation(state_b, PLAYER_ONE_ID)

    assert observation_a == observation_b
    assert observation_fingerprint(observation_a) == observation_fingerprint(observation_b)


def test_viewer_deck_composition_changes_are_visible() -> None:
    state_a = _build_state(viewer_deck=_DEFAULT_VIEWER_DECK)
    state_b = _build_state(
        viewer_deck=(
            card("p1_deck_geralt", "neutral_geralt"),
            card("p1_deck_scorch", "neutral_scorch"),
        )
    )

    observation_a = build_player_observation(state_a, PLAYER_ONE_ID)
    observation_b = build_player_observation(state_b, PLAYER_ONE_ID)

    assert observation_a != observation_b
    assert observation_fingerprint(observation_a) != observation_fingerprint(observation_b)


def test_hidden_permutations_do_not_change_offered_legal_action_ids() -> None:
    state_a = _build_state()
    hidden_mutated = _build_state(
        opponent_hand=(card("p2_hidden_z", "skellige_kambi"),),
        opponent_deck=(card("p2_deck_z", "neutral_mysterious_elf"),),
    )
    viewer_reordered = _build_state(viewer_deck=tuple(reversed(_DEFAULT_VIEWER_DECK)))

    def legal_action_ids(state: GameState) -> tuple[str, ...]:
        actions = enumerate_legal_actions(
            state,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
        return tuple(sorted(action_to_id(action) for action in actions))

    expected = legal_action_ids(state_a)
    assert expected
    assert legal_action_ids(hidden_mutated) == expected
    assert legal_action_ids(viewer_reordered) == expected
