from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path

from gwent_engine.ai.arena import bot_family
from gwent_engine.ai.baseline.profile_catalog import get_base_profile_definition
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_shared.extract import (
    expect_int,
    expect_mapping,
    expect_sequence,
    expect_str,
    optional_str_field,
    require_enum_field,
    require_int_field,
    require_sequence_field,
    require_str_field,
)
from gwent_shared.json_payloads import load_json_mapping

from gwent_evaluation.models import (
    SUPPORTED_SCHEMA_VERSION,
    AgentSpec,
    BotFamily,
    SchedulingPolicy,
    SuitePurpose,
    SuiteSpec,
)

type AgentResolver = Callable[[str], AgentSpec]

_AGENT_SPEC_FIELDS = frozenset({"schema_version", "agent_id", "family", "profile"})
_SUITE_SPEC_FIELDS = frozenset(
    {
        "schema_version",
        "suite_id",
        "purpose",
        "candidate",
        "opponents",
        "deck_pairs",
        "seeds",
        "scheduling",
        "action_budget",
    }
)
_AGENT_CATALOG_FIELDS = frozenset({"schema_version", "agents"})
_SUITE_CATALOG_FIELDS = frozenset({"schema_version", "suites"})


class SpecError(ValueError):
    """Raised when an evaluation spec document is malformed or unsupported."""


def load_agent_catalog(path: Path) -> dict[str, AgentSpec]:
    """Load all named benchmark participants from one catalog document."""

    document = _load_document(path)
    _reject_unknown_fields(document, _AGENT_CATALOG_FIELDS, context=str(path))
    _ = _require_schema_version(document, context=str(path))
    catalog: dict[str, AgentSpec] = {}
    for index, entry in enumerate(
        require_sequence_field(document, "agents", context=str(path), error_factory=SpecError)
    ):
        spec = parse_agent_spec(entry, context=f"{path}.agents[{index}]")
        if spec.agent_id in catalog:
            raise SpecError(f"{path} contains duplicate agent id {spec.agent_id!r}.")
        catalog[spec.agent_id] = spec
    if not catalog:
        raise SpecError(f"{path} must declare at least one agent.")
    return catalog


def load_suite_catalog(
    path: Path,
    *,
    agents: Mapping[str, AgentSpec],
) -> dict[str, SuiteSpec]:
    """Load all suites from one catalog, resolving agents by catalog id."""

    document = _load_document(path)
    _reject_unknown_fields(document, _SUITE_CATALOG_FIELDS, context=str(path))
    _ = _require_schema_version(document, context=str(path))
    resolve_agent = _catalog_agent_resolver(agents)
    catalog: dict[str, SuiteSpec] = {}
    for index, entry in enumerate(
        require_sequence_field(document, "suites", context=str(path), error_factory=SpecError)
    ):
        suite = parse_suite_spec(
            entry,
            resolve_agent=resolve_agent,
            context=f"{path}.suites[{index}]",
        )
        if suite.suite_id in catalog:
            raise SpecError(f"{path} contains duplicate suite id {suite.suite_id!r}.")
        catalog[suite.suite_id] = suite
    if not catalog:
        raise SpecError(f"{path} must declare at least one suite.")
    return catalog


def parse_agent_spec(payload: object, *, context: str = "<agent spec>") -> AgentSpec:
    mapping = expect_mapping(payload, context=context, error_factory=SpecError)
    _reject_unknown_fields(mapping, _AGENT_SPEC_FIELDS, context=context)
    schema_version = _require_schema_version(mapping, context=context)
    agent_id = require_str_field(mapping, "agent_id", context=context, error_factory=SpecError)
    family = _require_enum_field(mapping, "family", BotFamily, context=context)
    profile = optional_str_field(mapping, "profile", context=context, error_factory=SpecError)
    return AgentSpec(
        schema_version=schema_version,
        agent_id=agent_id,
        family=family,
        profile=_resolve_agent_profile(family, profile, context=context),
    )


def parse_suite_spec(
    payload: object,
    *,
    resolve_agent: AgentResolver,
    context: str = "<suite spec>",
) -> SuiteSpec:
    mapping = expect_mapping(payload, context=context, error_factory=SpecError)
    _reject_unknown_fields(mapping, _SUITE_SPEC_FIELDS, context=context)
    schema_version = _require_schema_version(mapping, context=context)
    suite_id = require_str_field(mapping, "suite_id", context=context, error_factory=SpecError)
    purpose = _require_enum_field(mapping, "purpose", SuitePurpose, context=context)
    deck_pairs = _require_deck_pairs(mapping, context=context)
    seeds = _require_seeds(mapping, context=context)
    scheduling = _require_enum_field(mapping, "scheduling", SchedulingPolicy, context=context)
    action_budget = _require_positive_int(mapping, "action_budget", context=context)
    candidate = _resolve_agent_reference(mapping, "candidate", resolve_agent, context=context)
    opponents = _resolve_opponent_references(mapping, resolve_agent, context=context)
    return SuiteSpec(
        schema_version=schema_version,
        suite_id=suite_id,
        purpose=purpose,
        candidate=candidate,
        opponents=opponents,
        deck_pairs=deck_pairs,
        seeds=seeds,
        scheduling=scheduling,
        action_budget=action_budget,
        observation_contract_version=OBSERVATION_CONTRACT_VERSION,
    )


