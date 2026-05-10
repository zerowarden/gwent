from __future__ import annotations

from dataclasses import replace
from typing import cast

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline import (
    DEFAULT_BASELINE_CONFIG,
    build_assessment,
    classify_context,
    compose_profile,
    evaluate_action,
    explain_action_score,
)
from gwent_engine.ai.baseline.evaluation import ActionScoreBreakdown, ScoreTerm
from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.debug import (
    explain_heuristic_decision_from_state,
    heuristic_decision_to_dict,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import (
    ChoiceSourceKind,
    Row,
)
from gwent_engine.core.actions import PlayCardAction, ResolveChoiceAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardInstanceId, ChoiceId
from gwent_engine.core.state import GameState

from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)

from ..scenario_builder import card, rows, scenario
from .test_baseline_support import (
    make_mardroeme_transform_choice_state,
    make_steel_forged_noop_state,
)


def test_explain_action_score_total_matches_evaluate_action() -> None:
    state = (
        scenario("explain_action_score")
        .player(
            "p1",
            leader_used=True,
            hand=[card("p1_archer", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            leader_used=True,
            hand=[card("p2_hidden_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    action = next(action for action in legal_actions if isinstance(action, PlayCardAction))
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    assert breakdown.total == evaluate_action(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )
    assert breakdown.terms


def test_explain_heuristic_decision_surfaces_minimum_commitment_override() -> None:
    state = _minimum_commitment_override_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        legal_actions=legal_actions,
    )

    assert explanation.chosen_action == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_recruit_finish"),
        target_row=Row.RANGED,
    )
    assert explanation.override is not None
    assert explanation.override.reason == "minimum_commitment_finish"
    assert explanation.profile.profile_id == DEFAULT_BASE_PROFILE.profile_id
    assert explanation.profile.policy_names.scorch_policy == "opportunistic_scorch"
    assert explanation.profile.policy_names.leader_policy == "aggressive"
    assert any(candidate.shortlisted for candidate in explanation.candidates)
    assert explanation.ranked_actions


def test_explain_action_score_surfaces_noop_steel_forged_penalty() -> None:
    state = make_steel_forged_noop_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    action = next(action for action in legal_actions if isinstance(action, UseLeaderAbilityAction))
    assessment = build_assessment(
        observation,
        CARD_REGISTRY,
        legal_actions=legal_actions,
    )
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(term.name == "leader_no_effect_penalty" for term in breakdown.terms)
    assert all(term.name != "leader_immediate_need" for term in breakdown.terms)


def test_explain_action_score_surfaces_deterministic_tactical_rebate() -> None:
    state = make_mardroeme_transform_choice_state()
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_mardroeme"),
        target_row=Row.CLOSE,
    )
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    rebate_term = _term_named(breakdown, "deterministic_tactical_rebate")

    assert rebate_term.value > 0
    assert _detail_value(rebate_term, "tactical_family") == "mardroeme"
    assert cast(float, _detail_value(rebate_term, "realized_tactical_lift_raw")) > 0
    assert cast(float, _detail_value(rebate_term, "speculative_penalty_score")) > 0


def test_explain_heuristic_decision_marks_noop_steel_forged_leader_candidate() -> None:
    state = make_steel_forged_noop_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        legal_actions=legal_actions,
    )

    leader_candidate = next(
        candidate
        for candidate in explanation.candidates
        if isinstance(candidate.action, UseLeaderAbilityAction)
    )

    assert explanation.chosen_action != leader_candidate.action
    assert leader_candidate.reason == "leader no-op"
    assert leader_candidate.coarse_score == -4.0


def test_explain_heuristic_decision_surfaces_pending_choice_terms() -> None:
    state = (
        scenario("explain_pending_choice_decoy")
        .round(2)
        .player(
            "p1",
            faction="nilfgaard",
            gems_remaining=1,
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_spy_target", "neutral_mysterious_elf", owner="p2"),
                    card("p1_archer_target", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .player("p2", faction="nilfgaard", gems_remaining=1)
        .card_choice(
            choice_id="pending_choice_1",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_spy_target", "p1_archer_target"),
        )
        .build()
    )
    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    assert explanation.chosen_action == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("pending_choice_1"),
        selected_card_instance_ids=(CardInstanceId("p1_spy_target"),),
    )
    assert explanation.ranked_actions
    assert explanation.ranked_actions[0].terms
    assert all(
        term.name != "unsupported_action_penalty" for term in explanation.ranked_actions[0].terms
    )
    assert any(
        term.name == "decoy_target_spy_bonus" for term in explanation.ranked_actions[0].terms
    )


def test_explain_action_score_surfaces_return_leader_value_terms() -> None:
    state = (
        scenario("explain_return_leader_terms")
        .round(2)
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_bringer_of_death",
            discard=[card("p1_return_catapult", "northern_realms_catapult")],
        )
        .player("p2", leader_used=True, hand=[card("p2_hidden", "scoiatael_dol_blathanna_archer")])
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    action = next(action for action in legal_actions if isinstance(action, UseLeaderAbilityAction))
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(term.name == "leader_projected_hand_value" for term in breakdown.terms)
    assert any(term.name == "leader_projected_card_advantage" for term in breakdown.terms)


def test_explain_heuristic_decision_surfaces_leader_pending_choice_terms() -> None:
    state = (
        scenario("explain_leader_pending_choice")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_bringer_of_death",
            discard=[
                card("p1_return_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_return_catapult", "northern_realms_catapult"),
            ],
        )
        .leader_choice(
            choice_id="leader_return_choice",
            player_id="p1",
            source_leader_id="monsters_eredin_bringer_of_death",
            legal_target_card_instance_ids=("p1_return_archer", "p1_return_catapult"),
        )
        .build()
    )

    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        player_id=PLAYER_ONE_ID,
    )

    assert explanation.chosen_action == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("leader_return_choice"),
        selected_card_instance_ids=(CardInstanceId("p1_return_catapult"),),
    )
    assert any(term.name == "leader_return_value" for term in explanation.ranked_actions[0].terms)


