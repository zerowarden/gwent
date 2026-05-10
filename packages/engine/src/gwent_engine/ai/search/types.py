from __future__ import annotations

from dataclasses import dataclass, field

from gwent_engine.core.actions import GameAction


@dataclass(frozen=True, slots=True)
class SearchTraceFact:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class SearchValueTerm:
    name: str
    value: float
    formula: str | None = None
    details: tuple[SearchTraceFact, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchReplyExplanation:
    kind: str
    reason: str
    actions: tuple[GameAction, ...] = ()
    value_adjustment: float = 0.0
    components: tuple[SearchValueTerm, ...] = ()
    notes: tuple[SearchTraceFact, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchLineExplanation:
    self_turn_facts: tuple[SearchTraceFact, ...] = ()
    leaf_facts: tuple[SearchTraceFact, ...] = ()
    leaf_terms: tuple[SearchValueTerm, ...] = ()
    reply: SearchReplyExplanation | None = None
    root_adjustments: tuple[SearchValueTerm, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """Search candidate plus ordering hint."""

    action: GameAction
    ordering_score: float = 0.0
    reason: str = "unordered"


@dataclass(frozen=True, slots=True)
class SearchLine:
    """Fully evaluated line for the current search depth."""

    actions: tuple[GameAction, ...]
    reply_actions: tuple[GameAction, ...] = ()
    value: float = 0.0
    explanation: SearchLineExplanation = SearchLineExplanation()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchCandidateEvaluation:
    """Root candidate plus the fully evaluated searched line."""

    action: GameAction
    root_rank: int
    ordering_score: float
    reason: str
    line: SearchLine
    selected: bool = False


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Search engine result at the public bot boundary."""

    chosen_action: GameAction
    candidates: tuple[SearchCandidate, ...] = ()
    evaluations: tuple[SearchCandidateEvaluation, ...] = ()
    principal_line: SearchLine | None = None
    used_fallback_policy: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)
