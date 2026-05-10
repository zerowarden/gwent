from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import cast

import yaml
from gwent_shared.error_translation import translate_exception
from gwent_shared.extract import (
    expect_bool,
    expect_int,
    expect_optional_int,
    expect_optional_str,
    expect_str,
    require_field,
)
from gwent_shared.extract import (
    expect_mapping as shared_expect_mapping,
)
from gwent_shared.extract import (
    expect_sequence as shared_expect_sequence,
)

from gwent_engine.core.enums import FactionId
from gwent_engine.core.errors import DefinitionLoadError

NO_NONE_VALUES: frozenset[str] = frozenset()


def _safe_load_yaml(source: str) -> object:
    return cast(object, yaml.safe_load(source))


def load_yaml_document(path: Path) -> object:
    source = translate_exception(
        lambda: path.read_text(encoding="utf-8"),
        OSError,
        lambda exc: DefinitionLoadError(f"Failed to read YAML file {path}: {exc}"),
    )
    document = translate_exception(
        lambda: _safe_load_yaml(source),
        yaml.YAMLError,
        lambda exc: DefinitionLoadError(f"Failed to parse YAML file {path}: {exc}"),
    )

    return {} if document is None else document


def expect_mapping(value: object, *, context: str) -> Mapping[str, object]:
    return shared_expect_mapping(value, context=context, error_factory=DefinitionLoadError)


def expect_sequence(value: object, *, context: str) -> Sequence[object]:
    return shared_expect_sequence(value, context=context, error_factory=DefinitionLoadError)


def require_str(mapping: Mapping[str, object], field: str, *, context: str) -> str:
    return expect_str(
        require_field(mapping, field, context=context, error_factory=DefinitionLoadError),
        context=context,
        label=field,
        error_factory=DefinitionLoadError,
    )


def require_int(mapping: Mapping[str, object], field: str, *, context: str) -> int:
    return expect_int(
        require_field(mapping, field, context=context, error_factory=DefinitionLoadError),
        context=context,
        label=field,
        error_factory=DefinitionLoadError,
    )


def optional_str(mapping: Mapping[str, object], field: str, *, context: str) -> str | None:
    return expect_optional_str(
        mapping.get(field),
        context=context,
        label=field,
        error_factory=DefinitionLoadError,
    )


def optional_bool(mapping: Mapping[str, object], field: str, *, context: str) -> bool | None:
    value = mapping.get(field)
    if value is None:
        return None
    return expect_bool(
        value,
        context=context,
        label=field,
        error_factory=DefinitionLoadError,
    )


def optional_int(mapping: Mapping[str, object], field: str, *, context: str) -> int | None:
    return expect_optional_int(
        mapping.get(field),
        context=context,
        label=field,
        error_factory=DefinitionLoadError,
    )


def parse_enum[EnumT: Enum](
    enum_type: type[EnumT],
    raw_value: str,
    *,
    error_factory: Callable[[str], Exception],
) -> EnumT:
    return translate_exception(
        lambda: enum_type(raw_value),
        ValueError,
        lambda _exc: error_factory(raw_value),
    )


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
