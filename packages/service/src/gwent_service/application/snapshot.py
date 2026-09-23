from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gwent_engine.core.state import GameState

from gwent_service.domain.models import (
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
    find_service_player_slot,
)
from gwent_service.engine.contracts import EngineAdapter


@dataclass(frozen=True, slots=True)
class MatchSnapshot:
    match_id: str
    state: GameState
    event_log_payloads: tuple[dict[str, object], ...]
    player_slots: tuple[StoredPlayerSlot, StoredPlayerSlot]
    staged_mulligans: tuple[StagedMulliganSubmission, ...]
    version: int
    created_at: datetime
    updated_at: datetime

    def slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        return find_service_player_slot(self.player_slots, service_player_id)

    def opponent_slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        viewer_slot = self.slot_for_service_player(service_player_id)
        for slot in self.player_slots:
            if slot.service_player_id != viewer_slot.service_player_id:
                return slot
        raise KeyError(service_player_id)


def snapshot_from_stored_match(
    stored_match: StoredMatch,
    *,
    adapter: EngineAdapter,
) -> MatchSnapshot:
    return MatchSnapshot(
        match_id=stored_match.match_id,
        state=adapter.deserialize_state(stored_match.state_payload),
        event_log_payloads=stored_match.event_log_payloads,
        player_slots=stored_match.player_slots,
        staged_mulligans=stored_match.staged_mulligans,
        version=stored_match.version,
        created_at=stored_match.created_at,
        updated_at=stored_match.updated_at,
    )


def stored_match_from_snapshot(
    snapshot: MatchSnapshot,
    *,
    adapter: EngineAdapter,
) -> StoredMatch:
    return StoredMatch(
        match_id=snapshot.match_id,
        state_payload=adapter.serialize_state(snapshot.state),
        event_log_payloads=snapshot.event_log_payloads,
        player_slots=snapshot.player_slots,
        staged_mulligans=snapshot.staged_mulligans,
        version=snapshot.version,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )
