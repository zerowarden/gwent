"""Real bounded optimizer behavior over synthetic fitness; no game execution."""

from __future__ import annotations

import json
import pickle
import random
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast, final

import numpy as np
import pytest
from gwent_evaluation.models import SpecError
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.tuning import cma_backend
from gwent_evaluation.tuning.cma_backend import CmaEsSearch
from gwent_evaluation.tuning.models import (
    CmaSettings,
    CmaTermination,
    OptimizerMethod,
    OptimizerSpec,
    StudySpec,
)
from gwent_evaluation.tuning.optimizers import (
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
)
from gwent_evaluation.tuning.parameters import encode_parameters
from gwent_evaluation.tuning.study import create_optimizer
from numpy.typing import NDArray


def settings(*, seed: int = 0, population: int = 16, generations: int = 8) -> OptimizerSpec:
    return OptimizerSpec(
        OptimizerMethod.CMA_ES,
        seed,
        population * generations,
        population,
        generations,
        0.2,
        cma=CmaSettings(),
    )


def quadratic(coordinates: tuple[float, ...]) -> float:
    return sum((coordinate - 0.7) ** 2 for coordinate in coordinates)


def results(batch: tuple[Proposal, ...]) -> tuple[ProposalFitness, ...]:
    return tuple(ProposalFitness(proposal, quadratic(proposal.coordinates)) for proposal in batch)


def collect(backend: CmaEsSearch) -> tuple[tuple[ProposalFitness, ...], ...]:
    history: list[tuple[ProposalFitness, ...]] = []
    while batch := backend.ask():
        values = results(batch)
        backend.tell(values)
        history.append(values)
    return tuple(history)


def test_bounded_quadratic_improves_within_the_declared_budget() -> None:
    mean = (0.1,) * 11
    backend = CmaEsSearch(settings(), initial_mean=mean)
    history = collect(backend)
    proposals = [value for batch in history for value in batch]
    assert len(proposals) == 128
    assert min(value.fitness for value in proposals) < quadratic(mean)
    assert [value.proposal.index for value in proposals] == list(range(128))
    assert all(0 <= x <= 1 for value in proposals for x in value.proposal.coordinates)
    assert backend.stop_reason is OptimizerStopReason.BUDGET_EXHAUSTED
    assert backend.stop is not None
    assert backend.stop.completed_proposals == 128
    assert backend.ask() == ()


@final
class RecordingStrategy:
    def __init__(self, wrapped: cma_backend.CmaStrategy) -> None:
        self.wrapped = wrapped
        self.asked: list[NDArray[np.float64]] = []
        self.original_coordinates: tuple[tuple[float, ...], ...] = ()
        self.told: list[NDArray[np.float64]] = []
        self.values: list[float] = []

    def ask(self) -> list[NDArray[np.float64]]:
        self.asked = self.wrapped.ask()
        self.original_coordinates = tuple(
            tuple(cast(list[float], row.tolist())) for row in self.asked
        )
        return self.asked

    def tell(self, solutions: list[NDArray[np.float64]], values: list[float]) -> None:
        self.told = solutions
        self.values = list(values)
        self.wrapped.tell(solutions, values)

    def stop(self) -> Mapping[str, object]:
        return self.wrapped.stop()


@pytest.fixture
def recordings(monkeypatch: pytest.MonkeyPatch) -> list[RecordingStrategy]:
    factory = cma_backend.load_cma_strategy
    recorded: list[RecordingStrategy] = []

    def load(expected_version: str) -> cma_backend.CmaStrategyFactory:
        original = factory(expected_version)

        def construct(
            mean: list[float], sigma: float, options: dict[str, object]
        ) -> RecordingStrategy:
            strategy = RecordingStrategy(original(mean, sigma, options))
            recorded.append(strategy)
            return strategy

        return construct

    monkeypatch.setattr(cma_backend, "load_cma_strategy", load)
    return recorded


