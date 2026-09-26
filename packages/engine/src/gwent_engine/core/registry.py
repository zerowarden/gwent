from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.core.errors import DuplicateDefinitionError


def build_registry[KeyT, ValueT](
    definitions: Iterable[ValueT],
    *,
    key: Callable[[ValueT], KeyT],
    label: str,
    validate: Callable[[Mapping[KeyT, ValueT]], None] | None = None,
) -> Mapping[KeyT, ValueT]:
    """Materialize definitions into a read-only mapping, rejecting duplicates."""

    materialized: dict[KeyT, ValueT] = {}
    for definition in definitions:
        definition_id = key(definition)
        if definition_id in materialized:
            raise DuplicateDefinitionError(f"Duplicate {label} definition id: {definition_id!r}")
        materialized[definition_id] = definition
    if validate is not None:
        validate(materialized)
    return MappingProxyType(materialized)


@dataclass(frozen=True, slots=True)
class MappingRegistry[KeyT, ValueT]:
    """Read-only registry surface shared by authored definition registries.

    Subclasses declare their lookup error as `_unknown_error` and build
    instances through `build_registry`, which owns duplicate rejection and
    optional cross-reference validation.
    """

    _definitions: Mapping[KeyT, ValueT]

    _unknown_error: ClassVar[Callable[[object], Exception]] = ValueError

    def __contains__(self, definition_id: object) -> bool:
        return definition_id in self._definitions

    def __iter__(self) -> Iterator[ValueT]:
        return iter(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)

    def get(self, definition_id: KeyT) -> ValueT:
        return translate_mapping_key(self._definitions, definition_id, type(self)._unknown_error)