def test_explain_heuristic_decision_surfaces_leader_steal_terms_for_player_two() -> None:
    state = (
        scenario("explain_leader_steal_pending_choice_p2")
        .player(
            "p1",
            discard=[
                card("a_target_vill", "neutral_villentretenmerth"),
                card("z_target_crone", "monsters_crone_weavess"),
            ],
        )
        .player(
            "p2",
            faction="nilfgaard",
            leader_id="nilfgaard_emhyr_the_relentless",
        )
        .leader_choice(
            choice_id="leader_steal_choice_p2",
            player_id="p2",
            source_leader_id="nilfgaard_emhyr_the_relentless",
            legal_target_card_instance_ids=("a_target_vill", "z_target_crone"),
        )
        .build()
    )

    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        player_id=PLAYER_TWO_ID,
    )

    assert explanation.chosen_action == ResolveChoiceAction(
        player_id=PLAYER_TWO_ID,
        choice_id=ChoiceId("leader_steal_choice_p2"),
        selected_card_instance_ids=(CardInstanceId("a_target_vill"),),
    )
    assert explanation.ranked_actions
    assert all(
        term.name != "unsupported_action_penalty" for term in explanation.ranked_actions[0].terms
    )
    assert any(term.name == "leader_steal_value" for term in explanation.ranked_actions[0].terms)


def test_explain_heuristic_decision_surfaces_pruned_candidates_and_comparison() -> None:
    config = replace(
        DEFAULT_BASELINE_CONFIG,
        candidates=replace(DEFAULT_BASELINE_CONFIG.candidates, max_candidates=2),
    )
    state = _candidate_pruning_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
        config=config,
        legal_actions=legal_actions,
    )

    assert any(candidate.prune_stage == "candidate_pool" for candidate in explanation.candidates)
    assert explanation.comparison is not None
    assert explanation.comparison.selection_source == "ranked_choice"
    assert explanation.comparison.runner_up_action is not None
    assert explanation.comparison.score_margin is not None
    assert explanation.comparison.decisive_terms


