from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime


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
        return self._slot_for_id(
            service_player_id,
            slot_id=lambda slot: slot.service_player_id,
        )

    def _slot_for_id(
        self,
        slot_id_value: str,
        *,
        slot_id: Callable[[StoredPlayerSlot], str],
    ) -> StoredPlayerSlot:
        for slot in self.player_slots:
            if slot_id(slot) == slot_id_value:
                return slot
        raise KeyError(slot_id_value)

    def opponent_slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        viewer_slot = self.slot_for_service_player(service_player_id)
        for slot in self.player_slots:
            if slot.service_player_id != viewer_slot.service_player_id:
                return slot
        raise KeyError(service_player_id)
