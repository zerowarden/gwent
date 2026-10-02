"""Named Scorch and leader timing policies selected by heuristic profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.features import preserved_leader_value
from gwent_engine.ai.baseline.projection import ScorchImpact
from gwent_engine.ai.policy import (
    AGGRESSIVE_LEADER_POLICY_ID,
    CONSERVATIVE_LEADER_POLICY_ID,
    DEFAULT_FEATURE_POLICY,
    DEFAULT_LEADER_POLICY_TUNING,
    OPPORTUNISTIC_SCORCH_POLICY_ID,
    RESERVE_SCORCH_POLICY_ID,
    ActionBonusConfig,
    EvaluationWeights,
    PolicyResourceBias,
    PolicySelection,
)
from gwent_engine.core.errors import DefinitionLoadError

type LeaderPolicyComponent = tuple[str, float]


class PolicyProfile(Protocol):
    """Minimal resolved-profile surface needed by policy evaluators."""

    @property
    def weights(self) -> EvaluationWeights: ...

    @property
    def action_bonus(self) -> ActionBonusConfig: ...

    @property
    def resource_bias(self) -> PolicyResourceBias: ...


@dataclass(frozen=True, slots=True)
class ScorchPolicy:
    """When Scorch is worth spending now.

    Scorch timing is highly contextual: a profile may spend it opportunistically
    for immediate swing or hold it to preserve a stronger tactical answer later.
    """

    name: str
    evaluate: Callable[[ScorchImpact, DecisionContext, PolicyProfile], float]


def _opportunistic_scorch(
    scorch_impact: ScorchImpact,
    context: DecisionContext,
    profile: PolicyProfile,
) -> float:
    """Spend Scorch when the current position rewards immediate swing."""

    if not scorch_impact.has_live_targets or scorch_impact.net_swing <= 0:
        return profile.action_bonus.invalid_target_penalty
    multiplier = (
        profile.resource_bias.minimum_commitment if context.prioritize_immediate_points else 1.0
    )
    return profile.action_bonus.scorch_bonus * max(1.0, multiplier)


def _reserve_scorch(
    scorch_impact: ScorchImpact,
    context: DecisionContext,
    profile: PolicyProfile,
) -> float:
    """Discount Scorch usage to preserve a stronger answer for later."""

    del context
    if not scorch_impact.has_live_targets or scorch_impact.net_swing <= 0:
        return profile.action_bonus.invalid_target_penalty
    return profile.action_bonus.scorch_bonus / max(
        profile.resource_bias.preserve_resources,
        1.0,
    )


OPPORTUNISTIC_SCORCH_POLICY = ScorchPolicy(OPPORTUNISTIC_SCORCH_POLICY_ID, _opportunistic_scorch)
RESERVE_SCORCH_POLICY = ScorchPolicy(RESERVE_SCORCH_POLICY_ID, _reserve_scorch)

SCORCH_POLICIES: Mapping[str, ScorchPolicy] = MappingProxyType(
    {policy.name: policy for policy in (OPPORTUNISTIC_SCORCH_POLICY, RESERVE_SCORCH_POLICY)}
)
LEADER_POLICY_IDS = frozenset({CONSERVATIVE_LEADER_POLICY_ID, AGGRESSIVE_LEADER_POLICY_ID})


def validate_policy_selection(selection: PolicySelection, *, context: str) -> None:
    for policy_name, known in (
        (selection.scorch, SCORCH_POLICIES),
        (selection.leader, LEADER_POLICY_IDS),
    ):
        if policy_name not in known:
            raise DefinitionLoadError(f"{context} references unknown policy {policy_name!r}.")


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
    if policy_name == CONSERVATIVE_LEADER_POLICY_ID:
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
