from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import NoReturn, cast

from gwent_shared.extract import expect_mapping, expect_sequence, expect_str

ErrorFactory = Callable[[str], Exception]


def dump_json(payload: object) -> str:
    return json.dumps(payload)


def dump_pretty_json(payload: object) -> str:
    """Canonical, reviewable JSON text for persisted records and artifacts."""

    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def dump_canonical_json(payload: object) -> str:
    """Deterministic JSON text: sorted keys, compact separators, ASCII-only."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_json(payload: object) -> str:
    """Canonical JSON text for typed payloads, rejecting non-finite numbers."""

    return dump_canonical_json(to_canonical(payload))


def to_canonical(value: object) -> object:
    """Convert typed records into a deterministic JSON-compatible structure."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return cast(object, value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_canonical(cast(object, getattr(value, field.name)))
            for field in dataclasses.fields(value)
            if field.init
        }
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): to_canonical(item)
            for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [to_canonical(item) for item in cast(Sequence[object], value)]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (to_canonical(item) for item in cast(set[object] | frozenset[object], value)),
            key=repr,
        )
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cannot canonicalize non-finite numbers.")
        return value
    if isinstance(value, str):
        return value
    raise TypeError(f"Cannot canonicalize value of type {type(value).__name__}.")


def parse_json_document(
    text: str,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> object:
    """Parse strict JSON text, rejecting duplicate keys and non-finite numbers."""

    def reject_constant(constant: str) -> NoReturn:
        raise error_factory(f"{context} contains the non-finite constant {constant!r}.")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        mapping: dict[str, object] = {}
        for key, value in pairs:
            if key in mapping:
                raise error_factory(f"{context} contains the duplicate key {key!r}.")
            mapping[key] = value
        return mapping

    try:
        return cast(
            object,
            json.loads(
                text,
                parse_constant=reject_constant,
                object_pairs_hook=reject_duplicate_keys,
            ),
        )
    except json.JSONDecodeError as error:
        raise error_factory(f"{context} is not valid JSON: {error}") from error


def load_json_mapping(
    raw_value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> dict[str, object]:
    decoded = _load_json(raw_value, context=context, error_factory=error_factory)
    return dict(expect_mapping(decoded, context=context, error_factory=error_factory))


def load_json_list(
    raw_value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> list[object]:
    decoded = _load_json(raw_value, context=context, error_factory=error_factory)
    return list(expect_sequence(decoded, context=context, error_factory=error_factory))


def load_json_object_list(
    raw_value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> list[dict[str, object]]:
    decoded = load_json_list(raw_value, context=context, error_factory=error_factory)
    objects: list[dict[str, object]] = []
    for index, item in enumerate(decoded):
        objects.append(
            dict(
                expect_mapping(
                    item,
                    context=f"{context}[{index}]",
                    error_factory=error_factory,
                )
            )
        )
    return objects


def _load_json(
    raw_value: object,
    *,
    context: str,
    error_factory: ErrorFactory = TypeError,
) -> object:
    raw_json = expect_str(raw_value, context=context, error_factory=error_factory)
    return parse_json_document(raw_json, context=context, error_factory=error_factory)