def _load_document(path: Path) -> Mapping[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecError(f"Cannot read spec file {path}: {error}.") from error
    return load_json_mapping(text, context=str(path), error_factory=SpecError)


def _catalog_agent_resolver(agents: Mapping[str, AgentSpec]) -> AgentResolver:
    def resolve(agent_id: str) -> AgentSpec:
        try:
            return agents[agent_id]
        except KeyError as error:
            raise SpecError(f"Unknown agent id: {agent_id!r}.") from error

    return resolve


def _reject_unknown_fields(
    mapping: Mapping[str, object],
    allowed: frozenset[str],
    *,
    context: str,
) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        formatted = ", ".join(repr(field) for field in unknown)
        raise SpecError(f"{context} contains unknown field(s): {formatted}.")


def _require_schema_version(mapping: Mapping[str, object], *, context: str) -> int:
    schema_version = require_int_field(
        mapping,
        "schema_version",
        context=context,
        error_factory=SpecError,
    )
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise SpecError(
            f"{context} schema_version must be {SUPPORTED_SCHEMA_VERSION}, "
            + f"found {schema_version}."
        )
    return schema_version


def _require_enum_field[EnumType: Enum](
    mapping: Mapping[str, object],
    field: str,
    enum_type: type[EnumType],
    *,
    context: str,
) -> EnumType:
    return require_enum_field(mapping, field, enum_type, context=context, error_factory=SpecError)


def _resolve_agent_profile(
    family: BotFamily,
    profile: str | None,
    *,
    context: str,
) -> str | None:
    if profile is None:
        return None
    if not bot_family(family).accepts_profile:
        raise SpecError(f"{context} family {family.value!r} does not support a profile override.")
    try:
        return get_base_profile_definition(profile).profile_id
    except ValueError as error:
        raise SpecError(f"{context} profile {profile!r} is not a recognized profile.") from error


def _resolve_agent_reference(
    mapping: Mapping[str, object],
    field: str,
    resolve_agent: AgentResolver,
    *,
    context: str,
) -> AgentSpec:
    reference = require_str_field(mapping, field, context=context, error_factory=SpecError)
    return _resolve_agent(reference, resolve_agent, context=context)


def _resolve_opponent_references(
    mapping: Mapping[str, object],
    resolve_agent: AgentResolver,
    *,
    context: str,
) -> tuple[AgentSpec, ...]:
    references = _require_nonempty_str_sequence(mapping, "opponents", context=context)
    _reject_duplicates(references, field="opponents", context=context)
    return tuple(
        _resolve_agent(reference, resolve_agent, context=context) for reference in references
    )


def _resolve_agent(
    reference: str,
    resolve_agent: AgentResolver,
    *,
    context: str,
) -> AgentSpec:
    try:
        return resolve_agent(reference)
    except SpecError as error:
        raise SpecError(
            f"{context}: cannot resolve agent reference {reference!r}: {error}"
        ) from error


def _require_nonempty_str_sequence(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> tuple[str, ...]:
    raw_items = require_sequence_field(mapping, field, context=context, error_factory=SpecError)
    if not raw_items:
        raise SpecError(f"{context} field {field!r} must not be empty.")
    return tuple(
        expect_str(item, context=f"{context}.{field}[{index}]", error_factory=SpecError)
        for index, item in enumerate(raw_items)
    )


def _require_deck_pairs(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> tuple[tuple[str, str], ...]:
    raw_pairs = require_sequence_field(
        mapping,
        "deck_pairs",
        context=context,
        error_factory=SpecError,
    )
    if not raw_pairs:
        raise SpecError(f"{context} field 'deck_pairs' must not be empty.")
    pairs: list[tuple[str, str]] = []
    for index, raw_pair in enumerate(raw_pairs):
        pair_context = f"{context}.deck_pairs[{index}]"
        pair = expect_sequence(raw_pair, context=pair_context, error_factory=SpecError)
        if len(pair) != 2:
            raise SpecError(f"{pair_context} must contain exactly two deck ids.")
        pairs.append(
            (
                expect_str(pair[0], context=f"{pair_context}[0]", error_factory=SpecError),
                expect_str(pair[1], context=f"{pair_context}[1]", error_factory=SpecError),
            )
        )
    result = tuple(pairs)
    _reject_duplicates(result, field="deck_pairs", context=context)
    return result


def _require_seeds(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> tuple[int, ...]:
    raw_seeds = require_sequence_field(mapping, "seeds", context=context, error_factory=SpecError)
    if not raw_seeds:
        raise SpecError(f"{context} field 'seeds' must not be empty.")
    seeds = tuple(
        expect_int(seed, context=f"{context}.seeds[{index}]", error_factory=SpecError)
        for index, seed in enumerate(raw_seeds)
    )
    _reject_duplicates(seeds, field="seeds", context=context)
    return seeds


def _require_positive_int(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> int:
    value = require_int_field(mapping, field, context=context, error_factory=SpecError)
    if value <= 0:
        raise SpecError(f"{context} field {field!r} must be positive, found {value}.")
    return value


def _reject_duplicates(
    values: Sequence[object],
    *,
    field: str,
    context: str,
) -> None:
    if len(set(values)) != len(values):
        raise SpecError(f"{context} field {field!r} must not contain duplicates.")