def test_boundaries_preserve_asked_evaluated_and_told_coordinates(
    study: StudySpec,
    recordings: list[RecordingStrategy],
) -> None:
    mean = tuple(float(index % 2) for index in range(11))
    backend = CmaEsSearch(settings(generations=2), initial_mean=mean)
    recorder = recordings[0]
    for _ in range(2):
        batch = backend.ask()
        assert backend.ask() == batch
        assert tuple(p.coordinates for p in batch) == recorder.original_coordinates
        for proposal in batch:
            candidate = study.bind(proposal.coordinates)
            for parameter, coordinate in zip(
                study.parameter_space.parameters, proposal.coordinates, strict=True
            ):
                assert getattr(candidate.baseline.weights, parameter.name) == (
                    parameter.lower + coordinate * (parameter.upper - parameter.lower)
                )
        values = results(batch)
        backend.tell(values)
        assert recorder.told is recorder.asked
        assert recorder.values == [item.fitness for item in values]


def test_flat_scores_are_not_perturbed_and_stop_with_actual_work(
    recordings: list[RecordingStrategy],
) -> None:
    backend = CmaEsSearch(settings(), initial_mean=(0.5,) * 11)
    batch = backend.ask()
    backend.tell(tuple(ProposalFitness(proposal, 0.5) for proposal in batch))
    assert recordings[0].values == [0.5] * 16
    assert backend.stop_reason is OptimizerStopReason.FLAT_OBJECTIVE
    assert backend.stop is not None
    assert backend.stop.completed_proposals == 16
    assert "tolfun" in backend.stop.backend_reasons
    assert backend.ask() == ()
    replay = CmaEsSearch(settings(), initial_mean=(0.5,) * 11)
    assert replay.ask() == batch
    replay.tell(tuple(ProposalFitness(proposal, 0.5) for proposal in batch))
    assert replay.stop == backend.stop


@pytest.mark.parametrize(
    "invalid", ["empty", "partial", "reversed", "repeated", "changed", "nan", "infinity", "bool"]
)
def test_rejected_populations_never_reach_backend_or_advance_randomness(
    invalid: str,
    recordings: list[RecordingStrategy],
) -> None:
    spec = settings(population=4, generations=2)
    backend = CmaEsSearch(spec, initial_mean=(0.5, 0.5))
    reference = CmaEsSearch(spec, initial_mean=(0.5, 0.5))
    with pytest.raises(SpecError, match="pending batch"):
        backend.tell(())
    batch = backend.ask()
    assert reference.ask() == batch
    valid = results(batch)
    alternatives = {
        "empty": (),
        "partial": valid[:1],
        "reversed": tuple(reversed(valid)),
        "repeated": (valid[0],) * len(valid),
        "changed": (
            replace(valid[0], proposal=replace(batch[0], coordinates=(0.1, 0.1))),
            *valid[1:],
        ),
        "nan": (replace(valid[0], fitness=float("nan")), *valid[1:]),
        "infinity": (replace(valid[0], fitness=float("inf")), *valid[1:]),
        "bool": (replace(valid[0], fitness=True), *valid[1:]),
    }
    with pytest.raises(SpecError):
        backend.tell(alternatives[invalid])
    assert recordings[0].told == []
    assert backend.ask() == batch
    assert backend.stop is None
    backend.tell(valid)
    reference.tell(valid)
    with pytest.raises(SpecError, match="pending batch"):
        backend.tell(valid)
    assert collect(backend) == collect(reference)


def test_interleaved_optimizers_and_global_random_draws_do_not_change_sequences() -> None:
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    before_numpy = pickle.dumps(numpy_state)
    specs = (settings(seed=0), settings(seed=23))
    expected = tuple(collect(CmaEsSearch(spec, initial_mean=(0.4, 0.4))) for spec in specs)
    backends = tuple(CmaEsSearch(spec, initial_mean=(0.4, 0.4)) for spec in specs)
    assert random.getstate() == python_state
    assert pickle.dumps(np.random.get_state()) == before_numpy
    try:
        for generation in range(8):
            for backend, history in zip(backends, expected, strict=True):
                random.seed(generation)
                np.random.seed(generation)
                _ = random.random()
                _ = np.random.standard_normal(20)
                current_numpy = pickle.dumps(np.random.get_state())
                current_python = random.getstate()
                batch = backend.ask()
                assert batch == tuple(item.proposal for item in history[generation])
                backend.tell(history[generation])
                assert pickle.dumps(np.random.get_state()) == current_numpy
                assert random.getstate() == current_python
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


