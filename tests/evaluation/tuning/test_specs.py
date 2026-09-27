from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest
from gwent_evaluation import cli
from gwent_evaluation.models import SpecError, SuitePurpose
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.tuning.models import (
    CmaSettings,
    OptimizerMethod,
    OptimizerSpec,
    StudyMode,
    StudySpec,
)
from gwent_evaluation.tuning.specs import (
    load_study_spec,
    plan_study,
    study_from_dict,
)
from gwent_shared.json_payloads import parse_json_document

from tests.evaluation.support import REPOSITORY_ROOT


def test_full_snapshot_round_trip_is_independent_of_catalogs(
    study: StudySpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = record_to_dict(study)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Snapshot decoding must not read authoring catalogs")

    monkeypatch.setattr(Path, "read_text", forbidden)
    decoded = study_from_dict(parse_json_document(json.dumps(snapshot), context="test"))
    assert decoded == study
    assert decoded.digest() == study.digest()
    assert decoded.optimization.repository.implementation_digest
    assert decoded.optimization.runtime.packages
    assert decoded.optimization.assets.deck_digests
    assert decoded.optimization.suite.candidate.heuristic_configuration == study.incumbent


def test_plan_counts_are_exact_and_cli_never_calls_evaluator(
    study_path: Path,
    study: StudySpec,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Planning must not call the evaluator")

    monkeypatch.setattr(cli, "execute_run", forbidden)
    assert cli.main(["tune", "plan", str(study_path)]) == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["sensitivity_status"] == "not_assessed"
    assert payload["execution_available"] is False
    assert payload["match_counts"] == {
        "optimize_per_candidate": 4,
        "validation_per_candidate": 4,
        "test_per_candidate": 4,
        "proposal_slots": 4,
        "optimization_matches": 20,
        "maximum_validation_matches": 12,
        "maximum_test_matches": 8,
        "maximum_evaluation_matches": 40,
        "separate_pilot_match_budget": 12,
    }
    expected = plan_study(study)
    expected["parameter_order"] = [item.name for item in study.parameter_space.parameters]
    assert payload == expected


def test_scientific_stages_require_matching_purposes_without_playing_games(
    study: StudySpec,
) -> None:
    manifests = tuple(
        replace(manifest, suite=replace(manifest.suite, purpose=purpose))
        for manifest, purpose in zip(
            (study.optimization, study.validation, study.test),
            (SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST),
            strict=True,
        )
    )
    scientific = replace(
        study,
        mode=StudyMode.SCIENTIFIC,
        optimization=manifests[0],
        validation=manifests[1],
        test=manifests[2],
    )
    assert plan_study(scientific)["execution_available"] is True
    assert scientific.match_counts() == study.match_counts()
    assert study_from_dict(record_to_dict(scientific)) == scientific
    with pytest.raises(SpecError, match="purpose"):
        _ = replace(scientific, validation=scientific.test)


@pytest.mark.parametrize(
    "change",
    [
        "roots",
        "purpose",
        "budget",
        "optimizer_budget",
        "fingerprint",
        "pilot_roots",
        "mutable_optimizers",
        "objective",
        "boolean_budget",
    ],
)
def test_conflicting_python_studies_fail_preflight(study: StudySpec, change: str) -> None:
    with pytest.raises(ValueError):
        match change:
            case "roots":
                _ = replace(
                    study,
                    validation=replace(
                        study.validation,
                        suite=replace(study.validation.suite, seeds=study.optimization.suite.seeds),
                    ),
                )
            case "purpose":
                _ = replace(
                    study,
                    validation=replace(
                        study.validation,
                        suite=replace(study.validation.suite, purpose=SuitePurpose.TEST),
                    ),
                )
            case "budget":
                _ = replace(study, evaluation_match_budget=39)
            case "optimizer_budget":
                _ = replace(
                    study,
                    optimizers=(
                        replace(study.optimizers[0], proposal_budget=4),
                        study.optimizers[1],
                    ),
                )
            case "fingerprint":
                _ = replace(study, frozen_configuration_digest="changed")
            case "pilot_roots":
                _ = replace(
                    study,
                    sensitivity=replace(study.sensitivity, pilot_seeds=study.test.suite.seeds),
                )
            case "mutable_optimizers":
                _ = replace(study, **{"optimizers": list(study.optimizers)})
            case "objective":
                _ = replace(study, objective_version=2)
            case "boolean_budget":
                _ = replace(study, evaluation_match_budget=True)
            case _:
                raise AssertionError(f"Unknown test mutation: {change}")


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("parameter_space",),
        ("selection",),
        ("bootstrap",),
        ("optimization", "suite", "candidate"),
        ("optimization", "repository"),
    ],
)
def test_unknown_and_missing_snapshot_fields_fail(study: StudySpec, path: tuple[str, ...]) -> None:
    for mutation in ("unknown", "missing"):
        payload = record_to_dict(study)
        mapping = payload
        for key in path:
            mapping = cast(dict[str, object], mapping[key])
        if mutation == "unknown":
            mapping["unknown"] = True
        else:
            del mapping[next(iter(mapping))]
        with pytest.raises(ValueError):
            _ = study_from_dict(payload)


