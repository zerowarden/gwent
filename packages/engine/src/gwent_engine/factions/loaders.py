"""Load faction definitions from YAML."""

from pathlib import Path

from gwent_engine.core import PassiveKind
from gwent_engine.core.errors import UnknownPassiveKindError
from gwent_engine.core.yaml_parsing import (
    expect_mapping,
    expect_sequence,
    load_yaml_document,
    parse_enum,
    parse_faction_id,
    require_str,
)
from gwent_engine.factions.models import FactionDefinition


def load_faction_definitions(path: Path) -> tuple[FactionDefinition, ...]:
    document = expect_mapping(load_yaml_document(path), context=f"{path} root")
    raw_factions = expect_sequence(document.get("factions"), context=f"{path} factions")
    return tuple(_build_faction_definition(raw_faction, path=path) for raw_faction in raw_factions)


def _build_faction_definition(raw_faction: object, *, path: Path) -> FactionDefinition:
    entry = expect_mapping(raw_faction, context=f"{path} faction entry")
    context = f"{path} faction {entry.get('faction_id', '<missing>')!r}"
    return FactionDefinition(
        faction_id=parse_faction_id(require_str(entry, "faction_id", context=context)),
        name=require_str(entry, "name", context=context),
        passive_kind=_parse_passive_kind(require_str(entry, "passive_kind", context=context)),
        passive_description=require_str(entry, "passive_description", context=context),
    )


def _parse_passive_kind(raw_value: str) -> PassiveKind:
    return parse_enum(
        PassiveKind,
        raw_value,
        error_factory=UnknownPassiveKindError,
    )
