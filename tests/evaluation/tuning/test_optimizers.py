"""Seeded proposal protocol and selection over explicit synthetic objectives."""

import random
from dataclasses import replace
from typing import override

import pytest
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import SeededRandom
from gwent_evaluation.metrics import BootstrapConfig, bootstrap_interval
from gwent_evaluation.models import SpecError, TerminationReason
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.tuning import optimizers
from gwent_evaluation.tuning.models import CmaSettings, OptimizerMethod, OptimizerSpec
from gwent_evaluation.tuning.objective import TrialEvaluation, TrialResultReference, TrialStatus
from gwent_evaluation.tuning.optimizers import (
    CachedEvaluation,
    EvaluationCache,
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
    ProposalOptimizer,
    RandomSearch,
    ScoredCandidate,
    summarize_search,
)


def settings(*, seed: int = 0, budget: int = 4, batch: int = 2) -> OptimizerSpec:
    return OptimizerSpec(OptimizerMethod.RANDOM, seed, budget, batch, None, None)


def collect(backend: ProposalOptimizer) -> tuple[Proposal, ...]:
    proposals: list[Proposal] = []
    while batch := backend.ask():
        proposals.extend(batch)
        backend.tell(tuple(ProposalFitness(proposal, 0.5) for proposal in batch))
    return tuple(proposals)


def synthetic_trial(
    coordinates: tuple[float, ...], score: float, *, digest: str | None = None
) -> TrialEvaluation:
    """Hand-authored outcomes for a numeric test objective; no scientific game evidence."""
    configuration = digest or canonical_digest(coordinates)
    identity = canonical_digest({"benchmark": "synthetic", "configuration": configuration})
    return TrialEvaluation(
        schema_version=1,
        study_digest="synthetic-study",
        configuration_digest=configuration,
        candidate_digest=canonical_digest({"configuration": configuration}),
        suite_id="synthetic-optimization",
        suite_digest="synthetic-suite",
        benchmark_identity="synthetic-benchmark",
        execution_identity=identity,
        run_root="synthetic-results",
        results=tuple(
            TrialResultReference(
                str(index), f"{index}.json", "fixture", "fixture", TerminationReason.COMPLETED
            )
            for index in range(4)
        ),
        planned=4,
        completed=4,
        failed=0,
        missing=0,
        score=score,
        valid_for_comparison=True,
        optimization_evidence=True,
        status=TrialStatus.ELIGIBLE,
        reasons=(),
        fresh_matches=4,
    )


def scored(
    coordinates: tuple[float, ...], score: float, *, digest: str | None = None
) -> ScoredCandidate:
    return ScoredCandidate(
        coordinates, CachedEvaluation(synthetic_trial(coordinates, score, digest=digest), False)
    )


def test_seeded_protocol_has_a_fixed_ordered_sequence_and_budget_stop() -> None:
    backend: ProposalOptimizer = RandomSearch(settings(), dimensions=2)
    first = backend.ask()
    assert backend.ask() == first
    assert backend.stop_reason is None
    backend.tell(tuple(ProposalFitness(proposal, 0.25) for proposal in first))
    proposals = (*first, *collect(backend))
    assert proposals == (
        Proposal(0, (0.8444218515250481, 0.7579544029403025)),
        Proposal(1, (0.420571580830845, 0.25891675029296335)),
        Proposal(2, (0.5112747213686085, 0.4049341374504143)),
        Proposal(3, (0.7837985890347726, 0.30331272607892745)),
    )
    assert backend.stop_reason is OptimizerStopReason.BUDGET_EXHAUSTED
    assert backend.ask() == ()
    assert collect(RandomSearch(settings(), dimensions=2)) == proposals
    assert collect(RandomSearch(settings(batch=1), dimensions=2)) == proposals


def test_global_game_and_metric_randomness_do_not_change_proposals() -> None:
    expected = collect(RandomSearch(settings(budget=6), dimensions=3))
    global_state = random.getstate()
    first = RandomSearch(settings(budget=6), dimensions=3)
    second = RandomSearch(settings(budget=6), dimensions=3)
    assert random.getstate() == global_state
    collected: list[Proposal] = []
    game_random = SeededRandom(91)
    cards = [CardInstanceId("a"), CardInstanceId("b"), CardInstanceId("c")]
    try:
        while batch := first.ask():
            before = random.getstate()
            assert second.ask() == batch
            assert random.getstate() == before
            for _ in range(20):
                _ = random.random()
                game_random.shuffle(cards)
                _ = game_random.choice(tuple(cards))
            _ = bootstrap_interval(
                (0.0, 0.5, 1.0), config=BootstrapConfig(resamples=10, minimum_blocks=2)
            )
            collected.extend(batch)
            values = tuple(ProposalFitness(proposal, 0.5) for proposal in batch)
            first.tell(values)
            second.tell(values)
    finally:
        random.setstate(global_state)
    assert tuple(collected) == expected


