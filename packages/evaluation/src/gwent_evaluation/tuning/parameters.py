"""The versioned, ordered weight surface; no arbitrary attribute paths."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from typing import cast

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.policy import EvaluationWeights
from gwent_shared.extract import expect_finite_float, expect_int, expect_sequence, expect_str

from gwent_evaluation.models import SpecError
from gwent_evaluation.provenance import canonical_digest


def finite_float(value: object, *, context: str) -> float:
    return expect_finite_float(value, context=context, error_factory=SpecError)


WEIGHT_NAMES: tuple[str, ...] = tuple(field.name for field in fields(EvaluationWeights))
_PENALTIES = frozenset(
    {"scorch_exposure", "weather_exposure", "overcommit_penalty", "dead_card_penalty"}
)


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    name: str
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if self.name not in WEIGHT_NAMES:
            raise SpecError(f"Unsupported tunable {self.name!r}.")
        lower = finite_float(self.lower, context=f"{self.name}.lower")
        upper = finite_float(self.upper, context=f"{self.name}.upper")
        if lower >= upper or not math.isfinite(upper - lower):
            raise SpecError("Parameter bounds must have a positive finite width.")
        if (self.name in _PENALTIES and upper > 0) or (self.name not in _PENALTIES and lower < 0):
            raise SpecError(f"{self.name} bounds must preserve the weight's sign.")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)


@dataclass(frozen=True, slots=True)
class ParameterSpace:
    schema_version: int
    space_id: str
    parameters: tuple[ParameterDefinition, ...]

    def __post_init__(self) -> None:
        if (
            expect_int(
                self.schema_version, context="parameter space version", error_factory=SpecError
            )
            != 1
        ):
            raise SpecError("Unsupported parameter space version.")
        _ = expect_str(self.space_id, context="space_id", error_factory=SpecError)
        if type(self.parameters) is not tuple or any(
            type(item) is not ParameterDefinition for item in self.parameters
        ):
            raise SpecError("parameters must be an immutable tuple of ParameterDefinition records.")
        if tuple(item.name for item in self.parameters) != WEIGHT_NAMES:
            raise SpecError(
                "Parameter space v1 requires all eleven weights once, in canonical order."
            )

    def digest(self) -> str:
        return canonical_digest(self)


def _require_unshadowed(configuration: HeuristicConfiguration) -> None:
    if type(configuration) is not HeuristicConfiguration:
        raise SpecError("Expected an immutable heuristic configuration.")
    overrides = configuration.profile.weights
    if any(getattr(overrides, item.name) is not None for item in fields(overrides)):
        raise SpecError("Tunable weights must not be shadowed by profile overrides.")


def frozen_configuration_digest(
    space: ParameterSpace, configuration: HeuristicConfiguration
) -> str:
    """Hash all behavior settings after replacing only allowlisted weights."""
    _require_unshadowed(configuration)
    masked = replace(
        configuration.baseline.weights, **{item.name: 0.0 for item in space.parameters}
    )
    return replace(configuration, baseline=replace(configuration.baseline, weights=masked)).digest()


def encode_parameters(
    space: ParameterSpace,
    configuration: HeuristicConfiguration,
    *,
    frozen_configuration: HeuristicConfiguration,
) -> tuple[float, ...]:
    if frozen_configuration_digest(space, configuration) != frozen_configuration_digest(
        space, frozen_configuration
    ):
        raise SpecError("Candidate changed a frozen configuration setting.")
    coordinates: list[float] = []
    for parameter in space.parameters:
        value = cast(float, getattr(configuration.baseline.weights, parameter.name))
        if not parameter.lower <= value <= parameter.upper:
            raise SpecError(f"{parameter.name} is outside the parameter space.")
        coordinates.append((value - parameter.lower) / (parameter.upper - parameter.lower))
    return tuple(coordinates)


def bind_parameters(
    space: ParameterSpace,
    coordinates: tuple[float, ...],
    *,
    frozen_configuration: HeuristicConfiguration,
) -> HeuristicConfiguration:
    _require_unshadowed(frozen_configuration)
    values = expect_sequence(coordinates, context="coordinates", error_factory=SpecError)
    if len(values) != len(space.parameters):
        raise SpecError("Coordinate vector length must match the parameter space.")
    weights: dict[str, float] = {}
    for parameter, raw in zip(space.parameters, values, strict=True):
        coordinate = finite_float(raw, context=f"coordinate {parameter.name}")
        if not 0 <= coordinate <= 1:
            raise SpecError("Coordinates must lie in the inclusive interval [0, 1].")
        if coordinate == 0:
            value = parameter.lower
        elif coordinate == 1:
            value = parameter.upper
        else:
            value = parameter.lower + coordinate * (parameter.upper - parameter.lower)
        weights[parameter.name] = value
    return replace(
        frozen_configuration,
        baseline=replace(
            frozen_configuration.baseline,
            weights=replace(frozen_configuration.baseline.weights, **weights),
        ),
    )
