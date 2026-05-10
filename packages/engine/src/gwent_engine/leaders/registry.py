from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.core.errors import DuplicateDefinitionError, UnknownLeaderDefinitionError
from gwent_engine.core.ids import LeaderId
from gwent_engine.core.registry import MappingRegistry
from gwent_engine.leaders.models import LeaderDefinition


@dataclass(frozen=True, slots=True)
class LeaderRegistry(MappingRegistry[LeaderId, LeaderDefinition]):
    @classmethod
    def from_definitions(cls, definitions: Iterable[LeaderDefinition]) -> "LeaderRegistry":
        materialized: dict[LeaderId, LeaderDefinition] = {}
        for definition in definitions:
            if definition.leader_id in materialized:
                raise DuplicateDefinitionError(
                    f"Duplicate leader definition id: {definition.leader_id!r}"
                )
            materialized[definition.leader_id] = definition
        return cls(MappingProxyType(materialized))

    def get(self, leader_id: LeaderId) -> LeaderDefinition:
        return translate_mapping_key(
            self._definitions,
            leader_id,
            UnknownLeaderDefinitionError,
        )
