from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar

from gwent_engine.cards.models import CardDefinition
from gwent_engine.core.errors import UnknownCardDefinitionError
from gwent_engine.core.ids import CardDefinitionId
from gwent_engine.core.registry import MappingRegistry, build_registry


@dataclass(frozen=True, slots=True)
class CardRegistry(MappingRegistry[CardDefinitionId, CardDefinition]):
    _unknown_error: ClassVar[Callable[[object], Exception]] = UnknownCardDefinitionError

    @classmethod
    def from_definitions(cls, definitions: Iterable[CardDefinition]) -> CardRegistry:
        return cls(
            build_registry(
                definitions,
                key=_definition_id,
                label="card",
                validate=_validate_references,
            )
        )


def _definition_id(definition: CardDefinition) -> CardDefinitionId:
    return definition.definition_id


def _validate_references(materialized: Mapping[CardDefinitionId, CardDefinition]) -> None:
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
