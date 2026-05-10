from collections.abc import Iterator, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MappingRegistry[KeyT, ValueT]:
    """Read-only registry surface shared by authored definition registries."""

    _definitions: Mapping[KeyT, ValueT]

    def __contains__(self, definition_id: object) -> bool:
        return definition_id in self._definitions

    def __iter__(self) -> Iterator[ValueT]:
        return iter(self._definitions.values())

    def __len__(self) -> int:
        return len(self._definitions)
