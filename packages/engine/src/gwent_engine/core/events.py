"""Typed events emitted by the engine."""

from dataclasses import dataclass

from gwent_engine.core.enums import (
    AbilityKind,
    EffectSourceCategory,
    LeaderAbilityKind,
    LeaderAbilityMode,
    PassiveKind,
    Phase,
    Row,
)
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId, LeaderId, PlayerId


@dataclass(frozen=True, slots=True)
class StartingPlayerChosenEvent:
    event_id: int
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class GameStartedEvent:
    event_id: int
    phase: Phase
    round_number: int


@dataclass(frozen=True, slots=True)
class CardsDrawnEvent:
    event_id: int
    player_id: PlayerId
    card_instance_ids: tuple[CardInstanceId, ...]


@dataclass(frozen=True, slots=True)
class MulliganPerformedEvent:
    event_id: int
    player_id: PlayerId
    replaced_card_instance_ids: tuple[CardInstanceId, ...]
    drawn_card_instance_ids: tuple[CardInstanceId, ...]


@dataclass(frozen=True, slots=True)
class CardPlayedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    target_row: Row | None


@dataclass(frozen=True, slots=True)
class SpyResolvedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    drawn_card_instance_ids: tuple[CardInstanceId, ...] = ()


@dataclass(frozen=True, slots=True)
class MedicResolvedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    resurrected_card_instance_id: CardInstanceId | None = None


@dataclass(frozen=True, slots=True)
class MusterResolvedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    mustered_card_instance_ids: tuple[CardInstanceId, ...] = ()


@dataclass(frozen=True, slots=True)
class CardTransformedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    previous_definition_id: CardDefinitionId
    new_definition_id: CardDefinitionId
    affected_row: Row


@dataclass(frozen=True, slots=True)
class UnitHornActivatedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    affected_row: Row


@dataclass(frozen=True, slots=True)
class UnitHornSuppressedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    affected_row: Row
    active_source_category: EffectSourceCategory
    active_source_card_instance_id: CardInstanceId | None = None
    active_source_leader_id: LeaderId | None = None


@dataclass(frozen=True, slots=True)
class UnitScorchResolvedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    affected_row: Row
    destroyed_card_instance_ids: tuple[CardInstanceId, ...] = ()


@dataclass(frozen=True, slots=True)
class SpecialCardResolvedEvent:
    event_id: int
    player_id: PlayerId
    card_instance_id: CardInstanceId
    ability_kind: AbilityKind
    affected_row: Row | None = None
    target_card_instance_id: CardInstanceId | None = None
    discarded_card_instance_ids: tuple[CardInstanceId, ...] = ()


@dataclass(frozen=True, slots=True)
class AvengerSummonQueuedEvent:
    event_id: int
    player_id: PlayerId
    source_card_instance_id: CardInstanceId
    summoned_definition_id: CardDefinitionId
    affected_row: Row


@dataclass(frozen=True, slots=True)
class AvengerSummonedEvent:
    event_id: int
    player_id: PlayerId
    source_card_instance_id: CardInstanceId
    summoned_card_instance_id: CardInstanceId
    summoned_definition_id: CardDefinitionId
    affected_row: Row


@dataclass(frozen=True, slots=True)
class LeaderAbilityResolvedEvent:
    event_id: int
    player_id: PlayerId
    leader_id: LeaderId
    ability_kind: LeaderAbilityKind
    ability_mode: LeaderAbilityMode
    affected_row: Row | None = None
    played_card_instance_id: CardInstanceId | None = None
    target_card_instance_id: CardInstanceId | None = None
    discarded_card_instance_ids: tuple[CardInstanceId, ...] = ()
    drawn_card_instance_ids: tuple[CardInstanceId, ...] = ()
    returned_card_instance_ids: tuple[CardInstanceId, ...] = ()
    revealed_card_instance_ids: tuple[CardInstanceId, ...] = ()
    shuffled_card_instance_ids: tuple[CardInstanceId, ...] = ()
    moved_card_instance_ids: tuple[CardInstanceId, ...] = ()
    disabled_player_id: PlayerId | None = None


@dataclass(frozen=True, slots=True)
class PlayerPassedEvent:
    event_id: int
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class PlayerLeftEvent:
    event_id: int
    player_id: PlayerId


@dataclass(frozen=True, slots=True)
class FactionPassiveTriggeredEvent:
    event_id: int
    player_id: PlayerId
    passive_kind: PassiveKind
    chosen_player_id: PlayerId | None = None
    card_instance_id: CardInstanceId | None = None


@dataclass(frozen=True, slots=True)
class RoundEndedEvent:
    event_id: int
    round_number: int
    player_scores: tuple[tuple[PlayerId, int], tuple[PlayerId, int]]
    winner: PlayerId | None


@dataclass(frozen=True, slots=True)
class CardsMovedToDiscardEvent:
    event_id: int
    card_instance_ids: tuple[CardInstanceId, ...]


@dataclass(frozen=True, slots=True)
class NextRoundStartedEvent:
    event_id: int
    round_number: int
    starting_player: PlayerId


@dataclass(frozen=True, slots=True)
class MatchEndedEvent:
    event_id: int
    winner: PlayerId | None


type GameEvent = (
    StartingPlayerChosenEvent
    | GameStartedEvent
    | CardsDrawnEvent
    | MulliganPerformedEvent
    | CardPlayedEvent
    | SpyResolvedEvent
    | MedicResolvedEvent
    | MusterResolvedEvent
    | CardTransformedEvent
    | UnitHornActivatedEvent
    | UnitHornSuppressedEvent
    | UnitScorchResolvedEvent
    | SpecialCardResolvedEvent
    | AvengerSummonQueuedEvent
    | AvengerSummonedEvent
    | LeaderAbilityResolvedEvent
    | PlayerPassedEvent
    | PlayerLeftEvent
    | FactionPassiveTriggeredEvent
    | RoundEndedEvent
    | CardsMovedToDiscardEvent
    | NextRoundStartedEvent
    | MatchEndedEvent
)
