from __future__ import annotations

from dataclasses import dataclass
from typing import override

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.policies.protocol import PolicyProfile, ScorchPolicy
from gwent_engine.ai.baseline.projection import ScorchImpact
from gwent_engine.ai.policy import OPPORTUNISTIC_SCORCH_POLICY_ID, RESERVE_SCORCH_POLICY_ID
from gwent_engine.core.actions import PlayCardAction


@dataclass(frozen=True, slots=True)
class OpportunisticScorchPolicy(ScorchPolicy):
    """Spend Scorch when the current position rewards immediate swing.

    This policy exists for tempo-focused situations where holding Scorch is
    less valuable than taking a live tactical gain right now.
    """

    name: str = OPPORTUNISTIC_SCORCH_POLICY_ID

    @override
    def evaluate(
        self,
        *,
        action: PlayCardAction,
        assessment: DecisionAssessment,
        context: DecisionContext,
        scorch_impact: ScorchImpact,
        profile: PolicyProfile,
    ) -> float:
        del action, assessment
        if not scorch_impact.has_live_targets or scorch_impact.net_swing <= 0:
            return profile.action_bonus.invalid_target_penalty
        multiplier = (
            profile.resource_bias.minimum_commitment if context.prioritize_immediate_points else 1.0
        )
        return profile.action_bonus.scorch_bonus * max(1.0, multiplier)


@dataclass(frozen=True, slots=True)
class ReserveScorchPolicy(ScorchPolicy):
    """Discount Scorch usage to preserve a stronger answer for later.

    This policy exists for resource-preserving profiles that would rather keep
    Scorch in reserve than spend it on a marginal current-board exchange.
    """

    name: str = RESERVE_SCORCH_POLICY_ID

    @override
    def evaluate(
        self,
        *,
        action: PlayCardAction,
        assessment: DecisionAssessment,
        context: DecisionContext,
        scorch_impact: ScorchImpact,
        profile: PolicyProfile,
    ) -> float:
        del action, assessment, context
        if not scorch_impact.has_live_targets or scorch_impact.net_swing <= 0:
            return profile.action_bonus.invalid_target_penalty
        return profile.action_bonus.scorch_bonus / max(
            profile.resource_bias.preserve_resources,
            1.0,
        )


OPPORTUNISTIC_SCORCH_POLICY = OpportunisticScorchPolicy()
RESERVE_SCORCH_POLICY = ReserveScorchPolicy()
