from __future__ import annotations

from dataclasses import dataclass, field

from gwent_engine.ai.policy import SearchConfig
from gwent_engine.ai.search.types import (
    SearchCandidate,
    SearchCandidateEvaluation,
    SearchLine,
)
from gwent_engine.core.actions import GameAction


@dataclass(frozen=True, slots=True)
class SearchDecisionComparison:
    chosen_action: GameAction
    runner_up_action: GameAction | None
    chosen_value: float | None
    runner_up_value: float | None
    value_margin: float | None
    chosen_reason: str | None
    runner_up_reason: str | None


@dataclass(frozen=True, slots=True)
class SearchDecisionExplanation:
    """Structured explanation scaffold for search decisions.

    Phase 4 exposes both the searched root candidates and the evaluated
    searched lines so match review and debugging surfaces can explain not just
    which action won, but how the search ranked the explored alternatives.
    """

    chosen_action: GameAction
    profile_id: str
    config: SearchConfig
    used_fallback_policy: bool
    candidates: tuple[SearchCandidate, ...] = ()
    evaluations: tuple[SearchCandidateEvaluation, ...] = ()
    principal_line: SearchLine | None = None
    comparison: SearchDecisionComparison | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
