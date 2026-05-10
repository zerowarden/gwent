from dataclasses import dataclass

from gwent_engine.core import FactionId, PassiveKind


@dataclass(frozen=True, slots=True)
class FactionDefinition:
    faction_id: FactionId
    name: str
    passive_kind: PassiveKind
    passive_description: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("FactionDefinition name cannot be blank.")
        if not self.passive_description.strip():
            raise ValueError("FactionDefinition passive_description cannot be blank.")
