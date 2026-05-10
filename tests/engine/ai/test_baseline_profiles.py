from dataclasses import replace

from gwent_engine.ai.baseline.context import TacticalMode, classify_context
from gwent_engine.ai.baseline.profile_catalog import (
    BaseProfileDefinition,
    ProfilePassOverrides,
    ProfileWeightOverrides,
)
from gwent_engine.ai.baseline.profiles import compose_profile
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, PolicySelection, ProfileTuningConfig

from .test_baseline_support import make_assessment


def test_compose_profile_biases_opening_toward_card_advantage() -> None:
    assessment = make_assessment()
    context = classify_context(assessment)

    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    assert profile.weights.card_advantage > DEFAULT_BASELINE_CONFIG.weights.card_advantage
    assert (
        profile.weights.remaining_hand_value > DEFAULT_BASELINE_CONFIG.weights.remaining_hand_value
    )


def test_compose_profile_biases_opponent_passed_toward_exact_finish() -> None:
    assessment = make_assessment(
        score_gap=3, opponent_passed=True, viewer_board_strength=6, opponent_board_strength=3
    )
    context = classify_context(assessment)

    profile = compose_profile(DEFAULT_BASELINE_CONFIG, assessment, context)

    assert profile.minimum_commitment_bias > 1.0
    assert profile.weights.exact_finish_bonus > DEFAULT_BASELINE_CONFIG.weights.exact_finish_bonus
    assert profile.candidate_limit <= DEFAULT_BASELINE_CONFIG.candidates.max_candidates
    assert context.mode == TacticalMode.FINISH_AFTER_PASS


def test_compose_profile_uses_profile_tuning_config_values() -> None:
    assessment = make_assessment(
        score_gap=3,
        opponent_passed=True,
        viewer_board_strength=6,
        opponent_board_strength=3,
    )
    context = classify_context(assessment)
    config = replace(
        DEFAULT_BASELINE_CONFIG,
        profile_tuning=ProfileTuningConfig(
            economy_weight_multiplier=1.2,
            tempo_weight_multiplier=1.3,
            leader_preservation_multiplier=1.05,
            minimum_commitment_weight_multiplier=1.4,
            opponent_passed_candidate_limit=2,
            minimum_commitment_mode_bias=3.0,
            neutral_commitment_mode_bias=1.0,
            preserve_resources_bias=1.4,
            spend_resources_bias=0.8,
        ),
    )

    profile = compose_profile(config, assessment, context)

    assert profile.weights.exact_finish_bonus == (
        DEFAULT_BASELINE_CONFIG.weights.exact_finish_bonus * 1.3 * 1.4
    )
    assert profile.candidate_limit == 2
    assert profile.minimum_commitment_bias == 3.0


def test_compose_profile_uses_base_profile_definition() -> None:
    assessment = make_assessment(card_advantage=1)
    context = classify_context(assessment)
    base_profile = BaseProfileDefinition(
        profile_id="custom",
        policies=PolicySelection(
            scorch="opportunistic_scorch",
            leader="aggressive",
        ),
        weights=ProfileWeightOverrides(
            immediate_points=1.2,
            card_advantage=2.4,
        ),
        pass_overrides=ProfilePassOverrides(
            safe_lead_margin=9,
        ),
    )

    profile = compose_profile(
        DEFAULT_BASELINE_CONFIG,
        assessment,
        context,
        base_profile=base_profile,
    )

    assert profile.scorch_policy.name == "opportunistic_scorch"
    assert profile.leader_policy.name == "aggressive"
    assert profile.pass_lead_margin == 9
    assert profile.weights.immediate_points > DEFAULT_BASELINE_CONFIG.weights.immediate_points
