from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

ErrorFactory = Callable[[str], Exception]

__all__ = [
    "expect_bool",
    "expect_int",
    "expect_mapping",
    "expect_optional_int",
    "expect_optional_str",
    "expect_sequence",
    "expect_str",
    "optional_int_field",
    "optional_str_field",
    "require_bool_field",
    "require_field",
    "require_int_field",
    "require_mapping_field",
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


def expect_mapping(
    value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
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
