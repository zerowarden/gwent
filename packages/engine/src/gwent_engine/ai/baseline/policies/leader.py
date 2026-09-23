from __future__ import annotations

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.features import preserved_leader_value
from gwent_engine.ai.baseline.policies.protocol import LeaderPolicy, PolicyProfile
from gwent_engine.ai.policy import (
    AGGRESSIVE_LEADER_POLICY_ID,
    CONSERVATIVE_LEADER_POLICY_ID,
    DEFAULT_FEATURE_POLICY,
    DEFAULT_LEADER_POLICY_TUNING,
    LEGACY_PRESERVE_LEADER_POLICY_ID,
)

type LeaderPolicyComponent = tuple[str, float]


def leader_policy_components(
    *,
    policy_name: str,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: PolicyProfile,
) -> tuple[LeaderPolicyComponent, ...]:
    resource_bias = profile.resource_bias
    reserve_cost = profile.weights.leader_value * preserved_leader_value(
        leader_used=assessment.viewer.leader_used,
        reserve_value=DEFAULT_FEATURE_POLICY.preserved_leader_value,
    )
    if policy_name in {
        CONSERVATIVE_LEADER_POLICY_ID,
        LEGACY_PRESERVE_LEADER_POLICY_ID,
    }:
        return (
            (
                "leader_reserve_cost",
                -(reserve_cost * max(resource_bias.preserve_resources, 1.0)),
            ),
        )
    immediate_need = 0.0
    if assessment.score_gap < 0:
        immediate_need = (
            abs(assessment.score_gap)
            * profile.weights.immediate_points
            * DEFAULT_LEADER_POLICY_TUNING.immediate_need_gap_multiplier
            * max(1.0, resource_bias.minimum_commitment)
        )
    round_pressure = 0.0
    if context.prioritize_immediate_points:
        round_pressure += profile.weights.exact_finish_bonus
    if assessment.is_final_round:
        round_pressure += profile.weights.exact_finish_bonus
    elif assessment.is_elimination_round:
        round_pressure += (
            profile.weights.exact_finish_bonus
            * DEFAULT_LEADER_POLICY_TUNING.elimination_round_pressure_multiplier
        )
    return (
        ("leader_immediate_need", immediate_need),
        ("leader_round_pressure", round_pressure),
        (
            "leader_reserve_cost",
            -(reserve_cost / max(resource_bias.preserve_resources, 1.0)),
        ),
    )


CONSERVATIVE_LEADER_POLICY = LeaderPolicy(name=CONSERVATIVE_LEADER_POLICY_ID)
AGGRESSIVE_LEADER_POLICY = LeaderPolicy(name=AGGRESSIVE_LEADER_POLICY_ID)
