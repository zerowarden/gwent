from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from gwent_shared.error_translation import translate_mapping_key

from gwent_engine.cards.models import CardDefinition
from gwent_engine.core.errors import DuplicateDefinitionError, UnknownCardDefinitionError
from gwent_engine.core.ids import CardDefinitionId
from gwent_engine.core.registry import MappingRegistry


@dataclass(frozen=True, slots=True)
class CardRegistry(MappingRegistry[CardDefinitionId, CardDefinition]):
    @classmethod
    def from_definitions(cls, definitions: Iterable[CardDefinition]) -> "CardRegistry":
        materialized: dict[CardDefinitionId, CardDefinition] = {}
        for definition in definitions:
            if definition.definition_id in materialized:
                raise DuplicateDefinitionError(
                    f"Duplicate card definition id: {definition.definition_id!r}"
                )
            materialized[definition.definition_id] = definition
        for definition in materialized.values():
            for referenced_definition_id in (
                definition.transforms_into_definition_id,
                definition.avenger_summon_definition_id,
            ):
                if (
                    referenced_definition_id is not None
                    and referenced_definition_id not in materialized
                ):
                    raise UnknownCardDefinitionError(referenced_definition_id)
        return cls(MappingProxyType(materialized))

    def get(self, definition_id: CardDefinitionId) -> CardDefinition:
        return translate_mapping_key(
            self._definitions,
            definition_id,
            UnknownCardDefinitionError,
        )
