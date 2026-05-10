from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.projection import ScorchImpact
from gwent_engine.ai.policy import ActionBonusConfig, EvaluationWeights, PolicyResourceBias
from gwent_engine.core.actions import PlayCardAction


class PolicyProfile(Protocol):
    """Minimal resolved-profile surface needed by policy evaluators."""

    @property
    def weights(self) -> EvaluationWeights: ...

    @property
    def action_bonus(self) -> ActionBonusConfig: ...

    @property
    def resource_bias(self) -> PolicyResourceBias: ...


class ScorchPolicy(ABC):
    """Policy for when Scorch is worth spending now.

    This is separate because Scorch timing is highly contextual: a profile may
    spend it opportunistically for immediate swing or hold it to preserve a
    stronger tactical answer later.
    """

    name: str

    @abstractmethod
    def evaluate(
        self,
        *,
        action: PlayCardAction,
        assessment: DecisionAssessment,
        context: DecisionContext,
        scorch_impact: ScorchImpact,
        profile: PolicyProfile,
    ) -> float: ...


class LeaderPolicy(ABC):
    """Policy for leader timing.

    Leader abilities are scarce battle resources, so profiles often need a
    separate timing rule that is more conservative or more tempo-oriented than
    ordinary card play.
    """

    name: str

    @abstractmethod
    def evaluate(
        self,
        *,
        assessment: DecisionAssessment,
        context: DecisionContext,
        profile: PolicyProfile,
    ) -> float: ...
