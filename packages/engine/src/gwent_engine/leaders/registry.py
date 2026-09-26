from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar

from gwent_engine.core.errors import UnknownLeaderDefinitionError
from gwent_engine.core.ids import LeaderId
from gwent_engine.core.registry import MappingRegistry, build_registry
from gwent_engine.leaders.models import LeaderDefinition


@dataclass(frozen=True, slots=True)
class LeaderRegistry(MappingRegistry[LeaderId, LeaderDefinition]):
    _unknown_error: ClassVar[Callable[[object], Exception]] = UnknownLeaderDefinitionError

    @classmethod
    def from_definitions(cls, definitions: Iterable[LeaderDefinition]) -> LeaderRegistry:
        return cls(build_registry(definitions, key=_leader_id, label="leader"))


def _leader_id(definition: LeaderDefinition) -> LeaderId:
    return definition.leader_id
