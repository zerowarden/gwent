from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import cast

import yaml
from gwent_shared.extract import (
    expect_mapping as shared_expect_mapping,
)
from gwent_shared.extract import (
    expect_sequence as shared_expect_sequence,
)
from gwent_shared.extract import (
    optional_bool_field,
    optional_int_field,
    optional_str_field,
    require_int_field,
    require_str_field,
)

from gwent_engine.core.enums import FactionId
from gwent_engine.core.errors import DefinitionLoadError

NO_NONE_VALUES: frozenset[str] = frozenset()


def load_yaml_document(path: Path) -> object:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DefinitionLoadError(f"Failed to read YAML file {path}: {exc}") from exc
    try:
        document = cast(object, yaml.safe_load(source))
    except yaml.YAMLError as exc:
        raise DefinitionLoadError(f"Failed to parse YAML file {path}: {exc}") from exc

    return {} if document is None else document


def expect_mapping(value: object, *, context: str) -> Mapping[str, object]:
    return shared_expect_mapping(value, context=context, error_factory=DefinitionLoadError)


def expect_sequence(value: object, *, context: str) -> Sequence[object]:
    return shared_expect_sequence(value, context=context, error_factory=DefinitionLoadError)


def require_str(mapping: Mapping[str, object], field: str, *, context: str) -> str:
    return require_str_field(mapping, field, context=context, error_factory=DefinitionLoadError)


def require_int(mapping: Mapping[str, object], field: str, *, context: str) -> int:
    return require_int_field(mapping, field, context=context, error_factory=DefinitionLoadError)


def optional_str(mapping: Mapping[str, object], field: str, *, context: str) -> str | None:
    return optional_str_field(mapping, field, context=context, error_factory=DefinitionLoadError)


def optional_bool(mapping: Mapping[str, object], field: str, *, context: str) -> bool | None:
    return optional_bool_field(mapping, field, context=context, error_factory=DefinitionLoadError)


def optional_int(mapping: Mapping[str, object], field: str, *, context: str) -> int | None:
    return optional_int_field(mapping, field, context=context, error_factory=DefinitionLoadError)


def parse_enum[EnumT: Enum](
    enum_type: type[EnumT],
    raw_value: str,
    *,
    error_factory: Callable[[str], Exception],
) -> EnumT:
    try:
        return enum_type(raw_value)
    except ValueError as exc:
        raise error_factory(raw_value) from exc


def parse_faction_id(raw_value: str) -> FactionId:
    return parse_enum(
        FactionId,
        raw_value,
        error_factory=lambda value: DefinitionLoadError(f"Unknown faction id: {value!r}"),
    )


def parse_optional_enum[EnumT: Enum](
    enum_type: type[EnumT],
    raw_value: str | None,
    *,
    error_factory: Callable[[str], Exception],
    none_values: frozenset[str] = NO_NONE_VALUES,
) -> EnumT | None:
    if raw_value is None or raw_value in none_values:
        return None
    return parse_enum(enum_type, raw_value, error_factory=error_factory)
