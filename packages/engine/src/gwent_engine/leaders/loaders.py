from pathlib import Path

from gwent_engine.core import (
    AbilityKind,
    LeaderAbilityKind,
    LeaderAbilityMode,
    LeaderSelectionMode,
    Row,
)
from gwent_engine.core.errors import (
    DefinitionLoadError,
    UnknownAbilityKindError,
    UnknownLeaderAbilityKindError,
)
from gwent_engine.core.ids import LeaderId
from gwent_engine.core.yaml_parsing import (
    expect_mapping,
    expect_sequence,
    load_yaml_document,
    optional_bool,
    optional_int,
    optional_str,
    parse_enum,
    parse_faction_id,
    parse_optional_enum,
    require_str,
)
from gwent_engine.leaders.abilities import SUPPORTED_LEADER_ABILITY_KINDS
from gwent_engine.leaders.models import LeaderDefinition


def load_leader_definitions(path: Path) -> tuple[LeaderDefinition, ...]:
    document = expect_mapping(load_yaml_document(path), context=f"{path} root")
    raw_leaders = expect_sequence(document.get("leaders"), context=f"{path} leaders")
    return tuple(_build_leader_definition(raw_leader, path=path) for raw_leader in raw_leaders)


def _build_leader_definition(raw_leader: object, *, path: Path) -> LeaderDefinition:
    entry = expect_mapping(raw_leader, context=f"{path} leader entry")
    context = f"{path} leader {entry.get('leader_id', '<missing>')!r}"
    cards_to_draw = optional_int(entry, "cards_to_draw", context=context) or 0
    ability_kind = _parse_leader_ability_kind(require_str(entry, "ability_kind", context=context))
    if ability_kind not in SUPPORTED_LEADER_ABILITY_KINDS:
        raise DefinitionLoadError(
            f"{context} declares unsupported leader ability kind {ability_kind!r}."
        )
    return LeaderDefinition(
        leader_id=LeaderId(require_str(entry, "leader_id", context=context)),
        name=require_str(entry, "name", context=context),
        faction=parse_faction_id(require_str(entry, "faction", context=context)),
        ability_kind=ability_kind,
        ability_mode=_parse_leader_ability_mode(
            require_str(entry, "ability_mode", context=context)
        ),
        uses_per_match=optional_int(entry, "uses_per_match", context=context) or 1,
        selection_mode=_parse_optional_selection_mode(
            optional_str(entry, "selection_mode", context=context),
            context=context,
        ),
        weather_ability_kind=_parse_optional_weather_ability_kind(
            optional_str(entry, "weather_kind", context=context)
        ),
        affected_row=_parse_optional_row(
            optional_str(entry, "affected_row", context=context),
            context=context,
        ),
        blocked_if_row_already_affected_by_horn=(
            optional_bool(entry, "blocked_if_row_already_affected_by_horn", context=context)
            or False
        ),
        minimum_opponent_row_total=(
            optional_int(entry, "minimum_opponent_row_total", context=context) or 0
        ),
        cards_to_draw=cards_to_draw,
        hand_discard_count=optional_int(entry, "hand_discard_count", context=context) or 0,
        deck_pick_count=optional_int(entry, "deck_pick_count", context=context) or 0,
        reveal_count=optional_int(entry, "reveal_count", context=context) or 0,
        rule_text=optional_str(entry, "rule_text", context=context),
    )


def _parse_leader_ability_kind(raw_value: str) -> LeaderAbilityKind:
    return parse_enum(
        LeaderAbilityKind,
        raw_value,
        error_factory=UnknownLeaderAbilityKindError,
    )


def _parse_leader_ability_mode(raw_value: str) -> LeaderAbilityMode:
    return parse_enum(
        LeaderAbilityMode,
        raw_value,
        error_factory=lambda value: DefinitionLoadError(f"Unknown leader ability mode: {value!r}"),
    )


def _parse_optional_selection_mode(
    raw_value: str | None,
    *,
    context: str,
) -> LeaderSelectionMode | None:
    return parse_optional_enum(
        LeaderSelectionMode,
        raw_value,
        error_factory=lambda value: DefinitionLoadError(
            f"{context} has unknown selection_mode {value!r}."
        ),
    )


def _parse_optional_weather_ability_kind(
    raw_value: str | None,
) -> AbilityKind | None:
    return parse_optional_enum(
        AbilityKind,
        raw_value,
        error_factory=UnknownAbilityKindError,
        none_values=frozenset({"any_weather"}),
    )


def _parse_optional_row(raw_value: str | None, *, context: str) -> Row | None:
    return parse_optional_enum(
        Row,
        raw_value,
        error_factory=lambda value: DefinitionLoadError(f"{context} has unknown row {value!r}."),
    )
