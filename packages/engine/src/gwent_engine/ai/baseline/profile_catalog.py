from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from gwent_shared.error_translation import translate_mapping_key
from gwent_shared.extract import (
    expect_mapping,
    optional_int_field,
    require_mapping_field,
    require_str_field,
)

from gwent_engine.ai.baseline.policies.registry import POLICY_CATALOG
from gwent_engine.ai.policy import (
    AGGRESSIVE_LEADER_POLICY_ID,
    OPPORTUNISTIC_SCORCH_POLICY_ID,
    PolicySelection,
)
from gwent_engine.core.errors import DefinitionLoadError
from gwent_engine.core.yaml_parsing import load_yaml_document
from gwent_engine.resources import bundled_data_path

DEFAULT_BASE_PROFILES_PATH = bundled_data_path("heuristic_profiles.yaml")


@dataclass(frozen=True, slots=True)
class ProfileWeightOverrides:
    immediate_points: float | None = None
    card_advantage: float | None = None
    remaining_hand_value: float | None = None
    leader_value: float | None = None
    overcommit_penalty: float | None = None
    exact_finish_bonus: float | None = None


@dataclass(frozen=True, slots=True)
class ProfilePassOverrides:
    safe_lead_margin: int | None = None
    elimination_safe_lead_margin: int | None = None
    estimated_opponent_tempo_per_card: int | None = None
    elimination_estimated_opponent_tempo_per_card: int | None = None


@dataclass(frozen=True, slots=True)
class BaseProfileDefinition:
    """Stable base-profile definition.

    A base profile carries long-lived policy defaults plus a small set of
    weight and pass-threshold overrides. Tactical adaptation is selected in
    code, not authored as per-profile mode variants.
    """

    profile_id: str
    policies: PolicySelection
    weights: ProfileWeightOverrides = field(default_factory=ProfileWeightOverrides)
    pass_overrides: ProfilePassOverrides = field(default_factory=ProfilePassOverrides)


DEFAULT_BASE_PROFILE = BaseProfileDefinition(
    profile_id="neutral",
    policies=PolicySelection(
        scorch=OPPORTUNISTIC_SCORCH_POLICY_ID,
        leader=AGGRESSIVE_LEADER_POLICY_ID,
    ),
)


def load_base_profiles(
    path: Path,
) -> dict[str, BaseProfileDefinition]:
    """Load authored base profiles from YAML."""

    context = f"{path} root"
    document = expect_mapping(
        load_yaml_document(path),
        context=context,
        error_factory=DefinitionLoadError,
    )
    raw_profiles = require_mapping_field(
        document,
        "profiles",
        context=context,
        error_factory=DefinitionLoadError,
    )
    profiles: dict[str, BaseProfileDefinition] = {}
    for raw_profile_id, raw_value in raw_profiles.items():
        if not raw_profile_id.strip():
            raise DefinitionLoadError(f"{context}.profiles keys must be non-blank strings.")
        profile_id = raw_profile_id.strip()
        profile_context = f"{context}.profiles.{profile_id}"
        profile_mapping = expect_mapping(
            raw_value,
            context=profile_context,
            error_factory=DefinitionLoadError,
        )
        profiles[profile_id] = BaseProfileDefinition(
            profile_id=profile_id,
            policies=_parse_required_policy_selection(
                profile_mapping,
                field="policies",
                context=profile_context,
            ),
            weights=_parse_weight_overrides(profile_mapping, context=profile_context),
            pass_overrides=_parse_pass_overrides(profile_mapping, context=profile_context),
        )
    return profiles


@lru_cache(maxsize=1)
def load_default_base_profiles() -> dict[str, BaseProfileDefinition]:
    return load_base_profiles(DEFAULT_BASE_PROFILES_PATH)


def available_base_profile_ids() -> tuple[str, ...]:
    return tuple(sorted(load_default_base_profiles()))


def get_base_profile_definition(profile_id: str) -> BaseProfileDefinition:
    return translate_mapping_key(
        load_default_base_profiles(),
        profile_id,
        lambda _profile_id: ValueError(f"Unknown profile id: {profile_id!r}"),
    )


def resolve_base_profile(profile_id: str | None) -> BaseProfileDefinition:
    """Resolve an optional profile override to the canonical default profile."""

    if profile_id is None:
        return DEFAULT_BASE_PROFILE
    return get_base_profile_definition(profile_id)


