from dataclasses import fields, replace
from typing import cast

import pytest
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.policy import EvaluationWeights
from gwent_evaluation.models import SpecError
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.parameters import (
    WEIGHT_NAMES,
    ParameterDefinition,
    bind_parameters,
    encode_parameters,
    frozen_configuration_digest,
)


def test_default_vector_preserves_exact_weights_and_digest(study: StudySpec) -> None:
    space, incumbent = study.parameter_space, study.incumbent
    vector = encode_parameters(space, incumbent, frozen_configuration=incumbent)
    assert (
        tuple(item.name for item in space.parameters)
        == tuple(field.name for field in fields(EvaluationWeights))
        == WEIGHT_NAMES
    )
    assert vector == (0.2, 0.25, 0.25, 0.25, 0.75, 0.75, 0.25, 0.25, 0.75, 0.75, 0.25)
    decoded = study.bind(vector)
    assert decoded == incumbent
    assert decoded.digest() == incumbent.digest()


@pytest.mark.parametrize("coordinate", [0.0, 1.0, 0.12345678901234567])
def test_bounds_and_interior_values_bind_without_other_changes(
    study: StudySpec, coordinate: float
) -> None:
    changed = study.bind((coordinate,) * 11)
    for parameter in study.parameter_space.parameters:
        expected = parameter.lower + coordinate * (parameter.upper - parameter.lower)
        assert getattr(changed.baseline.weights, parameter.name) == expected
    assert (
        frozen_configuration_digest(study.parameter_space, changed)
        == study.frozen_configuration_digest
    )
    assert study.incumbent == HeuristicConfiguration()


@pytest.mark.parametrize(
    "field", ["scorch_threshold", "max_candidates", "weights.immediate_points"]
)
def test_only_weight_names_are_allowed(field: str) -> None:
    with pytest.raises(SpecError, match="Unsupported tunable"):
        _ = ParameterDefinition(field, 0, 1)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered"])
def test_parameter_order_is_a_versioned_contract(study: StudySpec, mutation: str) -> None:
    parameters = study.parameter_space.parameters
    changed = {
        "missing": parameters[:-1],
        "duplicate": (*parameters[:-1], parameters[0]),
        "reordered": tuple(reversed(parameters)),
    }[mutation]
    with pytest.raises(SpecError, match="canonical order"):
        _ = replace(study.parameter_space, parameters=changed)


@pytest.mark.parametrize(
    "values",
    [
        (),
        (0.0,) * 10,
        (0.0,) * 12,
        (True,) * 11,
        (float("nan"),) * 11,
        (float("inf"),) * 11,
        (-0.01,) * 11,
        (1.01,) * 11,
    ],
)
def test_invalid_vectors_are_rejected(study: StudySpec, values: tuple[float, ...]) -> None:
    with pytest.raises(SpecError):
        _ = study.bind(values)


@pytest.mark.parametrize(
    "lower,upper",
    [(True, 1), (0, False), (float("nan"), 1), (0, float("inf")), (1, 1), (2, 1), (-1, 1)],
)
def test_invalid_bounds_are_rejected(lower: float, upper: float) -> None:
    with pytest.raises(SpecError):
        _ = ParameterDefinition("immediate_points", lower, upper)


def test_shadowed_weights_and_changed_frozen_settings_are_rejected(study: StudySpec) -> None:
    incumbent = study.incumbent
    shadowed = replace(
        incumbent,
        profile=replace(
            incumbent.profile, weights=replace(incumbent.profile.weights, immediate_points=1.0)
        ),
    )
    with pytest.raises(SpecError, match="shadowed"):
        _ = bind_parameters(study.parameter_space, (0.5,) * 11, frozen_configuration=shadowed)
    changed = replace(
        incumbent,
        baseline=replace(
            incumbent.baseline, candidates=replace(incumbent.baseline.candidates, max_candidates=99)
        ),
    )
    with pytest.raises(SpecError, match="frozen"):
        _ = encode_parameters(study.parameter_space, changed, frozen_configuration=incumbent)
    with pytest.raises(SpecError):
        _ = ParameterDefinition("scorch_exposure", -6, 1)


def test_no_out_of_bounds_default_or_mutable_space(study: StudySpec) -> None:
    parameters = list(study.parameter_space.parameters)
    parameters[0] = replace(parameters[0], lower=2.0)
    with pytest.raises(SpecError, match="outside"):
        _ = encode_parameters(
            replace(study.parameter_space, parameters=tuple(parameters)),
            study.incumbent,
            frozen_configuration=study.incumbent,
        )
    with pytest.raises(SpecError, match="immutable"):
        _ = replace(
            study.parameter_space,
            parameters=cast(tuple[ParameterDefinition, ...], cast(object, parameters)),
        )
