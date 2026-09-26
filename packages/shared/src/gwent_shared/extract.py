from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import cast

ErrorFactory = Callable[[str], Exception]

NO_NONE_VALUES: frozenset[str] = frozenset()

__all__ = [
    "expect_bool",
    "expect_constructor",
    "expect_constructor_sequence",
    "expect_enum",
    "expect_int",
    "expect_mapping",
    "expect_optional_bool",
    "expect_optional_constructor",
    "expect_optional_enum",
    "expect_optional_int",
    "expect_optional_str",
    "expect_pair_sequence",
    "expect_sequence",
    "expect_str",
    "optional_bool_field",
    "optional_constructor_field",
    "optional_enum_field",
    "optional_int_field",
    "optional_str_field",
    "require_bool_field",
    "require_constructor_field",
    "require_enum_field",
    "require_field",
    "require_int_field",
    "require_mapping_field",
    "require_pair_sequence_field",
    "require_sequence_field",
    "require_str_field",
    "require_str_sequence_field",
    "stringify",
    "stringify_list",
    "stringify_optional",
]


def require_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> object:
    value = mapping.get(field)
    if value is None:
        raise error_factory(f"{context} field {field!r} is required.")
    return value


def require_mapping_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> Mapping[str, object]:
    return expect_mapping(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=f"{context}.{field}",
        error_factory=error_factory,
    )


def require_sequence_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> Sequence[object]:
    return expect_sequence(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=f"{context}.{field}",
        error_factory=error_factory,
    )


def require_str_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> str:
    return expect_str(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def require_int_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> int:
    return expect_int(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def require_bool_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> bool:
    return expect_bool(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def require_constructor_field[ValueT](
    mapping: Mapping[str, object],
    field: str,
    constructor: Callable[[str], ValueT],
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> ValueT:
    return expect_constructor(
        require_field(mapping, field, context=context, error_factory=error_factory),
        constructor,
        context=context,
        label=field,
        error_factory=error_factory,
    )


def optional_constructor_field[ValueT](
    mapping: Mapping[str, object],
    field: str,
    constructor: Callable[[str], ValueT],
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> ValueT | None:
    return expect_optional_constructor(
        mapping.get(field),
        constructor,
        context=context,
        label=field,
        error_factory=error_factory,
    )


def expect_constructor[ValueT](
    value: object,
    constructor: Callable[[str], ValueT],
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> ValueT:
    return constructor(expect_str(value, context=context, label=label, error_factory=error_factory))


def expect_optional_constructor[ValueT](
    value: object | None,
    constructor: Callable[[str], ValueT],
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> ValueT | None:
    raw_value = expect_optional_str(
        value, context=context, label=label, error_factory=error_factory
    )
    if raw_value is None:
        return None
    return constructor(raw_value)


def expect_constructor_sequence[ValueT](
    value: object,
    constructor: Callable[[str], ValueT],
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> tuple[ValueT, ...]:
    items = expect_sequence(value, context=context, error_factory=error_factory)
    return tuple(
        expect_constructor(
            item,
            constructor,
            context=f"{context}[{index}]",
            error_factory=error_factory,
        )
        for index, item in enumerate(items)
    )


def require_str_sequence_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> tuple[str, ...]:
    raw_sequence = require_sequence_field(
        mapping,
        field,
        context=context,
        error_factory=error_factory,
    )
    return tuple(
        expect_str(
            item,
            context=f"{context}.{field}[{index}]",
            error_factory=error_factory,
        )
        for index, item in enumerate(raw_sequence)
    )


def optional_str_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> str | None:
    return expect_optional_str(
        mapping.get(field),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def optional_int_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> int | None:
    return expect_optional_int(
        mapping.get(field),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def expect_optional_bool(
    value: object | None,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> bool | None:
    if value is None:
        return None
    return expect_bool(value, context=context, label=label, error_factory=error_factory)


def optional_bool_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> bool | None:
    return expect_optional_bool(
        mapping.get(field),
        context=context,
        label=field,
        error_factory=error_factory,
    )


def expect_pair_sequence(
    value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> tuple[tuple[object, object], ...]:
    pairs: list[tuple[object, object]] = []
    items = expect_sequence(value, context=context, error_factory=error_factory)
    for index, item in enumerate(items):
        pair_context = f"{context}[{index}]"
        pair = expect_sequence(item, context=pair_context, error_factory=error_factory)
        if len(pair) != 2:
            raise error_factory(f"{pair_context} must contain exactly two entries.")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)


def require_pair_sequence_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> tuple[tuple[object, object], ...]:
    return expect_pair_sequence(
        require_field(mapping, field, context=context, error_factory=error_factory),
        context=f"{context}.{field}",
        error_factory=error_factory,
    )


def expect_mapping(
    value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    raise error_factory(f"{context} must be a mapping.")


def expect_sequence(
    value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    raise error_factory(f"{context} must be a sequence.")


def expect_str(
    value: object,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> str:
    if not isinstance(value, str):
        raise error_factory(_message(context, label, "must be a string"))
    stripped = value.strip()
    if not stripped:
        raise error_factory(_message(context, label, "cannot be blank"))
    return stripped


def expect_int(
    value: object,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_factory(_message(context, label, "must be an integer"))
    return value


def expect_enum[EnumType: Enum](
    value: object,
    enum_type: type[EnumType],
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> EnumType:
    raw_value = expect_str(value, context=context, label=label, error_factory=error_factory)
    try:
        return enum_type(raw_value)
    except ValueError as error:
        allowed = ", ".join(repr(cast(object, member.value)) for member in enum_type)
        raise error_factory(_message(context, label, f"must be one of: {allowed}")) from error


def require_enum_field[EnumType: Enum](
    mapping: Mapping[str, object],
    field: str,
    enum_type: type[EnumType],
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> EnumType:
    return expect_enum(
        require_field(mapping, field, context=context, error_factory=error_factory),
        enum_type,
        context=context,
        label=field,
        error_factory=error_factory,
    )


def expect_optional_enum[EnumType: Enum](
    value: object | None,
    enum_type: type[EnumType],
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
    none_values: frozenset[str] = NO_NONE_VALUES,
) -> EnumType | None:
    raw_value = expect_optional_str(
        value, context=context, label=label, error_factory=error_factory
    )
    if raw_value is None or raw_value in none_values:
        return None
    return expect_enum(
        raw_value,
        enum_type,
        context=context,
        label=label,
        error_factory=error_factory,
    )


def optional_enum_field[EnumType: Enum](
    mapping: Mapping[str, object],
    field: str,
    enum_type: type[EnumType],
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
    none_values: frozenset[str] = NO_NONE_VALUES,
) -> EnumType | None:
    return expect_optional_enum(
        mapping.get(field),
        enum_type,
        context=context,
        label=field,
        error_factory=error_factory,
        none_values=none_values,
    )


def expect_bool(
    value: object,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> bool:
    if not isinstance(value, bool):
        raise error_factory(_message(context, label, "must be a boolean"))
    return value


def expect_optional_str(
    value: object | None,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise error_factory(_message(context, label, "must be a string if provided"))
    stripped = value.strip()
    return stripped or None


def expect_optional_int(
    value: object | None,
    *,
    context: str,
    label: str | None = None,
    error_factory: ErrorFactory = TypeError,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_factory(_message(context, label, "must be an integer if provided"))
    return value


def stringify(value: object) -> str:
    return str(value)


def stringify_optional(value: object | None) -> str | None:
    if value is None:
        return None
    return stringify(value)


def stringify_list(values: Sequence[object]) -> list[str]:
    return [stringify(value) for value in values]


def _message(context: str, label: str | None, suffix: str) -> str:
    if label is None:
        return f"{context} {suffix}."
    return f"{context} field {label!r} {suffix}."
