from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

from gwent_shared.error_translation import translate_exception
from gwent_shared.extract import expect_mapping, expect_sequence, expect_str

ErrorFactory = Callable[[str], Exception]


def dump_json(payload: object) -> str:
    return json.dumps(payload)


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
    return translate_exception(
        lambda: _loads_json_document(raw_json),
        json.JSONDecodeError,
        lambda exc: error_factory(f"{context} must be valid JSON: {exc}"),
    )


def _loads_json_document(raw_json: str) -> object:
    return cast(object, json.loads(raw_json))