def test_replaying_ordered_history_reproduces_future_proposals() -> None:
    spec = settings(population=4)
    original = CmaEsSearch(spec, initial_mean=(0.25, 0.75))
    history: list[tuple[ProposalFitness, ...]] = []
    for _ in range(3):
        batch = original.ask()
        history.append(results(batch))
        original.tell(history[-1])
    recovered = CmaEsSearch(spec, initial_mean=(0.25, 0.75))
    for values in history:
        assert recovered.ask() == tuple(item.proposal for item in values)
        recovered.tell(values)
    assert collect(recovered) == collect(original)
    assert recovered.stop == original.stop


def test_scores_change_the_next_generation() -> None:
    first = CmaEsSearch(settings(), initial_mean=(0.5, 0.5))
    second = CmaEsSearch(settings(), initial_mean=(0.5, 0.5))
    batch = first.ask()
    assert second.ask() == batch
    first.tell(results(batch))
    second.tell(tuple(replace(value, fitness=-value.fitness) for value in results(batch)))
    assert first.ask() != second.ask()


def test_study_factory_starts_at_encoded_incumbent_and_supports_smoke(study: StudySpec) -> None:
    backend = create_optimizer(study, OptimizerMethod.CMA_ES)
    mean = encode_parameters(
        study.parameter_space, study.incumbent, frozen_configuration=study.incumbent
    )
    reference = CmaEsSearch(study.optimizers[1], initial_mean=mean)
    assert backend.ask() == reference.ask()
    assert len(backend.ask()) == 2
    backend.tell(results(backend.ask()))
    assert backend.stop is not None
    assert backend.stop.completed_proposals == 2
    assert backend.ask() == ()


def test_no_external_files_or_control_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    control = tmp_path / "cma_signals.in"
    _ = control.write_text('{"maxiter": 1}')
    spec = settings(generations=3)
    history = collect(CmaEsSearch(spec, initial_mean=(0.2, 0.8)))
    assert len(history) == 3
    assert set(tmp_path.iterdir()) == {control}


def test_numerical_stopping_is_not_reported_as_a_flat_objective() -> None:
    spec = replace(settings(), cma=CmaSettings(termination=CmaTermination(coordinate_tolerance=1)))
    backend = CmaEsSearch(spec, initial_mean=(0.5, 0.5))
    backend.tell(results(backend.ask()))
    assert backend.stop_reason is OptimizerStopReason.NUMERICAL_LIMIT
    assert backend.stop is not None
    assert "tolx" in backend.stop.backend_reasons


