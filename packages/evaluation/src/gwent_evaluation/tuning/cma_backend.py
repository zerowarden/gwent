"""Bounded CMA proposals; the caller owns evaluation, eligibility, and persistence.

Protocol 1 uses a private PCG64 generator and the pinned pycma implementation.
Replay must call ask and tell for every recorded population, in order; pycma's
feed_for_resume alone does not restore the random stream. No fitness jitter,
restarts, external settings files, final-mean evaluations, or backend logging.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol, cast, final

import numpy as np
from numpy.typing import NDArray

from gwent_evaluation.models import SpecError
from gwent_evaluation.tuning.models import OptimizerMethod, OptimizerSpec
from gwent_evaluation.tuning.optimizers import (
    OptimizerStop,
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
    validate_population,
)
from gwent_evaluation.tuning.parameters import finite_float


class CmaStrategy(Protocol):
    """The narrow untyped third-party boundary; no workspace-wide typing overrides."""

    def ask(self) -> list[NDArray[np.float64]]: ...

    def tell(self, solutions: list[NDArray[np.float64]], values: list[float]) -> None: ...

    def stop(self) -> Mapping[str, object]: ...


CmaStrategyFactory = Callable[[list[float], float, dict[str, object]], CmaStrategy]
_BACKEND_ERRORS = (ArithmeticError, ValueError, RuntimeError, np.linalg.LinAlgError)
_FLAT_REASONS = frozenset({"tolfun", "tolfunhist", "tolflatfitness"})
_NUMERICAL_REASONS = frozenset({"tolx", "tolconditioncov", "noeffectaxis", "noeffectcoord"})
_BUDGET_REASONS = frozenset({"maxiter", "maxfevals"})


def load_cma_strategy(expected_version: str) -> CmaStrategyFactory:
    try:
        installed = version("cma")
        if installed != expected_version:
            raise SpecError(
                f"CMA version mismatch: expected {expected_version}, found {installed}."
            )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Could not import matplotlib.pyplot",
                category=UserWarning,
                module=r"cma\.s",
            )
            module = import_module("cma")
    except (PackageNotFoundError, ImportError) as error:
        raise SpecError(
            "CMA requires the optional gwent-evaluation[tuning] dependencies."
        ) from error
    return cast(CmaStrategyFactory, module.CMAEvolutionStrategy)


def _options(
    settings: OptimizerSpec, randn: Callable[..., NDArray[np.float64]]
) -> dict[str, object]:
    assert settings.cma is not None
    termination = settings.cma.termination
    return {
        "bounds": [0.0, 1.0],
        "BoundaryHandler": settings.cma.boundary_handler,
        "popsize": settings.batch_size,
        "maxiter": settings.generations,
        "maxfevals": settings.proposal_budget,
        "randn": randn,
        "seed": np.nan,  # The injected generator owns the seed; never reseed global NumPy.
        "tolfun": termination.function_tolerance,
        "tolfunhist": termination.history_tolerance,
        "tolflatfitness": termination.flat_generations,
        "tolx": termination.coordinate_tolerance,
        "tolconditioncov": termination.condition_limit,
        # Only declared tolerances, numerical limits, and the proposal cap may stop a run.
        "ftarget": -np.inf,
        "tolfunrel": 0,
        "tolfacupx": np.inf,
        "tolupsigma": np.inf,
        "tolstagnation": 0,
        "tolxstagnation": False,
        "timeout": np.inf,
        "termination_callback": [],
        "signals_filename": "",
        "eval_final_mean": False,
        "verbose": -9,
        "verb_disp": 0,
        "verb_log": 0,
        "verb_plot": 0,
        "verb_time": False,
    }


@final
class CmaEsSearch:
    def __init__(self, settings: OptimizerSpec, *, initial_mean: tuple[float, ...]) -> None:
        if settings.method is not OptimizerMethod.CMA_ES or settings.cma is None:
            raise SpecError("CMA search requires CMA optimizer settings.")
        if type(initial_mean) is not tuple or len(initial_mean) < 2:
            raise SpecError("CMA requires at least two normalized coordinates.")
        mean = tuple(finite_float(value, context="CMA initial mean") for value in initial_mean)
        if any(not 0 <= value <= 1 for value in mean):
            raise SpecError("CMA initial mean must lie in [0, 1].")
        self._settings = settings
        self._dimensions = len(mean)
        self._completed = 0
        self._pending: tuple[Proposal, ...] = ()
        self._vectors: list[NDArray[np.float64]] = []
        self._stop: OptimizerStop | None = None
        rng = np.random.Generator(np.random.PCG64(settings.seed))

        def randn(*shape: int) -> NDArray[np.float64]:
            return rng.standard_normal(shape)

        factory = load_cma_strategy(settings.cma.backend_version)
        assert settings.initial_sigma is not None
        try:
            self._strategy = factory(list(mean), settings.initial_sigma, _options(settings, randn))
        except _BACKEND_ERRORS as error:
            raise SpecError(f"Cannot initialize CMA: {error}") from error

    @property
    def stop(self) -> OptimizerStop | None:
        return self._stop

    @property
    def stop_reason(self) -> OptimizerStopReason | None:
        return None if self._stop is None else self._stop.reason

    def _fail(self, error: Exception) -> None:
        reason = (
            OptimizerStopReason.NUMERICAL_LIMIT
            if isinstance(error, (ArithmeticError, np.linalg.LinAlgError))
            else OptimizerStopReason.BACKEND_FAILURE
        )
        self._stop = OptimizerStop(
            reason, self._completed, detail=f"{type(error).__name__}: {error}"
        )

    def ask(self) -> tuple[Proposal, ...]:
        if self._stop is not None:
            return ()
        if self._pending:
            return self._pending
        try:
            vectors = self._strategy.ask()
            if len(vectors) != self._settings.batch_size:
                raise ValueError("CMA returned an incomplete population.")
            proposals: list[Proposal] = []
            for offset, vector in enumerate(vectors):
                if vector.shape != (self._dimensions,) or not np.all(np.isfinite(vector)):
                    raise ValueError("CMA returned invalid coordinates.")
                coordinates = tuple(cast(list[float], vector.tolist()))
                if any(not 0 <= value <= 1 for value in coordinates):
                    raise ValueError("CMA returned coordinates outside [0, 1].")
                proposals.append(Proposal(self._completed + offset, coordinates))
        except _BACKEND_ERRORS as error:
            self._fail(error)
            raise SpecError(f"CMA ask failed: {error}") from error
        self._vectors = vectors
        self._pending = tuple(proposals)
        return self._pending

    def tell(self, results: tuple[ProposalFitness, ...]) -> None:
        if self._stop is not None:
            raise SpecError("CMA has stopped; replay committed history before recovery.")
        fitness = validate_population(self._pending, results)
        try:
            self._strategy.tell(self._vectors, list(fitness))
            self._completed += len(results)
            self._pending = ()
            self._vectors = []
            self._record_stop(self._strategy.stop())
        except _BACKEND_ERRORS as error:
            self._fail(error)
            raise SpecError(f"CMA tell failed: {error}") from error

    def _record_stop(self, diagnostics: Mapping[str, object]) -> None:
        reasons = frozenset(diagnostics)
        if reasons - (_FLAT_REASONS | _NUMERICAL_REASONS | _BUDGET_REASONS):
            reason = OptimizerStopReason.BACKEND_FAILURE
        elif reasons & _NUMERICAL_REASONS:
            reason = OptimizerStopReason.NUMERICAL_LIMIT
        elif reasons & _FLAT_REASONS:
            reason = OptimizerStopReason.FLAT_OBJECTIVE
        elif reasons & _BUDGET_REASONS or self._completed == self._settings.proposal_budget:
            reason = OptimizerStopReason.BUDGET_EXHAUSTED
        else:
            return
        self._stop = OptimizerStop(reason, self._completed, tuple(sorted(reasons)))
