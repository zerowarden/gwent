"""Domain-specific exceptions."""

from typing import ClassVar


class GwentEngineError(Exception):
    """Base class for engine-specific failures."""


class IllegalActionError(GwentEngineError):
    """Raised when an action is illegal for the current state."""


class DefinitionLoadError(GwentEngineError):
    """Raised when authored YAML data is invalid."""


class DuplicateDefinitionError(DefinitionLoadError):
    """Raised when duplicate authored identifiers are loaded."""


class _UnknownDefinitionFieldError(DefinitionLoadError):
    field_name: ClassVar[str]

    def __init__(self, value: object) -> None:
        super().__init__(f"Unknown {self.field_name}: {value!r}")


class _UnknownEntityError(GwentEngineError):
    entity_name: ClassVar[str]

    def __init__(self, entity_id: object) -> None:
        super().__init__(f"Unknown {self.entity_name} id: {entity_id!r}")


class UnknownAbilityKindError(_UnknownDefinitionFieldError):
    """Raised when a card YAML file references an unknown ability kind."""

    field_name: ClassVar[str] = "ability_kind"


class UnknownPassiveKindError(_UnknownDefinitionFieldError):
    """Raised when a faction YAML file references an unknown passive kind."""

    field_name: ClassVar[str] = "passive_kind"


class UnknownFactionError(_UnknownEntityError):
    """Raised when a faction lookup fails."""

    entity_name: ClassVar[str] = "faction"


class UnknownCardDefinitionError(_UnknownEntityError):
    """Raised when a card-definition lookup fails."""

    entity_name: ClassVar[str] = "card definition"


class UnknownCardInstanceError(_UnknownEntityError):
    """Raised when a card-instance lookup fails."""

    entity_name: ClassVar[str] = "card instance"


class UnknownPlayerError(_UnknownEntityError):
    """Raised when a player lookup fails."""

    entity_name: ClassVar[str] = "player"


class InvariantError(GwentEngineError):
    """Raised when runtime state violates an engine invariant."""


class SerializationError(GwentEngineError):
    """Raised when serialized engine data is malformed or unsupported."""


class UnknownLeaderAbilityKindError(_UnknownDefinitionFieldError):
    """Raised when a leader YAML file references an unknown leader_ability_kind."""

    field_name: ClassVar[str] = "leader_ability_kind"


class UnknownLeaderDefinitionError(_UnknownEntityError):
    """Raised when a leader-definition lookup fails."""

    entity_name: ClassVar[str] = "leader definition"