def test_backend_failure_is_terminal_without_retrying_mutated_state(
    recordings: list[RecordingStrategy],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CmaEsSearch(settings(), initial_mean=(0.5, 0.5))
    batch = backend.ask()

    def fail(_solutions: list[NDArray[np.float64]], _values: list[float]) -> None:
        raise np.linalg.LinAlgError("synthetic decomposition failure")

    monkeypatch.setattr(recordings[0], "tell", fail)
    with pytest.raises(SpecError, match="decomposition failure"):
        backend.tell(results(batch))
    assert backend.stop_reason is OptimizerStopReason.NUMERICAL_LIMIT
    assert backend.stop is not None
    assert backend.stop.completed_proposals == 0
    assert backend.stop.detail == "LinAlgError: synthetic decomposition failure"
    assert backend.ask() == ()
    with pytest.raises(SpecError, match="has stopped"):
        backend.tell(results(batch))


@pytest.mark.parametrize(
    "mean", [(), (0.5,), (-0.1, 0.5), (1.1, 0.5), (float("nan"), 0.5), (True, 0.5)]
)
def test_invalid_initial_means_fail_before_backend_construction(mean: tuple[float, ...]) -> None:
    with pytest.raises(SpecError):
        _ = CmaEsSearch(settings(), initial_mean=mean)


def test_installed_backend_must_match_study(monkeypatch: pytest.MonkeyPatch) -> None:
    def different_version(_name: str) -> str:
        return "different"

    monkeypatch.setattr(cma_backend, "version", different_version)
    with pytest.raises(SpecError, match="version mismatch"):
        _ = CmaEsSearch(settings(), initial_mean=(0.5, 0.5))


def test_runtime_construction_and_random_search_work_without_optimizer_dependencies(
    study: StudySpec,
) -> None:
    code = """
import importlib.abc
import json
import sys

class BlockOptimizer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'cma', 'numpy'}:
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, BlockOptimizer())
from gwent_engine.ai.arena import create_bot
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_service.main import app
from gwent_service.api import get_match_service
create_bot('heuristic', bot_id='runtime', heuristic_configuration=HeuristicConfiguration())
get_match_service()
from gwent_evaluation.tuning.models import OptimizerMethod
from gwent_evaluation.tuning.study import create_optimizer
from gwent_evaluation.tuning.specs import study_from_dict
from gwent_evaluation.models import SpecError
study = study_from_dict(json.loads(sys.stdin.read()))
assert create_optimizer(study, OptimizerMethod.RANDOM).ask()
try:
    create_optimizer(study, OptimizerMethod.CMA_ES)
except SpecError as error:
    assert 'optional' in str(error)
else:
    raise AssertionError('Missing dependencies must fail clearly')
assert 'numpy' not in sys.modules and 'cma' not in sys.modules
"""
    _ = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(record_to_dict(study)),
        check=True,
        capture_output=True,
        text=True,
    )


def test_wrong_method_is_rejected() -> None:
    spec = OptimizerSpec(OptimizerMethod.RANDOM, 0, 4, 2, None, None)
    with pytest.raises(SpecError, match="CMA optimizer"):
        _ = CmaEsSearch(spec, initial_mean=(0.5, 0.5))


def test_unknown_method_is_rejected_by_study_factory(study: StudySpec) -> None:
    with pytest.raises(SpecError, match="not declared"):
        _ = create_optimizer(study, cast(OptimizerMethod, cast(object, "unknown")))


@pytest.mark.parametrize("invalid", ["count", "shape", "nonfinite", "bounds"])
def test_invalid_backend_proposals_stop_without_exposing_a_population(
    invalid: str,
    recordings: list[RecordingStrategy],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CmaEsSearch(settings(population=2), initial_mean=(0.5, 0.5))
    alternatives = {
        "count": [np.array([0.5, 0.5])],
        "shape": [np.array([0.5])] * 2,
        "nonfinite": [np.array([float("nan"), 0.5])] * 2,
        "bounds": [np.array([1.01, 0.5])] * 2,
    }
    monkeypatch.setattr(recordings[0], "ask", lambda: alternatives[invalid])
    with pytest.raises(SpecError, match="CMA ask failed"):
        _ = backend.ask()
    assert backend.stop_reason is OptimizerStopReason.BACKEND_FAILURE
    assert backend.ask() == ()
    assert recordings[0].told == []


def test_first_import_and_construction_preserve_global_random_state() -> None:
    code = """
import pickle
import random
import numpy as np
python_state = random.getstate()
numpy_state = pickle.dumps(np.random.get_state())
from gwent_evaluation.tuning.cma_backend import CmaEsSearch
from gwent_evaluation.tuning.models import CmaSettings, OptimizerMethod, OptimizerSpec
spec = OptimizerSpec(OptimizerMethod.CMA_ES, 0, 2, 2, 1, .2, cma=CmaSettings())
optimizer = CmaEsSearch(spec, initial_mean=(.5, .5))
optimizer.ask()
assert python_state == random.getstate()
assert numpy_state == pickle.dumps(np.random.get_state())
"""
    _ = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