@pytest.mark.parametrize(
    "invalid", ["empty", "partial", "reversed", "repeated", "changed", "nan", "infinity", "boolean"]
)
def test_invalid_tell_preserves_the_pending_population(invalid: str) -> None:
    backend = RandomSearch(settings(), dimensions=2)
    batch = backend.ask()
    valid = tuple(ProposalFitness(proposal, 0.5) for proposal in batch)
    alternatives = {
        "empty": (),
        "partial": valid[:1],
        "reversed": tuple(reversed(valid)),
        "repeated": (valid[0], valid[0]),
        "changed": (
            replace(valid[0], proposal=replace(batch[0], coordinates=(0.1, 0.1))),
            valid[1],
        ),
        "nan": (replace(valid[0], fitness=float("nan")), valid[1]),
        "infinity": (replace(valid[0], fitness=float("inf")), valid[1]),
        "boolean": (replace(valid[0], fitness=True), valid[1]),
    }
    with pytest.raises(SpecError):
        backend.tell(alternatives[invalid])
    assert backend.ask() == batch
    backend.tell(valid)
    assert collect(backend) == collect(RandomSearch(settings(), dimensions=2))[2:]
    with pytest.raises(SpecError, match="pending batch"):
        backend.tell(valid)


@pytest.mark.parametrize("dimensions", [0, -1, True])
def test_invalid_dimensions_are_rejected(dimensions: int) -> None:
    with pytest.raises(SpecError, match="dimensions"):
        _ = RandomSearch(settings(), dimensions=dimensions)


def test_wrong_method_and_tell_without_ask_are_rejected() -> None:
    cma = OptimizerSpec(OptimizerMethod.CMA_ES, 0, 4, 2, 2, 0.2, cma=CmaSettings())
    with pytest.raises(SpecError, match="random optimizer"):
        _ = RandomSearch(cma, dimensions=2)
    with pytest.raises(SpecError, match="pending batch"):
        RandomSearch(settings(), dimensions=2).tell(())


def test_selection_uses_score_then_incumbent_then_distance_then_digest() -> None:
    incumbent = scored((0.5, 0.5), 0.4)
    far = scored((0.0, 0.0), 0.8, digest="sha256:" + "0" * 64)
    near = scored((0.5, 0.75), 0.8, digest="sha256:" + "f" * 64)
    near_tie = scored((0.5, 0.25), 0.8, digest="sha256:" + "a" * 64)
    higher = scored((1.0, 1.0), 0.9)
    proposals = (far, near, near_tie, higher)
    result = summarize_search(incumbent, proposals)
    assert result.ranked_candidates == (higher, near_tie, near, far, incumbent)
    assert result.best is higher
    assert not result.incumbent_retained
    assert result.optimization_score_gain == 0.5
    assert summarize_search(incumbent, tuple(reversed(proposals))) == result

    tied_incumbent = scored((0.5, 0.5), 0.8)
    tied = summarize_search(tied_incumbent, (far, near, near_tie))
    assert tied.best is tied_incumbent
    assert tied.incumbent_retained and tied.optimization_score_gain == 0


@pytest.mark.parametrize(
    "incumbent_coordinate,distinct,hits,fresh", [(0.0, 2, 5, 8), (0.5, 1, 6, 4)]
)
def test_duplicate_proposals_consume_slots_and_reuse_complete_evaluation_identity(
    monkeypatch: pytest.MonkeyPatch,
    incumbent_coordinate: float,
    distinct: int,
    hits: int,
    fresh: int,
) -> None:
    class ConstantRandom(random.Random):
        @override
        def random(self) -> float:
            return 0.5

    monkeypatch.setattr(optimizers, "Random", ConstantRandom)
    backend = RandomSearch(settings(budget=6), dimensions=1)
    cache = EvaluationCache()
    calls = 0

    def evaluate(coordinates: tuple[float, ...]) -> ScoredCandidate:
        trial = synthetic_trial(coordinates, 0.5)

        def objective() -> TrialEvaluation:
            nonlocal calls
            calls += 1
            return trial

        return ScoredCandidate(coordinates, cache.evaluate(trial.identity, objective))

    incumbent = evaluate((incumbent_coordinate,))
    evaluated: list[ScoredCandidate] = []
    indices: list[int] = []
    while batch := backend.ask():
        values: list[ProposalFitness] = []
        for proposal in batch:
            result = evaluate(proposal.coordinates)
            evaluated.append(result)
            indices.append(proposal.index)
            fitness = result.evaluation.trial.fitness
            assert fitness is not None
            assert fitness == 0.5
            values.append(ProposalFitness(proposal, fitness))
        backend.tell(tuple(values))
    summary = summarize_search(incumbent, tuple(evaluated))
    assert indices == list(range(6))
    assert calls == distinct
    assert summary.counts.proposals == 6
    assert summary.counts.distinct_configurations == distinct
    assert summary.counts.cache_hits == hits
    assert summary.counts.fresh_matches == fresh
    assert summary.incumbent_retained and summary.optimization_score_gain == 0
    assert backend.stop_reason is OptimizerStopReason.BUDGET_EXHAUSTED


