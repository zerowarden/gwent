"""Ordered proposal backends and method-independent reuse, ranking, and accounting.

Backends receive only numeric settings and fitness. Evaluation and persistence
belong to their caller; no optimizer runs games or reads study files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from math import fsum
from random import Random
from typing import Protocol, final

from gwent_evaluation.models import SpecError
from gwent_evaluation.tuning.models import OptimizerMethod, OptimizerSpec
from gwent_evaluation.tuning.objective import TrialEvaluation, TrialIdentity
from gwent_evaluation.tuning.parameters import finite_float


@dataclass(frozen=True, slots=True)
class Proposal:
    index: int
    coordinates: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ProposalFitness:
    proposal: Proposal
    fitness: float


class OptimizerStopReason(StrEnum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    FLAT_OBJECTIVE = "flat_objective"
    NUMERICAL_LIMIT = "numerical_limit"
    BACKEND_FAILURE = "backend_failure"


@dataclass(frozen=True, slots=True)
class OptimizerStop:
    reason: OptimizerStopReason
    completed_proposals: int
    backend_reasons: tuple[str, ...] = ()
    detail: str | None = None


def validate_population(
    pending: tuple[Proposal, ...], results: tuple[ProposalFitness, ...]
) -> tuple[float, ...]:
    """Validate the entire ordered batch before a backend changes any state."""
    if not pending or tuple(item.proposal for item in results) != pending:
        raise SpecError("Tell requires the complete pending batch in its original order.")
    return tuple(finite_float(item.fitness, context="optimizer fitness") for item in results)


class ProposalOptimizer(Protocol):
    @property
    def stop(self) -> OptimizerStop | None: ...

    @property
    def stop_reason(self) -> OptimizerStopReason | None: ...

    def ask(self) -> tuple[Proposal, ...]: ...

    def tell(self, results: tuple[ProposalFitness, ...]) -> None: ...


@final
class RandomSearch:
    """Protocol 1: private Python Random(seed), row-major random() draws.

    Coordinates are uniform in [0, 1). Repeated asks return the pending batch
    without drawing again. Only a complete ordered tell advances the backend.
    Flat fitness does not end random search before its declared proposal budget.
    """

    def __init__(self, settings: OptimizerSpec, *, dimensions: int) -> None:
        if settings.method is not OptimizerMethod.RANDOM:
            raise SpecError("Random search requires random optimizer settings.")
        if type(dimensions) is not int or dimensions <= 0:
            raise SpecError("Optimizer dimensions must be a positive integer.")
        self._settings = settings
        self._dimensions = dimensions
        self._random = Random(settings.seed)
        self._completed = 0
        self._pending: tuple[Proposal, ...] = ()

    @property
    def stop(self) -> OptimizerStop | None:
        if self._completed == self._settings.proposal_budget:
            return OptimizerStop(OptimizerStopReason.BUDGET_EXHAUSTED, self._completed)
        return None

    @property
    def stop_reason(self) -> OptimizerStopReason | None:
        return None if self.stop is None else self.stop.reason

    def ask(self) -> tuple[Proposal, ...]:
        if self._pending or self.stop_reason is not None:
            return self._pending
        self._pending = tuple(
            Proposal(
                self._completed + offset,
                tuple(self._random.random() for _ in range(self._dimensions)),
            )
            for offset in range(self._settings.batch_size)
        )
        return self._pending

    def tell(self, results: tuple[ProposalFitness, ...]) -> None:
        _ = validate_population(self._pending, results)
        self._completed += len(results)
        self._pending = ()


@dataclass(frozen=True, slots=True)
class CachedEvaluation:
    trial: TrialEvaluation
    cache_hit: bool


class EvaluationCache:
    """In-memory reuse of verified outcomes, keyed by complete trial identity.

    The caller obtains a current candidate_evaluation_identity before each
    lookup and supplies the verified objective adapter on a miss. This is not a
    persistent cache or a substitute for record verification during recovery.
    """

    def __init__(self) -> None:
        self._trials: dict[TrialIdentity, TrialEvaluation] = {}

    def evaluate(
        self, identity: TrialIdentity, evaluate: Callable[[], TrialEvaluation]
    ) -> CachedEvaluation:
        cached = self._trials.get(identity)
        if cached is not None:
            return CachedEvaluation(replace(cached, fresh_matches=0), cache_hit=True)
        trial = evaluate()
        if trial.identity != identity:
            raise SpecError("Objective result does not match the requested evaluation identity.")
        _ = trial.require_eligible_score()
        self._trials[identity] = trial
        return CachedEvaluation(trial, cache_hit=False)


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    coordinates: tuple[float, ...]
    evaluation: CachedEvaluation


@dataclass(frozen=True, slots=True)
class SearchCounts:
    proposals: int
    distinct_configurations: int
    cache_hits: int
    fresh_matches: int


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    ranked_candidates: tuple[ScoredCandidate, ...]
    incumbent_retained: bool
    optimization_score_gain: float
    counts: SearchCounts

    @property
    def best(self) -> ScoredCandidate:
        """Best evaluated configuration, without any claim about unsampled points."""
        return self.ranked_candidates[0]


def summarize_search(
    incumbent: ScoredCandidate, proposals: tuple[ScoredCandidate, ...]
) -> SearchOutcome:
    """Selection v1: score, incumbent, normalized Euclidean distance, digest.

    Counts include incumbent work except for proposal slots. Ranking deduplicates
    configurations; accounting retains every slot, including duplicate proposals.
    Fitness passed to a backend is never modified to encode this tie rule.
    """
    reference = incumbent.evaluation.trial
    incumbent_score = reference.require_eligible_score()
    dimensions = len(incumbent.coordinates)
    if not dimensions:
        raise SpecError("Selection requires normalized coordinates.")
    ranked: list[tuple[tuple[float, bool, float, str], ScoredCandidate]] = []
    all_candidates = (incumbent, *proposals)
    for candidate in all_candidates:
        trial = candidate.evaluation.trial
        score = trial.require_eligible_score()
        if (trial.study_digest, trial.benchmark_identity) != (
            reference.study_digest,
            reference.benchmark_identity,
        ):
            raise SpecError("Selection cannot combine different studies or benchmarks.")
        if type(candidate.coordinates) is not tuple or len(candidate.coordinates) != dimensions:
            raise SpecError("Selection coordinate dimensions differ.")
        for value in candidate.coordinates:
            if not 0 <= finite_float(value, context="selection coordinate") <= 1:
                raise SpecError("Selection coordinates must lie in [0, 1].")
        distance = fsum(
            (value - origin) ** 2
            for value, origin in zip(candidate.coordinates, incumbent.coordinates, strict=True)
        )
        ranked.append(
            (
                (
                    -score,
                    trial.configuration_digest != reference.configuration_digest,
                    distance,
                    trial.configuration_digest,
                ),
                candidate,
            )
        )
    distinct: dict[str, ScoredCandidate] = {}
    for _, candidate in sorted(ranked, key=lambda item: item[0]):
        digest = candidate.evaluation.trial.configuration_digest
        previous = distinct.get(digest)
        if previous is not None:
            if (previous.evaluation.trial.identity, previous.evaluation.trial.score) != (
                candidate.evaluation.trial.identity,
                candidate.evaluation.trial.score,
            ):
                raise SpecError("Repeated configurations have conflicting evaluation evidence.")
        else:
            distinct[digest] = candidate
    ordered = tuple(distinct.values())
    best = ordered[0].evaluation.trial
    return SearchOutcome(
        ranked_candidates=ordered,
        incumbent_retained=best.configuration_digest == reference.configuration_digest,
        optimization_score_gain=best.require_eligible_score() - incumbent_score,
        counts=SearchCounts(
            proposals=len(proposals),
            distinct_configurations=len(distinct),
            cache_hits=sum(item.evaluation.cache_hit for item in all_candidates),
            fresh_matches=sum(item.evaluation.trial.fresh_matches for item in all_candidates),
        ),
    )
