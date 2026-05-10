from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.core import FactionId
from gwent_engine.core.errors import DuplicateDefinitionError, UnknownFactionError
from gwent_engine.core.registry import MappingRegistry
from gwent_engine.factions.models import FactionDefinition


@dataclass(frozen=True, slots=True)
class FactionRegistry(MappingRegistry[FactionId, FactionDefinition]):
    @classmethod
    def from_definitions(cls, definitions: Iterable[FactionDefinition]) -> "FactionRegistry":
        materialized: dict[FactionId, FactionDefinition] = {}
        for definition in definitions:
            if definition.faction_id in materialized:
                raise DuplicateDefinitionError(
                    f"Duplicate faction definition id: {definition.faction_id!r}"
                )
            materialized[definition.faction_id] = definition
        return cls(MappingProxyType(materialized))

    def get(self, faction_id: FactionId) -> FactionDefinition:
        return translate_mapping_key(
            self._definitions,
            faction_id,
            UnknownFactionError,
        )
