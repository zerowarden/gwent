from __future__ import annotations

from dataclasses import replace

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.observations import (
    build_player_observation,
)
from gwent_engine.ai.policy import DEFAULT_SEARCH_CONFIG, SearchConfig
from gwent_engine.ai.search import build_search_engine
from gwent_engine.ai.search.opponent_model import generate_opponent_reply_candidates
from gwent_engine.ai.search.simulation import (
    PlayerSimulation,
    materialize_player_simulation,
)
from gwent_engine.ai.search.turn_resolution import should_search_opponent_reply
from gwent_engine.core import ChoiceSourceKind, Row
from gwent_engine.core.actions import (
    PlayCardAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import (
    CardInstanceId,
    PlayerId,
)
from gwent_engine.core.state import GameState

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
    NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
)


def _simulate(
    state: GameState,
    *,
    viewer_player_id: PlayerId = PLAYER_ONE_ID,
) -> PlayerSimulation:
    observation = build_player_observation(state, viewer_player_id, LEADER_REGISTRY)
    return materialize_player_simulation(
        observation,
        card_registry=CARD_REGISTRY,
    )


def test_search_engine_does_not_expect_a_reply_from_an_exhausted_opponent() -> None:
    state = (
        scenario("search_exhausted_opponent")
        .player(
            "p1",
            hand=[
                card("p1_catapult", "northern_realms_catapult"),
                card("p1_defender", "scoiatael_mahakaman_defender"),
            ],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            leader_used=True,
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .build()
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.used_fallback_policy is False
    assert result.chosen_action == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_catapult"),
        target_row=Row.SIEGE,
    )


def test_search_engine_expects_leader_reply_from_empty_handed_opponent() -> None:
    state = (
        scenario("search_empty_handed_opponent_with_leader")
        .player(
            "p1",
            hand=[card("p1_catapult", "northern_realms_catapult")],
            board=rows(siege=[card("p1_trebuchet", "northern_realms_trebuchet")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
            board=rows(siege=[card("p2_catapult", "northern_realms_catapult")]),
        )
        .current_player(PLAYER_TWO_ID)
        .build()
    )
    state = replace(state, round_number=3)

    decision = should_search_opponent_reply(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert decision.enabled is True

    candidates = generate_opponent_reply_candidates(
        state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(isinstance(candidate.action, UseLeaderAbilityAction) for candidate in candidates)


def test_search_engine_skips_reply_search_when_opponent_has_passed() -> None:
    state = (
        scenario("search_skip_reply_opponent_passed")
        .player(
            "p1",
            hand=[
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_reserve", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(
            "p2",
            passed=True,
            faction="northern_realms",
            leader_id=str(NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID),
        )
        .build()
    )
    engine = build_search_engine(
        config=DEFAULT_SEARCH_CONFIG,
        profile_definition=DEFAULT_BASE_PROFILE,
        bot_id="search_test",
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    result = engine.choose_action(
        observation,
        legal_actions,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert result.principal_line is not None
    assert result.principal_line.reply_actions == ()
    assert any(
        note in {"reply_search=opponent_already_passed", "reply_search=control_not_with_opponent"}
        for note in result.principal_line.notes
    )


def test_generate_opponent_reply_candidates_adds_inferred_hidden_pressure() -> None:
    state = (
        scenario("search_inferred_hidden_pressure")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            hand=[
                card("p2_hidden_a", "scoiatael_mahakaman_defender"),
                card("p2_hidden_b", "scoiatael_dol_blathanna_archer"),
                card("p2_hidden_c", "northern_realms_trebuchet"),
            ],
        )
        .current_player("p2")
        .build()
    )

    simulation = _simulate(state)
    candidates = generate_opponent_reply_candidates(
        simulation.state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(candidate.reason == "inferred_hidden_hand_pressure" for candidate in candidates)
    inferred = next(
        candidate for candidate in candidates if candidate.reason == "inferred_hidden_hand_pressure"
    )
    assert inferred.action is None
    assert inferred.inferred_penalty > 0


def test_generate_opponent_reply_candidates_respect_hidden_pressure_config() -> None:
    state = (
        scenario("search_inferred_hidden_pressure_tuning")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            hand=[
                card("p2_hidden_a", "scoiatael_mahakaman_defender"),
                card("p2_hidden_b", "scoiatael_dol_blathanna_archer"),
                card("p2_hidden_c", "northern_realms_trebuchet"),
            ],
        )
        .current_player("p2")
        .build()
    )

    simulation = _simulate(state)
    default_inferred = next(
        candidate
        for candidate in generate_opponent_reply_candidates(
            simulation.state,
            viewer_player_id=PLAYER_ONE_ID,
            profile_definition=DEFAULT_BASE_PROFILE,
            config=DEFAULT_SEARCH_CONFIG,
            card_registry=simulation.card_registry,
            leader_registry=LEADER_REGISTRY,
        )
        if candidate.reason == "inferred_hidden_hand_pressure"
    )
    reduced_inferred = next(
        candidate
        for candidate in generate_opponent_reply_candidates(
            simulation.state,
            viewer_player_id=PLAYER_ONE_ID,
            profile_definition=DEFAULT_BASE_PROFILE,
            config=SearchConfig(
                hidden_reply_unused_leader_bonus=0.0,
                hidden_reply_hand_parity_bonus=0.0,
            ),
            card_registry=simulation.card_registry,
            leader_registry=LEADER_REGISTRY,
        )
        if candidate.reason == "inferred_hidden_hand_pressure"
    )

    assert default_inferred.inferred_penalty > reduced_inferred.inferred_penalty


def test_generate_opponent_reply_candidates_caps_pending_choice_replies() -> None:
    state = (
        scenario("search_reply_cap_pending_choice")
        .player(
            "p1",
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_target_a", "neutral_mysterious_elf", owner="p2"),
                    card("p1_target_b", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_target_a", "p1_target_b"),
        )
        .current_player("p1")
        .build()
    )

    simulation = _simulate(state, viewer_player_id=PLAYER_ONE_ID)
    candidates = generate_opponent_reply_candidates(
        simulation.state,
        viewer_player_id=PLAYER_TWO_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=SearchConfig(max_opponent_replies=1),
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert len(candidates) == 1


def test_reply_depth_policy_triggers_for_close_score_gap() -> None:
    state = (
        scenario("search_reply_policy_close_gap")
        .player("p1", board=rows(close=[card("p1_archer", "scoiatael_dol_blathanna_archer")]))
        .player("p2", hand=[card("p2_hidden", "scoiatael_mahakaman_defender")])
        .current_player("p2")
        .build()
    )

    simulation = _simulate(state)
    decision = should_search_opponent_reply(
        simulation.state,
        viewer_player_id=PLAYER_ONE_ID,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert decision.enabled is True
    assert decision.reason in {"close_score_gap", "opponent_hidden_pressure"}


def test_generate_opponent_reply_candidates_do_not_exact_search_hidden_pending_choice() -> None:
    state = (
        scenario("search_hidden_pending_choice_redacted")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            faction="monsters",
            leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .pending_choice(
            choice_id="hidden_leader_choice",
            player_id="p2",
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            legal_target_card_instance_ids=("p2_hidden_hand", "p2_hidden_deck"),
            min_selections=2,
            max_selections=2,
        )
        .current_player("p2")
        .build()
    )

    simulation = _simulate(state, viewer_player_id=PLAYER_TWO_ID)
    candidates = generate_opponent_reply_candidates(
        simulation.state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert candidates
    assert all(candidate.action is None for candidate in candidates)
    assert {candidate.reason for candidate in candidates} == {"inferred_hidden_pending_choice"}


def test_generate_opponent_reply_candidates_respect_hidden_pending_choice_bonus() -> None:
    state = (
        scenario("search_hidden_pending_choice_tuning")
        .player(
            "p1",
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            faction="monsters",
            leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            hand=[card("p2_hidden_hand", "neutral_geralt")],
            deck=[card("p2_hidden_deck", "northern_realms_catapult")],
        )
        .pending_choice(
            choice_id="hidden_leader_choice_tuning",
            player_id="p2",
            source_kind=ChoiceSourceKind.LEADER_ABILITY,
            source_leader_id=str(MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID),
            legal_target_card_instance_ids=("p2_hidden_hand", "p2_hidden_deck"),
            min_selections=2,
            max_selections=2,
        )
        .current_player("p2")
        .build()
    )

    simulation = _simulate(state, viewer_player_id=PLAYER_TWO_ID)
    default_inferred = generate_opponent_reply_candidates(
        simulation.state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=DEFAULT_SEARCH_CONFIG,
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )[0]
    boosted_inferred = generate_opponent_reply_candidates(
        simulation.state,
        viewer_player_id=PLAYER_ONE_ID,
        profile_definition=DEFAULT_BASE_PROFILE,
        config=SearchConfig(hidden_pending_choice_bonus=9.0),
        card_registry=simulation.card_registry,
        leader_registry=LEADER_REGISTRY,
    )[0]

    assert default_inferred.reason == "inferred_hidden_pending_choice"
    assert boosted_inferred.reason == "inferred_hidden_pending_choice"
    assert boosted_inferred.inferred_penalty > default_inferred.inferred_penalty