def profile_bot_display_name(base_name: str, profile: BaseProfileDefinition) -> str:
    """Display names stay stable for the default profile and name overrides otherwise."""

    if profile.profile_id == DEFAULT_BASE_PROFILE.profile_id:
        return base_name
    return f"{base_name}[{profile.profile_id}]"


def _parse_required_policy_selection(
    mapping: object,
    *,
    field: str,
    context: str,
) -> PolicySelection:
    selection_mapping = require_mapping_field(
        expect_mapping(mapping, context=context, error_factory=DefinitionLoadError),
        field,
        context=context,
        error_factory=DefinitionLoadError,
    )
    return _policy_selection_from_mapping(selection_mapping, context=f"{context}.{field}")


def _policy_selection_from_mapping(
    mapping: object,
    *,
    context: str,
) -> PolicySelection:
    selection_mapping = expect_mapping(
        mapping,
        context=context,
        error_factory=DefinitionLoadError,
    )
    selection = PolicySelection(
        scorch=require_str_field(
            selection_mapping,
            "scorch_policy",
            context=context,
            error_factory=DefinitionLoadError,
        ),
        leader=require_str_field(
            selection_mapping,
            "leader_policy",
            context=context,
            error_factory=DefinitionLoadError,
        ),
    )
    POLICY_CATALOG.validate(selection, context=context)
    return selection


def _parse_weight_overrides(
    mapping: dict[str, object] | object,
    *,
    context: str,
) -> ProfileWeightOverrides:
    profile_mapping = expect_mapping(mapping, context=context, error_factory=DefinitionLoadError)
    raw_value = profile_mapping.get("weights")
    if raw_value is None:
        return ProfileWeightOverrides()
    weight_mapping = expect_mapping(
        raw_value,
        context=f"{context}.weights",
        error_factory=DefinitionLoadError,
    )
    return ProfileWeightOverrides(
        immediate_points=_optional_float_field(
            weight_mapping,
            "immediate_points",
            context=f"{context}.weights",
        ),
        card_advantage=_optional_float_field(
            weight_mapping,
            "card_advantage",
            context=f"{context}.weights",
        ),
        remaining_hand_value=_optional_float_field(
            weight_mapping,
            "remaining_hand_value",
            context=f"{context}.weights",
        ),
        leader_value=_optional_float_field(
            weight_mapping,
            "leader_value",
            context=f"{context}.weights",
        ),
        overcommit_penalty=_optional_float_field(
            weight_mapping,
            "overcommit_penalty",
            context=f"{context}.weights",
        ),
        exact_finish_bonus=_optional_float_field(
            weight_mapping,
            "exact_finish_bonus",
            context=f"{context}.weights",
        ),
    )


def _parse_pass_overrides(
    mapping: dict[str, object] | object,
    *,
    context: str,
) -> ProfilePassOverrides:
    profile_mapping = expect_mapping(mapping, context=context, error_factory=DefinitionLoadError)
    raw_value = profile_mapping.get("pass")
    if raw_value is None:
        return ProfilePassOverrides()
    pass_mapping = expect_mapping(
        raw_value,
        context=f"{context}.pass",
        error_factory=DefinitionLoadError,
    )
    return ProfilePassOverrides(
        safe_lead_margin=optional_int_field(
            pass_mapping,
            "safe_lead_margin",
            context=f"{context}.pass",
            error_factory=DefinitionLoadError,
        ),
        elimination_safe_lead_margin=optional_int_field(
            pass_mapping,
            "elimination_safe_lead_margin",
            context=f"{context}.pass",
            error_factory=DefinitionLoadError,
        ),
        estimated_opponent_tempo_per_card=optional_int_field(
            pass_mapping,
            "estimated_opponent_tempo_per_card",
            context=f"{context}.pass",
            error_factory=DefinitionLoadError,
        ),
        elimination_estimated_opponent_tempo_per_card=optional_int_field(
            pass_mapping,
            "elimination_estimated_opponent_tempo_per_card",
            context=f"{context}.pass",
            error_factory=DefinitionLoadError,
        ),
    )


def _optional_float_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> float | None:
    raw_value = mapping.get(field)
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise DefinitionLoadError(f"{context} field {field!r} must be numeric if provided.")
    return float(raw_value)