@pytest.mark.parametrize(
    "change",
    [
        "coordinate_order",
        "seed_overlap",
        "unknown",
        "cma_budget",
        "bool_threshold",
        "nonfinite",
        "missing",
    ],
)
def test_invalid_authoring_specs_run_zero_matches(
    study_path: Path, tmp_path: Path, change: str
) -> None:
    payload = cast(dict[str, object], json.loads(study_path.read_text()))
    payload["agents_catalog"] = str(REPOSITORY_ROOT / "experiments/agents.json")
    payload["suites_catalog"] = str(REPOSITORY_ROOT / "experiments/suites.json")
    if change == "coordinate_order":
        space = cast(dict[str, object], payload["parameter_space"])
        space["parameters"] = list(reversed(cast(list[object], space["parameters"])))
    elif change == "seed_overlap":
        suites = cast(dict[str, dict[str, object]], payload["suites"])
        suites["validation"]["seeds"] = suites["optimization"]["seeds"]
    elif change == "unknown":
        payload["unknown"] = 1
    elif change == "cma_budget":
        cast(list[dict[str, object]], payload["optimizers"])[1]["generations"] = 99
    elif change == "bool_threshold":
        cast(dict[str, object], payload["selection"])["minimum_test_improvement"] = True
    elif change == "nonfinite":
        cast(dict[str, object], payload["selection"])["minimum_test_improvement"] = float("inf")
    else:
        del payload["sensitivity"]
    path = tmp_path / "invalid.json"
    _ = path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        _ = load_study_spec(path, repository_root=REPOSITORY_ROOT)


def test_json_duplicate_keys_fail_before_catalog_resolution(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    _ = path.write_text('{"study_id":"a","study_id":"b"}')
    with pytest.raises(SpecError, match="duplicate"):
        _ = load_study_spec(path, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend_version", "unrecognized"),
        ("random_generator", "global"),
        ("boundary_handler", "clip"),
        ("termination", {}),
        ("function_tolerance", -1),
        ("history_tolerance", float("nan")),
        ("flat_generations", True),
        ("coordinate_tolerance", float("inf")),
        ("condition_limit", 1),
    ],
)
def test_cma_snapshot_pins_are_strict(study: StudySpec, field: str, value: object) -> None:
    snapshot = record_to_dict(study)
    optimizer = cast(list[dict[str, object]], snapshot["optimizers"])[1]
    cma = cast(dict[str, object], optimizer["cma"])
    target = cma if field in cma else cast(dict[str, object], cma["termination"])
    target[field] = value
    with pytest.raises(SpecError):
        _ = study_from_dict(snapshot)


def test_cma_pins_change_study_identity_and_survive_round_trip(study: StudySpec) -> None:
    original = study.optimizers[1]
    assert original.cma is not None
    updated = replace(
        original,
        cma=replace(
            original.cma, termination=replace(original.cma.termination, flat_generations=3)
        ),
    )
    changed = replace(study, optimizers=(study.optimizers[0], updated))
    assert changed.digest() != study.digest()
    assert study_from_dict(record_to_dict(changed)) == changed


@pytest.mark.parametrize("missing", ["cma", "backend_version", "function_tolerance"])
def test_snapshot_pins_are_never_filled_from_defaults(study: StudySpec, missing: str) -> None:
    snapshot = record_to_dict(study)
    optimizer = cast(list[dict[str, object]], snapshot["optimizers"])[1]
    cma = cast(dict[str, object], optimizer["cma"])
    if missing == "cma":
        del optimizer[missing]
    elif missing == "backend_version":
        del cma[missing]
    else:
        del cast(dict[str, object], cma["termination"])[missing]
    with pytest.raises(SpecError, match="must contain exactly"):
        _ = study_from_dict(snapshot)


def test_old_study_schema_cannot_be_executed_with_new_defaults(study: StudySpec) -> None:
    with pytest.raises(SpecError, match="study schema version"):
        _ = replace(study, schema_version=1)


def test_optimizer_settings_require_method_specific_pins(study: StudySpec) -> None:
    with pytest.raises(SpecError, match="cannot declare CMA"):
        _ = replace(study.optimizers[0], cma=CmaSettings())
    with pytest.raises(SpecError, match="explicit backend settings"):
        _ = OptimizerSpec(OptimizerMethod.CMA_ES, 0, 2, 2, 1, 0.2)
    with pytest.raises(SpecError, match="nonnegative"):
        _ = replace(study.optimizers[1], seed=-1)
