"""Score arithmetic, stratification, and block-level uncertainty.

Metrics operate on `ScoredCase` facts rather than persisted records so the
arithmetic stays pure and hand-authorable; `gwent_evaluation.reporting` adapts
scheduled matches and match results into those facts.

The primary comparison treats each complete balanced block as one independent
sampling unit. Treating individual matches (or decisions) as independent would
understate uncertainty, because legs of one block share their deal and seed.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import fsum
from typing import Final

SCORE_WIN: Final = 1.0
SCORE_DRAW: Final = 0.5
SCORE_LOSS: Final = 0.0

DEFAULT_CONFIDENCE_LEVEL: Final = 0.95
DEFAULT_RESAMPLES: Final = 2000

#: Percentile bootstrap over fewer independent blocks than this is too coarse
#: to present as an inferential interval; reports stay descriptive instead.
MINIMUM_BOOTSTRAP_BLOCKS: Final = 8
DEFAULT_BOOTSTRAP_SEED: Final = 0

DEFAULT_STRATA_DIMENSIONS: Final = (
    "opponent",
    "candidate_seat",
    "requested_starting_player",
    "candidate_deck",
    "opponent_deck",
)


class CaseStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"


class IntervalMethod(StrEnum):
    BLOCK_BOOTSTRAP = "block_bootstrap"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    """Resampling parameters for block-level percentile intervals."""

    resamples: int = DEFAULT_RESAMPLES
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
    minimum_blocks: int = MINIMUM_BOOTSTRAP_BLOCKS
    seed: int = DEFAULT_BOOTSTRAP_SEED

    def __post_init__(self) -> None:
        if self.resamples <= 0:
            raise ValueError("Bootstrap resamples must be positive.")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("Bootstrap confidence level must be between 0 and 1.")
        if self.minimum_blocks < 2:
            raise ValueError("Bootstrap minimum block count must be at least 2.")


DEFAULT_BOOTSTRAP: Final = BootstrapConfig()


@dataclass(frozen=True, slots=True)
class ScoredCase:
    """One scheduled match reduced to its scoring and stratification facts.

    `score` is the candidate score and is present exactly when `status` is
    `COMPLETED`; failures and missing results never enter a denominator.
    """

    case_id: str
    block_id: str
    status: CaseStatus
    score: float | None
    strata: Mapping[str, str]

    @property
    def completed(self) -> bool:
        return self.status is CaseStatus.COMPLETED


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    wins: int
    draws: int
    losses: int
    completed: int
    score: float | None


@dataclass(frozen=True, slots=True)
class ScoreInterval:
    """A percentile interval over resampled block means, or its absence."""

    method: IntervalMethod
    confidence_level: float
    lower: float | None
    upper: float | None
    blocks: int
    resamples: int | None


@dataclass(frozen=True, slots=True)
class StratumMetrics:
    dimension: str
    value: str
    summary: ScoreSummary
    interval: ScoreInterval


@dataclass(frozen=True, slots=True)
class BlockOutcome:
    block_id: str
    cases: tuple[ScoredCase, ...]

    @property
    def planned(self) -> int:
        return len(self.cases)

    @property
    def completed(self) -> int:
        return sum(case.completed for case in self.cases)

    @property
    def complete(self) -> bool:
        return self.planned > 0 and self.completed == self.planned

    @property
    def mean_score(self) -> float | None:
        scores = tuple(_require_score(case) for case in self.cases if case.completed)
        if not scores:
            return None
        return fsum(scores) / len(scores)


@dataclass(frozen=True, slots=True)
class RunMetrics:
    planned: int
    executed: int
    completed: int
    failed: int
    missing: int
    candidate: ScoreSummary
    balanced_score: float | None
    complete_blocks: int
    total_blocks: int
    interval: ScoreInterval
    strata: tuple[StratumMetrics, ...]
    valid: bool
    validity_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlockDifference:
    block_id: str
    reference_score: float
    candidate_score: float
    difference: float


@dataclass(frozen=True, slots=True)
class PairedComparison:
    blocks: tuple[BlockDifference, ...]
    reference_score: float | None
    candidate_score: float | None
    mean_difference: float | None
    interval: ScoreInterval


def summarize_scores(scores: Sequence[float]) -> ScoreSummary:
    wins = sum(score == SCORE_WIN for score in scores)
    draws = sum(score == SCORE_DRAW for score in scores)
    losses = sum(score == SCORE_LOSS for score in scores)
    for score in scores:
        _ = _require_score_value(score)
    return ScoreSummary(
        wins=wins,
        draws=draws,
        losses=losses,
        completed=len(scores),
        score=(fsum(scores) / len(scores) if scores else None),
    )


def block_outcomes(cases: Sequence[ScoredCase]) -> tuple[BlockOutcome, ...]:
    grouped: dict[str, list[ScoredCase]] = {}
    for case in cases:
        grouped.setdefault(case.block_id, []).append(case)
    return tuple(
        BlockOutcome(block_id=block_id, cases=tuple(grouped[block_id]))
        for block_id in sorted(grouped)
    )


def compute_run_metrics(
    cases: Sequence[ScoredCase],
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
    dimensions: Sequence[str] = DEFAULT_STRATA_DIMENSIONS,
) -> RunMetrics:
    """Compute descriptive scores plus a block-level interval for one candidate."""

    blocks = block_outcomes(cases)
    completed_cases = tuple(case for case in cases if case.completed)
    failed = sum(case.status is CaseStatus.FAILED for case in cases)
    missing = sum(case.status is CaseStatus.MISSING for case in cases)
    complete_blocks = tuple(block for block in blocks if block.complete)
    balanced_units = tuple(
        score for block in complete_blocks if (score := block.mean_score) is not None
    )
    validity_reasons = _validity_reasons(planned=len(cases), failed=failed, missing=missing)
    return RunMetrics(
        planned=len(cases),
        executed=len(cases) - missing,
        completed=len(completed_cases),
        failed=failed,
        missing=missing,
        candidate=summarize_scores(tuple(_require_score(case) for case in completed_cases)),
        balanced_score=_mean(balanced_units),
        complete_blocks=len(complete_blocks),
        total_blocks=len(blocks),
        interval=bootstrap_interval(balanced_units, config=bootstrap),
        strata=_stratum_metrics(
            cases,
            complete_blocks=complete_blocks,
            dimensions=dimensions,
            bootstrap=bootstrap,
        ),
        valid=not validity_reasons,
        validity_reasons=validity_reasons,
    )


def bootstrap_interval(
    units: Sequence[float],
    *,
    config: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> ScoreInterval:
    """Percentile bootstrap over independent block means."""

    if len(units) < config.minimum_blocks:
        return insufficient_sample_interval(blocks=len(units), config=config)
    rng = random.Random(config.seed)
    size = len(units)
    resampled = sorted(fsum(rng.choices(units, k=size)) / size for _ in range(config.resamples))
    alpha = (1.0 - config.confidence_level) / 2.0
    return ScoreInterval(
        method=IntervalMethod.BLOCK_BOOTSTRAP,
        confidence_level=config.confidence_level,
        lower=_percentile(resampled, alpha),
        upper=_percentile(resampled, 1.0 - alpha),
        blocks=size,
        resamples=config.resamples,
    )


def compare_block_scores(
    reference_cases: Sequence[ScoredCase],
    candidate_cases: Sequence[ScoredCase],
    *,
    bootstrap: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> PairedComparison:
    """Compare two candidates over blocks complete in both runs.

    Only complete blocks are paired, so blocks that did not finish under either
    candidate cannot silently enter the comparison.
    """

    reference = _complete_block_means(reference_cases)
    candidate = _complete_block_means(candidate_cases)
    blocks = tuple(
        BlockDifference(
            block_id=block_id,
            reference_score=reference[block_id],
            candidate_score=candidate[block_id],
            difference=candidate[block_id] - reference[block_id],
        )
        for block_id in sorted(set(reference) & set(candidate))
    )
    reference_score = _mean(tuple(block.reference_score for block in blocks))
    candidate_score = _mean(tuple(block.candidate_score for block in blocks))
    differences = tuple(block.difference for block in blocks)
    return PairedComparison(
        blocks=blocks,
        reference_score=reference_score,
        candidate_score=candidate_score,
        mean_difference=_mean(differences),
        interval=bootstrap_interval(differences, config=bootstrap),
    )


def insufficient_sample_interval(
    *,
    blocks: int,
    config: BootstrapConfig = DEFAULT_BOOTSTRAP,
) -> ScoreInterval:
    """An explicit non-inferential interval for incomplete or explicitly gated runs."""

    return ScoreInterval(
        method=IntervalMethod.INSUFFICIENT_SAMPLE,
        confidence_level=config.confidence_level,
        lower=None,
        upper=None,
        blocks=blocks,
        resamples=None,
    )


def _stratum_metrics(
    cases: Sequence[ScoredCase],
    *,
    complete_blocks: Sequence[BlockOutcome],
    dimensions: Sequence[str],
    bootstrap: BootstrapConfig,
) -> tuple[StratumMetrics, ...]:
    metrics: list[StratumMetrics] = []
    for dimension in dimensions:
        values = sorted({case.strata[dimension] for case in cases if dimension in case.strata})
        for value in values:
            selected = tuple(case for case in cases if case.strata.get(dimension) == value)
            units = _stratum_units(complete_blocks, dimension=dimension, value=value)
            metrics.append(
                StratumMetrics(
                    dimension=dimension,
                    value=value,
                    summary=summarize_scores(
                        tuple(_require_score(case) for case in selected if case.completed)
                    ),
                    interval=bootstrap_interval(units, config=bootstrap),
                )
            )
    return tuple(metrics)


def _stratum_units(
    blocks: Sequence[BlockOutcome],
    *,
    dimension: str,
    value: str,
) -> tuple[float, ...]:
    units: list[float] = []
    for block in blocks:
        scores = tuple(
            _require_score(case)
            for case in block.cases
            if case.completed and case.strata.get(dimension) == value
        )
        if scores:
            units.append(fsum(scores) / len(scores))
    return tuple(units)


def _validity_reasons(*, planned: int, failed: int, missing: int) -> tuple[str, ...]:
    reasons: list[str] = []
    if planned == 0:
        reasons.append("The run contains no scheduled matches.")
    if missing:
        reasons.append(f"{missing} scheduled match(es) have no persisted result.")
    if failed:
        reasons.append(f"{failed} scheduled match(es) did not complete.")
    return tuple(reasons)


def _complete_block_means(cases: Sequence[ScoredCase]) -> dict[str, float]:
    return {
        block.block_id: block.mean_score
        for block in block_outcomes(cases)
        if block.complete and block.mean_score is not None
    }


def _require_score(case: ScoredCase) -> float:
    score = case.score
    if not case.completed or score is None:
        raise ValueError(f"Case {case.case_id!r} has no candidate score.")
    return _require_score_value(score)


def _require_score_value(score: float | None) -> float:
    if score is None or score not in {SCORE_WIN, SCORE_DRAW, SCORE_LOSS}:
        raise ValueError(f"Candidate score must be 1, 0.5, or 0, found {score!r}.")
    return score


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return fsum(values) / len(values)


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    index = min(int(quantile * len(sorted_values)), len(sorted_values) - 1)
    return sorted_values[index]
