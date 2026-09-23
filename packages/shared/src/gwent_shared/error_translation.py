from __future__ import annotations

from collections.abc import Callable, Mapping


def translate_mapping_key[KeyT, ValueT](
    mapping: Mapping[KeyT, ValueT],
    key: KeyT,
    error_factory: Callable[[KeyT], Exception],
) -> ValueT:
    try:
        return mapping[key]
    except KeyError as exc:
        raise error_factory(key) from exc
