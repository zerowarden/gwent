"""Complete, immutable runtime values for the heuristic bot.

The codec accepts full snapshots only. Tuning bounds and study metadata belong
to evaluation; the engine validates types, finite numbers and policy selections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast, get_type_hints

from gwent_shared.extract import expect_finite_float, expect_mapping
from gwent_shared.json_payloads import canonical_digest, to_canonical

from gwent_engine.ai.baseline.policies import validate_policy_selection
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    ProfilePassOverrides,
    ProfileWeightOverrides,
)
from gwent_engine.ai.policy import (
    DEFAULT_BASELINE_CONFIG,
    RANKING_SCOPES,
    ActionBonusConfig,
    BaselineConfig,
    CandidateConfig,
    CandidateScoringConfig,
    EvaluationWeights,
    MulliganPolicyConfig,
    MulliganScoreWeights,
    PassConfig,
    PendingChoicePolicyConfig,
    PolicySelection,
    ProfileTuningConfig,
)
from gwent_engine.core.errors import DefinitionLoadError


class HeuristicConfigurationError(ValueError):
    """A runtime heuristic snapshot is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class HeuristicConfiguration:
    baseline: BaselineConfig = DEFAULT_BASELINE_CONFIG
    profile: BaseProfileDefinition = DEFAULT_BASE_PROFILE

    def __post_init__(self) -> None:
        baseline = _record(self.baseline, BaselineConfig, path="baseline", payload=False)
        profile = _record(self.profile, BaseProfileDefinition, path="profile", payload=False)
        if baseline.candidates.ranking_scope not in RANKING_SCOPES:
            raise HeuristicConfigurationError(
                f"baseline.candidates.ranking_scope must be one of {RANKING_SCOPES}."
            )
        try:
            validate_policy_selection(profile.policies, context="profile.policies")
        except DefinitionLoadError as error:
            raise HeuristicConfigurationError(str(error)) from error
        object.__setattr__(self, "baseline", baseline)
        object.__setattr__(self, "profile", profile)

    @classmethod
    def from_dict(cls, value: object) -> HeuristicConfiguration:
        mapping = _complete_mapping(value, {"baseline", "profile"}, path="configuration")
        return cls(
            baseline=_record(mapping["baseline"], BaselineConfig, path="baseline", payload=True),
            profile=_record(
                mapping["profile"], BaseProfileDefinition, path="profile", payload=True
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], to_canonical(self))

    def digest(self) -> str:
        """Behavior values only; profile display names do not select runtime policy."""
        payload = self.to_dict()
        profile = cast(dict[str, object], payload["profile"])
        del profile["profile_id"]
        return canonical_digest(payload)


# This is a closed codec for the existing configuration records, not a dynamic
# object loader. Their annotations are the authority for nested/primitive types.
_RECORD_TYPES: tuple[type[object], ...] = (
    BaselineConfig,
    EvaluationWeights,
    ActionBonusConfig,
    CandidateConfig,
    CandidateScoringConfig,
    PassConfig,
    ProfileTuningConfig,
    MulliganPolicyConfig,
    MulliganScoreWeights,
    PendingChoicePolicyConfig,
    BaseProfileDefinition,
    PolicySelection,
    ProfileWeightOverrides,
    ProfilePassOverrides,
)
_FIELD_TYPES: dict[type[object], dict[str, object]] = {
    record_type: cast(dict[str, object], get_type_hints(record_type))
    for record_type in _RECORD_TYPES
}


def _complete_mapping(value: object, names: set[str], *, path: str) -> dict[str, object]:
    mapping = dict(expect_mapping(value, context=path, error_factory=HeuristicConfigurationError))
    if set(mapping) != names:
        missing = sorted(names - set(mapping))
        unknown = sorted(set(mapping) - names)
        raise HeuristicConfigurationError(
            f"{path}: missing fields {missing}; unknown fields {unknown}."
        )
    return mapping


def _record[T](value: object, record_type: type[T], *, path: str, payload: bool) -> T:
    field_types = _FIELD_TYPES[record_type]
    if payload:
        mapping = _complete_mapping(value, set(field_types), path=path)
    else:
        if type(value) is not record_type:
            raise HeuristicConfigurationError(f"{path} must be {record_type.__name__}.")
        mapping = {name: cast(object, getattr(value, name)) for name in field_types}
    values = {
        name: _value(mapping[name], expected, path=f"{path}.{name}", payload=payload)
        for name, expected in field_types.items()
    }
    return record_type(**values)


def _value(value: object, expected: object, *, path: str, payload: bool) -> object:
    for record_type in _RECORD_TYPES:
        if expected is record_type:
            return _record(value, record_type, path=path, payload=payload)
    if expected in (float | None, int | None):
        if value is None:
            return None
        expected = float if expected == float | None else int
    if expected is float:
        return expect_finite_float(value, context=path, error_factory=HeuristicConfigurationError)
    if expected in (int, bool, str):
        if type(value) is not expected:
            raise HeuristicConfigurationError(f"{path} has an incompatible type.")
        if isinstance(value, str) and not value.strip():
            raise HeuristicConfigurationError(f"{path} must be non-blank.")
        return value
    raise HeuristicConfigurationError(f"Unsupported configuration field type: {expected!r}.")


__all__ = ["HeuristicConfiguration", "HeuristicConfigurationError"]