def test_explanation_export_surfaces_comparison_and_pruning() -> None:
    state = _minimum_commitment_override_state()

    heuristic_explanation = explain_heuristic_decision_from_state(
        state,
        card_registry=CARD_REGISTRY,
    )
    heuristic_payload = heuristic_decision_to_dict(heuristic_explanation)

    assert heuristic_payload["comparison"] is not None
    assert heuristic_payload["candidates"]
    assert heuristic_payload["chosen_action"]
    profile_payload = cast(dict[str, object], heuristic_payload["profile"])
    assert "weight_provenance" in profile_payload
    first_ranked_actions = cast(list[object], heuristic_payload["ranked_actions"])
    first_ranked_action = cast(dict[str, object], first_ranked_actions[0])
    first_ranked_term = cast(
        dict[str, object],
        cast(list[object], first_ranked_action["terms"])[0],
    )
    assert "formula" in first_ranked_term
    assert "details" in first_ranked_term


def test_explain_action_score_does_not_flag_overcommit_from_even_open_board() -> None:
    state = (
        scenario("explain_no_overcommit_even_open_board")
        .player(
            "p1",
            hand=[card("p1_geralt", "neutral_geralt")],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    action = next(action for action in legal_actions if isinstance(action, PlayCardAction))
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    overcommit_term = _term_named(breakdown, "overcommit_penalty")

    assert overcommit_term.raw_value == 0.0
    assert _detail_value(overcommit_term, "overcommit_window_active") == "no"


def test_explain_action_score_uses_trickery_allowance_before_open_round_overcommit() -> None:
    state = (
        scenario("explain_open_round_trickery_allowance")
        .player(
            "p1",
            hand=[card("p1_small_commit", "skellige_clan_draig_bon_dhu")],
            board=rows(close=[card("p1_existing_board", "skellige_clan_an_craie_warrior")]),
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    action = next(
        action
        for action in legal_actions
        if isinstance(action, PlayCardAction)
        and action.card_instance_id == CardInstanceId("p1_small_commit")
    )
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    overcommit_term = _term_named(breakdown, "overcommit_penalty")

    assert overcommit_term.raw_value == 0.0
    assert _detail_value(overcommit_term, "trickery_allowance") == 2
    assert _detail_value(overcommit_term, "true_overcommit_gap_after") == 8


def test_explain_action_score_flags_true_overcommit_after_opponent_passes() -> None:
    state = _minimum_commitment_override_state()
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )
    action = PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_defender_overkill"),
        target_row=Row.CLOSE,
    )
    assessment = build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions)
    context = classify_context(assessment)
    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=DEFAULT_BASE_PROFILE,
    )

    breakdown = explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=CARD_REGISTRY,
    )

    overcommit_term = _term_named(breakdown, "overcommit_penalty")

    assert cast(float, overcommit_term.raw_value) > 0
    assert _detail_value(overcommit_term, "required_score_gap_after") == 1
    assert _detail_value(overcommit_term, "trickery_allowance") == 0
    assert _detail_value(overcommit_term, "overcommit_window_active") == "yes"


def _minimum_commitment_override_state() -> GameState:
    return (
        scenario("heuristic_minimum_finish_explain")
        .round(3)
        .player(
            "p1",
            gems_remaining=1,
            hand=[
                card("p1_recruit_finish", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_defender_overkill", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(
            "p2",
            gems_remaining=1,
            passed=True,
            board=rows(close=[card("p2_board_unit", "scoiatael_dwarven_skirmisher")]),
        )
        .build()
    )


def _candidate_pruning_state() -> GameState:
    return (
        scenario("heuristic_candidate_pruning_explain")
        .player(
            "p1",
            leader_used=True,
            hand=[
                card("p1_light_unit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_medium_unit", "scoiatael_dol_blathanna_archer"),
                card("p1_heavy_unit", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(
            "p2",
            leader_used=True,
            hand=[card("p2_hidden_card", "scoiatael_dwarven_skirmisher")],
        )
        .build()
    )


def _term_named(breakdown: ActionScoreBreakdown, name: str) -> ScoreTerm:
    return next(term for term in breakdown.terms if term.name == name)


def _detail_value(term: ScoreTerm, key: str) -> float | int | str:
    return next(detail.value for detail in term.details if detail.key == key)
