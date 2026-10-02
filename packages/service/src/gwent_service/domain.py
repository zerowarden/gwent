"""Persisted match records, the repository port, and service errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, Protocol

from gwent_engine.core.state import GameState


@dataclass(frozen=True, slots=True)
class StoredPlayerSlot:
    service_player_id: str
    engine_player_id: str
    deck_id: str

    def __post_init__(self) -> None:
        if not self.service_player_id.strip():
            raise ValueError("StoredPlayerSlot service_player_id cannot be blank.")
        if not self.engine_player_id.strip():
            raise ValueError("StoredPlayerSlot engine_player_id cannot be blank.")
        if not self.deck_id.strip():
            raise ValueError("StoredPlayerSlot deck_id cannot be blank.")


@dataclass(frozen=True, slots=True)
class StagedMulliganSubmission:
    engine_player_id: str
    card_instance_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.engine_player_id.strip():
            raise ValueError("StagedMulliganSubmission engine_player_id cannot be blank.")
        if len(set(self.card_instance_ids)) != len(self.card_instance_ids):
            raise ValueError("StagedMulliganSubmission card_instance_ids must be unique.")
        for card_instance_id in self.card_instance_ids:
            if not card_instance_id.strip():
                raise ValueError("StagedMulliganSubmission card_instance_ids cannot be blank.")


@dataclass(frozen=True, slots=True)
class StoredMatch:
    match_id: str
    state_payload: dict[str, object]
    event_log_payloads: tuple[dict[str, object], ...]
    player_slots: tuple[StoredPlayerSlot, StoredPlayerSlot]
    staged_mulligans: tuple[StagedMulliganSubmission, ...] = ()
    version: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.match_id.strip():
            raise ValueError("StoredMatch match_id cannot be blank.")
        if len(self.player_slots) != 2:
            raise ValueError("StoredMatch requires exactly two player slots.")
        if len({slot.service_player_id for slot in self.player_slots}) != len(self.player_slots):
            raise ValueError("StoredMatch service player ids must be unique.")
        if len({slot.engine_player_id for slot in self.player_slots}) != len(self.player_slots):
            raise ValueError("StoredMatch engine player ids must be unique.")
        if len({item.engine_player_id for item in self.staged_mulligans}) != len(
            self.staged_mulligans
        ):
            raise ValueError("StoredMatch staged mulligans must be unique per engine player.")
        if self.version < 0:
            raise ValueError("StoredMatch version cannot be negative.")

    def slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        for slot in self.player_slots:
            if slot.service_player_id == service_player_id:
                return slot
        raise UnknownMatchPlayerError(service_player_id, self.match_id)

    def opponent_slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        viewer_slot = self.slot_for_service_player(service_player_id)
        for slot in self.player_slots:
            if slot.service_player_id != viewer_slot.service_player_id:
                return slot
        raise UnknownMatchPlayerError(service_player_id, self.match_id)


class MatchRepository(Protocol):
    """Persistence port for match snapshots."""

    def get(self, match_id: str) -> StoredMatch | None: ...

    def create(self, stored_match: StoredMatch) -> None: ...

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None: ...


class MatchServiceError(Exception):
    """Base error for gwent_service failures."""


class _SingleValueMatchServiceError(MatchServiceError):
    message_template: ClassVar[str]

    def __init__(self, value: str) -> None:
        super().__init__(self.message_template.format(value=value))


class MatchAlreadyExistsError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Match {value!r} already exists."


class MatchNotFoundError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Match {value!r} was not found."


class UnknownDeckError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Unknown deck {value!r}."


class MatchVersionConflictError(MatchServiceError):
    expected_version: int
    actual_version: int

    def __init__(
        self,
        match_id: str,
        *,
        expected_version: int,
        actual_version: int,
    ) -> None:
        super().__init__(
            f"Stale match {match_id!r}: expected version {expected_version}, got {actual_version}."
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class UnknownMatchPlayerError(MatchServiceError):
    def __init__(self, service_player_id: str, match_id: str) -> None:
        super().__init__(f"Player {service_player_id!r} does not belong to match {match_id!r}.")


class MatchPhaseError(MatchServiceError):
    pass


class MulliganAlreadySubmittedError(_SingleValueMatchServiceError):
    message_template: ClassVar[str] = "Mulligan already submitted for engine player {value!r}."


@dataclass(frozen=True, slots=True)
class MatchSnapshot:
    """A persisted match record plus its deserialized engine state."""

    stored: StoredMatch
    state: GameState
