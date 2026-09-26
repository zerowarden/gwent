from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar

from gwent_engine.core import FactionId
from gwent_engine.core.errors import UnknownFactionError
from gwent_engine.core.registry import MappingRegistry, build_registry
from gwent_engine.factions.models import FactionDefinition


@dataclass(frozen=True, slots=True)
class FactionRegistry(MappingRegistry[FactionId, FactionDefinition]):
    _unknown_error: ClassVar[Callable[[object], Exception]] = UnknownFactionError

    @classmethod
    def from_definitions(cls, definitions: Iterable[FactionDefinition]) -> FactionRegistry:
        return cls(build_registry(definitions, key=_faction_id, label="faction"))


def _faction_id(definition: FactionDefinition) -> FactionId:
    return definition.faction_id