def test_small_known_objective_returns_best_evaluated_point() -> None:
    def objective(coordinates: tuple[float, ...]) -> ScoredCandidate:
        return scored(coordinates, 1.0 - (coordinates[0] - 0.25) ** 2)

    backend = RandomSearch(settings(), dimensions=1)
    incumbent = objective((0.0,))
    evaluated: list[ScoredCandidate] = []
    while batch := backend.ask():
        values: list[ProposalFitness] = []
        for proposal in batch:
            result = objective(proposal.coordinates)
            evaluated.append(result)
            fitness = result.evaluation.trial.fitness
            assert fitness is not None
            values.append(ProposalFitness(proposal, fitness))
        backend.tell(tuple(values))
    result = summarize_search(incumbent, tuple(evaluated))
    assert result.best is evaluated[3]
    assert result.best.coordinates == (0.25891675029296335,)
    assert result.best.evaluation.trial.score != 1.0
    assert result.counts.proposals == 4
    assert result.counts.distinct_configurations == 5
    assert result.counts.fresh_matches == 20


@pytest.mark.parametrize("field", ["study_digest", "configuration_digest", "execution_identity"])
def test_cache_requires_every_identity_component(field: str) -> None:
    cache = EvaluationCache()
    first = synthetic_trial((0.5,), 0.5)
    assert not cache.evaluate(first.identity, lambda: first).cache_hit
    changed = replace(first, **{field: "changed"})
    with pytest.raises(SpecError, match="evaluation identity"):
        _ = cache.evaluate(changed.identity, lambda: first)
    fresh = cache.evaluate(changed.identity, lambda: changed)
    assert not fresh.cache_hit
    reused = cache.evaluate(first.identity, lambda: changed)
    assert reused.cache_hit and reused.trial.fresh_matches == 0
    assert reused.trial.score == first.score


@pytest.mark.parametrize(
    "change",
    [
        {"status": TrialStatus.DIAGNOSTIC_ONLY},
        {"status": TrialStatus.INCOMPLETE, "missing": 1, "completed": 3},
        {"status": TrialStatus.FAILED, "failed": 1, "completed": 3},
        {"optimization_evidence": False},
        {"valid_for_comparison": False},
        {"score": None},
        {"score": float("nan")},
        {"results": ()},
    ],
)
def test_ineligible_values_are_not_cached_or_ranked(
    change: dict[str, object],
) -> None:
    cache = EvaluationCache()
    incumbent = scored((0.5,), 0.5)
    valid = incumbent.evaluation.trial
    invalid = replace(valid, **change)
    with pytest.raises(SpecError):
        _ = cache.evaluate(valid.identity, lambda: invalid)
    with pytest.raises(SpecError):
        _ = summarize_search(
            incumbent, (ScoredCandidate((0.5,), CachedEvaluation(invalid, False)),)
        )
    if invalid.status is TrialStatus.ELIGIBLE:
        with pytest.raises(SpecError):
            _ = invalid.fitness
    assert not cache.evaluate(valid.identity, lambda: valid).cache_hit


@pytest.mark.parametrize(
    "change", ["study", "benchmark", "conflict", "dimension", "bounds", "nonfinite"]
)
def test_selection_rejects_incompatible_evidence_and_coordinates(change: str) -> None:
    incumbent = scored((0.5,), 0.5)
    trial = synthetic_trial((0.0,), 0.75)
    point = ScoredCandidate((0.0,), CachedEvaluation(trial, False))
    if change == "study":
        point = replace(
            point, evaluation=CachedEvaluation(replace(trial, study_digest="other"), False)
        )
    elif change == "benchmark":
        point = replace(
            point, evaluation=CachedEvaluation(replace(trial, benchmark_identity="other"), False)
        )
    elif change == "conflict":
        point = ScoredCandidate(
            (0.5,), CachedEvaluation(replace(incumbent.evaluation.trial, score=0.75), False)
        )
    elif change == "dimension":
        point = replace(point, coordinates=(0.0, 0.0))
    elif change == "bounds":
        point = replace(point, coordinates=(2.0,))
    else:
        point = replace(point, coordinates=(float("nan"),))
    with pytest.raises(SpecError):
        _ = summarize_search(incumbent, (point,))
