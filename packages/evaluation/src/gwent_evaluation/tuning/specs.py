"""Strict authoring references, complete snapshots, and zero-game planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import cast

from gwent_shared.extract import (
    expect_enum,
    expect_int,
    expect_mapping,
    expect_sequence,
    expect_str,
)
from gwent_shared.json_payloads import parse_json_document

from gwent_evaluation.agents import resolve_agent, snapshot_suite
from gwent_evaluation.assets import resolve_assets
from gwent_evaluation.execution import EvidencePolicy, build_run_manifest
from gwent_evaluation.metrics import BootstrapConfig
from gwent_evaluation.models import AgentSpec, RunManifest, SpecError, SuiteSpec
from gwent_evaluation.records import record_to_dict, run_manifest_from_dict
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.specs import load_agent_catalog, load_suite_catalog, parse_suite_spec
from gwent_evaluation.tuning.models import (
    OptimizerMethod,
    OptimizerSpec,
    SelectionPolicy,
    SensitivityProtocol,
    StudyMode,
    StudySpec,
)
from gwent_evaluation.tuning.parameters import (
    ParameterDefinition,
    ParameterSpace,
    finite_float,
    frozen_configuration_digest,
)


def _mapping(value: object, names: set[str], context: str) -> Mapping[str, object]:
    mapping = expect_mapping(value, context=context, error_factory=SpecError)
    if set(mapping) != names:
        raise SpecError(f"{context} must contain exactly: {', '.join(sorted(names))}.")
    return mapping


def _integer(value: object) -> int:
    return expect_int(value, context="study integer", error_factory=SpecError)


def _string(value: object) -> str:
    return expect_str(value, context="study string", error_factory=SpecError)


def _sequence(value: object) -> tuple[object, ...]:
    return tuple(expect_sequence(value, context="study sequence", error_factory=SpecError))


def _space(value: object) -> ParameterSpace:
    mapping = _mapping(value, {field.name for field in fields(ParameterSpace)}, "parameter_space")
    parameters: list[ParameterDefinition] = []
    for item in _sequence(mapping["parameters"]):
        parameter = _mapping(item, {"name", "lower", "upper"}, "parameter")
        parameters.append(
            ParameterDefinition(
                _string(parameter["name"]),
                finite_float(parameter["lower"], context="lower"),
                finite_float(parameter["upper"], context="upper"),
            )
        )
    return ParameterSpace(
        _integer(mapping["schema_version"]), _string(mapping["space_id"]), tuple(parameters)
    )


def _optimizer(value: object) -> OptimizerSpec:
    mapping = _mapping(value, {field.name for field in fields(OptimizerSpec)}, "optimizer")
    return OptimizerSpec(
        method=expect_enum(
            mapping["method"], OptimizerMethod, context="method", error_factory=SpecError
        ),
        seed=_integer(mapping["seed"]),
        proposal_budget=_integer(mapping["proposal_budget"]),
        batch_size=_integer(mapping["batch_size"]),
        generations=None if mapping["generations"] is None else _integer(mapping["generations"]),
        initial_sigma=None
        if mapping["initial_sigma"] is None
        else finite_float(mapping["initial_sigma"], context="initial_sigma"),
        protocol_version=_integer(mapping["protocol_version"]),
    )


def _selection(value: object) -> SelectionPolicy:
    mapping = _mapping(value, {field.name for field in fields(SelectionPolicy)}, "selection")
    return SelectionPolicy(
        _integer(mapping["version"]),
        _integer(mapping["finalist_count"]),
        finite_float(mapping["minimum_test_improvement"], context="minimum_test_improvement"),
        finite_float(mapping["maximum_stratum_decline"], context="maximum_stratum_decline"),
        tuple(_string(item) for item in _sequence(mapping["strata"])),
    )


def _sensitivity(value: object) -> SensitivityProtocol:
    mapping = _mapping(value, {field.name for field in fields(SensitivityProtocol)}, "sensitivity")
    return SensitivityProtocol(
        version=_integer(mapping["version"]),
        pilot_seeds=tuple(_integer(item) for item in _sequence(mapping["pilot_seeds"])),
        max_pilot_matches=_integer(mapping["max_pilot_matches"]),
        observations_per_match=_integer(mapping["observations_per_match"]),
        minimum_relative_score_witnesses=_integer(mapping["minimum_relative_score_witnesses"]),
        minimum_changed_actions=_integer(mapping["minimum_changed_actions"]),
        minimum_changed_outcomes=_integer(mapping["minimum_changed_outcomes"]),
    )


def _bootstrap(value: object) -> BootstrapConfig:
    mapping = _mapping(value, {field.name for field in fields(BootstrapConfig)}, "bootstrap")
    return BootstrapConfig(
        resamples=_integer(mapping["resamples"]),
        confidence_level=finite_float(mapping["confidence_level"], context="confidence_level"),
        minimum_blocks=_integer(mapping["minimum_blocks"]),
        seed=_integer(mapping["seed"]),
    )


def _study(
    mapping: Mapping[str, object],
    *,
    optimization: RunManifest,
    validation: RunManifest,
    test: RunManifest,
    fingerprint: str,
) -> StudySpec:
    return StudySpec(
        schema_version=_integer(mapping["schema_version"]),
        study_id=_string(mapping["study_id"]),
        mode=expect_enum(mapping["mode"], StudyMode, context="mode", error_factory=SpecError),
        parameter_space=_space(mapping["parameter_space"]),
        frozen_configuration_digest=fingerprint,
        optimization=optimization,
        validation=validation,
        test=test,
        optimizers=tuple(_optimizer(item) for item in _sequence(mapping["optimizers"])),
        objective_version=_integer(mapping["objective_version"]),
        selection=_selection(mapping["selection"]),
        sensitivity=_sensitivity(mapping["sensitivity"]),
        bootstrap=_bootstrap(mapping["bootstrap"]),
        evidence_policy=expect_enum(
            mapping["evidence_policy"],
            EvidencePolicy,
            context="evidence_policy",
            error_factory=SpecError,
        ),
        evaluation_match_budget=_integer(mapping["evaluation_match_budget"]),
    )


def _check_snapshot_fields(raw: object, expected: object) -> None:
    """Require complete nested records while reusing the evaluation record codec."""
    if isinstance(expected, dict):
        expected_mapping = cast(dict[str, object], expected)
        mapping = _mapping(raw, set(expected_mapping), "snapshot")
        for name, value in expected_mapping.items():
            _check_snapshot_fields(mapping[name], value)
    elif isinstance(expected, list):
        expected_items = cast(list[object], expected)
        items = _sequence(raw)
        if len(items) != len(expected_items):
            raise SpecError("Snapshot sequence length mismatch.")
        for item, expected_item in zip(items, expected_items, strict=True):
            _check_snapshot_fields(item, expected_item)


def study_from_dict(value: object) -> StudySpec:
    mapping = _mapping(value, {field.name for field in fields(StudySpec)}, "study snapshot")
    manifests: dict[str, RunManifest] = {}
    for stage in ("optimization", "validation", "test"):
        manifest = run_manifest_from_dict(mapping[stage])
        _check_snapshot_fields(mapping[stage], record_to_dict(manifest))
        manifests[stage] = manifest
    return _study(
        mapping,
        optimization=manifests["optimization"],
        validation=manifests["validation"],
        test=manifests["test"],
        fingerprint=_string(mapping["frozen_configuration_digest"]),
    )


def load_study_spec(path: Path, *, repository_root: Path) -> StudySpec:
    """Resolve authoring catalogs into pinned manifests, without executing games."""
    try:
        return _load_study_spec(path, repository_root=repository_root)
    except ValueError as error:
        raise SpecError(f"Invalid study {path}: {error}") from error


def _load_study_spec(path: Path, *, repository_root: Path) -> StudySpec:
    try:
        document = parse_json_document(
            path.read_text(encoding="utf-8"), context=str(path), error_factory=SpecError
        )
    except OSError as error:
        raise SpecError(f"Cannot read study {path}: {error}") from error
    author_fields = {field.name for field in fields(StudySpec)} - {
        "optimization",
        "validation",
        "test",
        "frozen_configuration_digest",
    }
    author_fields.update({"agents_catalog", "suites_catalog", "suites"})
    mapping = _mapping(document, author_fields, "study authoring spec")
    agents = load_agent_catalog(path.parent / _string(mapping["agents_catalog"]))
    suites = load_suite_catalog(path.parent / _string(mapping["suites_catalog"]), agents=agents)
    references = _mapping(
        mapping["suites"], {"optimization", "validation", "test"}, "suite references"
    )
    assets = resolve_assets()

    def resolve_reference(reference: object) -> SuiteSpec:
        if isinstance(reference, str):
            if reference not in suites:
                raise SpecError(f"Unknown suite reference {reference!r}.")
            return suites[reference]

        def resolve_agent_reference(agent_id: str) -> AgentSpec:
            if agent_id not in agents:
                raise SpecError(f"Unknown agent reference {agent_id!r}.")
            return agents[agent_id]

        return parse_suite_spec(reference, resolve_agent=resolve_agent_reference)

    manifests: dict[str, RunManifest] = {}
    for stage, reference in references.items():
        suite = snapshot_suite(resolve_reference(reference))
        manifests[stage] = build_run_manifest(
            suite=suite,
            run_id=f"{_string(mapping['study_id'])}-{stage}",
            matches=schedule_suite(suite),
            candidate=resolve_agent(suite.candidate),
            opponents=tuple(resolve_agent(agent) for agent in suite.opponents),
            assets=assets,
            repository_root=repository_root,
        )
    incumbent = manifests["optimization"].suite.candidate.heuristic_configuration
    if incumbent is None:
        raise SpecError("Study incumbent must be heuristic.")
    return _study(
        mapping,
        optimization=manifests["optimization"],
        validation=manifests["validation"],
        test=manifests["test"],
        fingerprint=frozen_configuration_digest(_space(mapping["parameter_space"]), incumbent),
    )


def plan_study(study: StudySpec) -> dict[str, object]:
    """Counts are upper bounds before cache hits and conditional selection."""
    return {
        "study_id": study.study_id,
        "study_digest": study.digest(),
        "mode": study.mode.value,
        "match_counts": study.match_counts(),
        "parameter_order": tuple(item.name for item in study.parameter_space.parameters),
        "incumbent_digest": study.incumbent.digest(),
        "frozen_configuration_digest": study.frozen_configuration_digest,
        "clean_checkout": study.optimization.repository.is_clean_checkout,
        "sensitivity_status": "not_assessed",
        "execution_available": False,
    }
