"""Bounded study declarations. These records do not run games or optimizers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from gwent_engine.ai.baseline.profile_catalog import DEFAULT_BASE_PROFILE
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_shared.extract import expect_int, expect_str

from gwent_evaluation.agents import resolve_agent
from gwent_evaluation.execution import EvidencePolicy
from gwent_evaluation.metrics import BootstrapConfig
from gwent_evaluation.models import BotFamily, RunManifest, SpecError, SuitePurpose
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import record_to_dict, run_manifest_from_dict
from gwent_evaluation.tuning.parameters import (
    ParameterSpace,
    bind_parameters,
    encode_parameters,
    finite_float,
    frozen_configuration_digest,
)
from gwent_evaluation.validation import validate_manifest_schedule


class StudyMode(StrEnum):
    SCIENTIFIC = "scientific"
    SMOKE = "smoke"


class OptimizerMethod(StrEnum):
    RANDOM = "random"
    CMA_ES = "cma_es"


def _positive_integer(value: object, name: str) -> int:
    integer = expect_int(value, context=name, error_factory=SpecError)
    if integer <= 0:
        raise SpecError(f"{name} must be positive.")
    return integer


@dataclass(frozen=True, slots=True)
class CmaTermination:
    function_tolerance: float = 1e-11
    history_tolerance: float = 1e-12
    flat_generations: int = 1
    coordinate_tolerance: float = 1e-11
    condition_limit: float = 1e14

    def __post_init__(self) -> None:
        _ = _positive_integer(self.flat_generations, "flat_generations")
        for name in ("function_tolerance", "history_tolerance", "coordinate_tolerance"):
            value = finite_float(cast(object, getattr(self, name)), context=name)
            if value < 0:
                raise SpecError(f"{name} must be nonnegative.")
            object.__setattr__(self, name, value)
        limit = finite_float(self.condition_limit, context="condition_limit")
        if limit <= 1:
            raise SpecError("condition_limit must exceed one.")
        object.__setattr__(self, "condition_limit", limit)


@dataclass(frozen=True, slots=True)
class CmaSettings:
    backend_version: str = "4.5.0"
    random_generator: str = "numpy_pcg64"
    boundary_handler: str = "BoundTransform"
    termination: CmaTermination = CmaTermination()

    def __post_init__(self) -> None:
        if self.backend_version != "4.5.0":
            raise SpecError("Unsupported CMA backend version.")
        if self.random_generator != "numpy_pcg64":
            raise SpecError("Unsupported CMA random generator.")
        if self.boundary_handler != "BoundTransform":
            raise SpecError("Unsupported CMA boundary handler.")
        if type(self.termination) is not CmaTermination:
            raise SpecError("CMA termination must be an immutable typed record.")


@dataclass(frozen=True, slots=True)
class OptimizerSpec:
    method: OptimizerMethod
    seed: int
    proposal_budget: int
    batch_size: int
    generations: int | None
    initial_sigma: float | None
    protocol_version: int = 1
    cma: CmaSettings | None = None

    def __post_init__(self) -> None:
        if type(self.method) is not OptimizerMethod:
            raise SpecError("Unsupported optimizer method.")
        if _positive_integer(self.protocol_version, "optimizer protocol version") != 1:
            raise SpecError("Unsupported optimizer protocol version.")
        _ = expect_int(self.seed, context="optimizer seed", error_factory=SpecError)
        _ = _positive_integer(self.proposal_budget, "proposal_budget")
        _ = _positive_integer(self.batch_size, "batch_size")
        if self.proposal_budget % self.batch_size:
            raise SpecError("Proposal budget must contain complete batches.")
        if self.method is OptimizerMethod.RANDOM:
            if any(value is not None for value in (self.generations, self.initial_sigma, self.cma)):
                raise SpecError("Random search cannot declare CMA settings.")
        else:
            if type(self.cma) is not CmaSettings:
                raise SpecError("CMA requires explicit backend settings.")
            if self.seed < 0:
                raise SpecError("CMA seed must be nonnegative.")
            generations = _positive_integer(self.generations, "generations")
            sigma = finite_float(self.initial_sigma, context="initial_sigma")
            if self.batch_size < 2 or self.proposal_budget != generations * self.batch_size:
                raise SpecError("CMA budget must equal population size times generations.")
            if not 0 < sigma <= 1:
                raise SpecError("CMA initial_sigma must lie in (0, 1].")
            object.__setattr__(self, "initial_sigma", sigma)


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    version: int
    finalist_count: int
    minimum_test_improvement: float
    maximum_stratum_decline: float
    strata: tuple[str, ...]

    def __post_init__(self) -> None:
        if _positive_integer(self.version, "selection version") != 1:
            raise SpecError("Unsupported selection policy version.")
        if not 1 <= _positive_integer(self.finalist_count, "finalist_count") <= 3:
            raise SpecError("Select between one and three finalists.")
        for name in ("minimum_test_improvement", "maximum_stratum_decline"):
            value = finite_float(cast(object, getattr(self, name)), context=name)
            if not 0 <= value <= 1:
                raise SpecError(f"{name} must lie in [0, 1].")
            object.__setattr__(self, name, value)
        if self.strata != ("opponent", "candidate_deck"):
            raise SpecError("Selection v1 guards opponent and candidate_deck strata.")


@dataclass(frozen=True, slots=True)
class SensitivityProtocol:
    version: int
    pilot_seeds: tuple[int, ...]
    max_pilot_matches: int
    observations_per_match: int
    minimum_relative_score_witnesses: int
    minimum_changed_actions: int
    minimum_changed_outcomes: int

    def __post_init__(self) -> None:
        if _positive_integer(self.version, "sensitivity version") != 1:
            raise SpecError("Unsupported sensitivity protocol version.")
        if type(self.pilot_seeds) is not tuple or not self.pilot_seeds:
            raise SpecError("Pilot seeds must be a nonempty immutable tuple.")
        for seed in self.pilot_seeds:
            _ = expect_int(seed, context="pilot seed", error_factory=SpecError)
        if len(set(self.pilot_seeds)) != len(self.pilot_seeds):
            raise SpecError("Duplicate pilot seeds.")
        for name in (
            "max_pilot_matches",
            "observations_per_match",
            "minimum_relative_score_witnesses",
            "minimum_changed_actions",
            "minimum_changed_outcomes",
        ):
            _ = _positive_integer(cast(object, getattr(self, name)), name)


@dataclass(frozen=True, slots=True)
class StudySpec:
    schema_version: int
    study_id: str
    mode: StudyMode
    parameter_space: ParameterSpace
    frozen_configuration_digest: str
    optimization: RunManifest
    validation: RunManifest
    test: RunManifest
    optimizers: tuple[OptimizerSpec, ...]
    objective_version: int
    selection: SelectionPolicy
    sensitivity: SensitivityProtocol
    bootstrap: BootstrapConfig
    evidence_policy: EvidencePolicy
    evaluation_match_budget: int

    def __post_init__(self) -> None:
        if _positive_integer(self.schema_version, "study schema version") != 2:
            raise SpecError("Unsupported study schema version.")
        _ = expect_str(self.study_id, context="study_id", error_factory=SpecError)
        if type(self.mode) is not StudyMode or type(self.evidence_policy) is not EvidencePolicy:
            raise SpecError("Unsupported study mode or evidence policy.")
        if _positive_integer(self.objective_version, "objective_version") != 1:
            raise SpecError("Unsupported objective version.")
        if (
            type(self.parameter_space) is not ParameterSpace
            or type(self.selection) is not SelectionPolicy
            or type(self.sensitivity) is not SensitivityProtocol
            or type(self.bootstrap) is not BootstrapConfig
        ):
            raise SpecError("Study policies must be immutable typed records.")
        if type(self.optimizers) is not tuple or any(
            type(item) is not OptimizerSpec for item in self.optimizers
        ):
            raise SpecError("optimizers must be an immutable tuple of OptimizerSpec records.")
        if tuple(item.method for item in self.optimizers) != (
            OptimizerMethod.RANDOM,
            OptimizerMethod.CMA_ES,
        ):
            raise SpecError("Declare random then cma_es exactly once.")
        if self.optimizers[0].proposal_budget != self.optimizers[1].proposal_budget:
            raise SpecError("Random and CMA must have equal proposal budgets.")
        if self.selection.finalist_count > sum(item.proposal_budget for item in self.optimizers):
            raise SpecError("Finalist count exceeds the proposal budget.")
        for name in ("resamples", "minimum_blocks"):
            _ = _positive_integer(cast(object, getattr(self.bootstrap, name)), f"bootstrap.{name}")
        _ = expect_int(self.bootstrap.seed, context="bootstrap.seed", error_factory=SpecError)
        confidence = finite_float(
            self.bootstrap.confidence_level, context="bootstrap.confidence_level"
        )
        if not 0 < confidence < 1:
            raise SpecError("Bootstrap confidence must lie in (0, 1).")
        self._validate_suites()
        if (
            frozen_configuration_digest(self.parameter_space, self.incumbent)
            != self.frozen_configuration_digest
        ):
            raise SpecError("Incumbent does not match the frozen configuration fingerprint.")
        _ = encode_parameters(
            self.parameter_space, self.incumbent, frozen_configuration=self.incumbent
        )
        if (
            _positive_integer(self.evaluation_match_budget, "evaluation_match_budget")
            != self.match_counts()["maximum_evaluation_matches"]
        ):
            raise SpecError(
                "Declared match budget disagrees with scheduled stages and proposal budgets."
            )

    @property
    def incumbent(self) -> HeuristicConfiguration:
        configuration = self.optimization.suite.candidate.heuristic_configuration
        if configuration is None:
            raise SpecError("Study incumbent must be an explicit heuristic snapshot.")
        return configuration

    def _validate_suites(self) -> None:
        manifests = (self.optimization, self.validation, self.test)
        purposes = (SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST)
        roots: set[int] = set()
        ids: set[str] = set()
        for manifest, purpose in zip(manifests, purposes, strict=True):
            if type(manifest) is not RunManifest:
                raise SpecError("Study suites must be full run-manifest snapshots.")
            if run_manifest_from_dict(record_to_dict(manifest)) != manifest:
                raise SpecError("Study manifests must use immutable canonical record values.")
            suite = manifest.suite
            expected_purpose = SuitePurpose.SMOKE if self.mode is StudyMode.SMOKE else purpose
            if suite.purpose is not expected_purpose:
                raise SpecError("Suite purpose conflicts with its study stage.")
            if suite.suite_id in ids or roots.intersection(suite.seeds):
                raise SpecError("Study stages require distinct suite IDs and disjoint root seeds.")
            ids.add(suite.suite_id)
            roots.update(suite.seeds)
            reference = self.optimization
            if (
                suite.candidate != reference.suite.candidate
                or suite.opponents != reference.suite.opponents
                or suite.deck_pairs != reference.suite.deck_pairs
                or suite.action_budget != reference.suite.action_budget
            ):
                raise SpecError(
                    "Study stages must share incumbent, opponents, decks, and action budget."
                )
            if (
                manifest.repository != reference.repository
                or manifest.runtime != reference.runtime
                or manifest.assets != reference.assets
            ):
                raise SpecError("Study stage provenance/assets differ.")
            _ = validate_manifest_schedule(manifest)
            for spec, identity in zip(
                (suite.candidate, *suite.opponents),
                (manifest.candidate, *manifest.opponents),
                strict=True,
            ):
                if spec.family is BotFamily.HEURISTIC and spec.heuristic_configuration is None:
                    raise SpecError("Heuristic participants require full snapshots.")
                if resolve_agent(spec).digest() != identity.digest:
                    raise SpecError("Participant configuration does not match its pinned identity.")
        if set(self.sensitivity.pilot_seeds).intersection(
            self.validation.suite.seeds + self.test.suite.seeds
        ):
            raise SpecError("Pilot roots cannot overlap validation or test roots.")
        profile = self.incumbent.profile
        if (
            profile.policies != DEFAULT_BASE_PROFILE.policies
            or profile.weights != DEFAULT_BASE_PROFILE.weights
            or profile.pass_overrides != DEFAULT_BASE_PROFILE.pass_overrides
        ):
            raise SpecError("The initial study targets resolved neutral without profile overrides.")

    def bind(self, coordinates: tuple[float, ...]) -> HeuristicConfiguration:
        return bind_parameters(
            self.parameter_space, coordinates, frozen_configuration=self.incumbent
        )

    def digest(self) -> str:
        return canonical_digest(self)

    def match_counts(self) -> dict[str, int]:
        counts = {
            "optimize_per_candidate": len(self.optimization.planned_case_ids),
            "validation_per_candidate": len(self.validation.planned_case_ids),
            "test_per_candidate": len(self.test.planned_case_ids),
        }
        proposals = sum(item.proposal_budget for item in self.optimizers)
        counts["proposal_slots"] = proposals
        counts["optimization_matches"] = (1 + proposals) * counts["optimize_per_candidate"]
        counts["maximum_validation_matches"] = (1 + self.selection.finalist_count) * counts[
            "validation_per_candidate"
        ]
        counts["maximum_test_matches"] = 2 * counts["test_per_candidate"]
        counts["maximum_evaluation_matches"] = (
            counts["optimization_matches"]
            + counts["maximum_validation_matches"]
            + counts["maximum_test_matches"]
        )
        counts["separate_pilot_match_budget"] = self.sensitivity.max_pilot_matches
        return counts


@dataclass(frozen=True, slots=True)
class SweepPoint:
    parameter: str
    value: float
    coordinates: tuple[float, ...]
    configuration_digest: str
