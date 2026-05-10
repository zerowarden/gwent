from collections.abc import Mapping
from pathlib import Path

from gwent_engine.cards.models import CardDefinition
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.errors import (
    DefinitionLoadError,
    UnknownAbilityKindError,
)
from gwent_engine.core.ids import CardDefinitionId
from gwent_engine.core.yaml_parsing import (
    expect_mapping,
    expect_sequence,
    load_yaml_document,
    optional_bool,
    optional_int,
    optional_str,
    parse_enum,
    parse_faction_id,
    require_int,
    require_str,
)


def load_card_definitions(path: Path) -> tuple[CardDefinition, ...]:
    document = expect_mapping(load_yaml_document(path), context=f"{path} root")
    raw_cards = expect_sequence(document.get("cards"), context=f"{path} cards")
    return tuple(_build_card_definition(raw_card, path=path) for raw_card in raw_cards)


def _build_card_definition(raw_card: object, *, path: Path) -> CardDefinition:
    entry = expect_mapping(raw_card, context=f"{path} card entry")
    context = f"{path} card {entry.get('definition_id', '<missing>')!r}"
    return CardDefinition(
        definition_id=CardDefinitionId(require_str(entry, "definition_id", context=context)),
        name=require_str(entry, "name", context=context),
        faction=parse_faction_id(require_str(entry, "faction", context=context)),
        card_type=_parse_card_type(require_str(entry, "card_type", context=context)),
        base_strength=require_int(entry, "base_strength", context=context),
        allowed_rows=_parse_rows(entry.get("allowed_rows"), context=context),
        ability_kinds=_parse_ability_kinds(entry.get("ability_kinds"), context=context),
        musters_group=optional_str(entry, "musters_group", context=context),
        muster_group=optional_str(entry, "muster_group", context=context),
        bond_group=optional_str(entry, "bond_group", context=context),
        transforms_into_definition_id=_optional_card_definition_id(
            entry,
            "transforms_into_definition_id",
            context=context,
        ),
        avenger_summon_definition_id=_optional_card_definition_id(
            entry,
            "avenger_summon_definition_id",
            context=context,
        ),
        generated_only=optional_bool(entry, "generated_only", context=context) or False,
        max_copies_per_deck=optional_int(entry, "max_copies_per_deck", context=context),
        is_hero=optional_bool(entry, "is_hero", context=context) or False,
        rule_text=optional_str(entry, "rule_text", context=context),
    )


def _parse_card_type(raw_value: str) -> CardType:
    return parse_enum(
        CardType,
        raw_value,
        error_factory=lambda value: DefinitionLoadError(f"Unknown card_type: {value!r}"),
    )


def _parse_rows(raw_value: object, *, context: str) -> tuple[Row, ...]:
    raw_rows = expect_sequence(raw_value, context=f"{context} allowed_rows")
    rows: list[Row] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, str):
            raise DefinitionLoadError(f"{context} allowed_rows entries must be strings.")
        rows.append(
            parse_enum(
                Row,
                raw_row,
                error_factory=lambda value: DefinitionLoadError(
                    f"{context} has unknown row {value!r}."
                ),
            )
        )
    return tuple(rows)


def _parse_ability_kinds(raw_value: object, *, context: str) -> tuple[AbilityKind, ...]:
    if raw_value is None:
        return ()
    raw_abilities = expect_sequence(raw_value, context=f"{context} ability_kinds")
    raw_ability_values: list[str] = []
    for raw_ability in raw_abilities:
        if not isinstance(raw_ability, str):
            raise DefinitionLoadError(f"{context} ability_kinds entries must be strings.")
        raw_ability_values.append(raw_ability)
    return tuple(
        parse_enum(
            AbilityKind,
            raw_ability,
            error_factory=UnknownAbilityKindError,
        )
        for raw_ability in raw_ability_values
    )


def _optional_card_definition_id(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> CardDefinitionId | None:
    raw_value = optional_str(mapping, field, context=context)
    if raw_value is None:
        return None
    return CardDefinitionId(raw_value)


__all__ = ["load_card_definitions"]
