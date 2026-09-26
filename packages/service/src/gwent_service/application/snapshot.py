from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from gwent_engine.core.state import GameState

from gwent_service.domain.models import (
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)
from gwent_service.engine.contracts import EngineAdapter


@dataclass(frozen=True, slots=True)
class MatchSnapshot:
    """A persisted match record plus its deserialized engine state.

    `stored` is the single source of truth for record fields; the snapshot
    exposes them as pass-through properties so callers keep a flat surface.
    """

    stored: StoredMatch
    state: GameState

    @property
    def match_id(self) -> str:
        return self.stored.match_id

    @property
    def event_log_payloads(self) -> tuple[dict[str, object], ...]:
        return self.stored.event_log_payloads

    @property
    def player_slots(self) -> tuple[StoredPlayerSlot, StoredPlayerSlot]:
        return self.stored.player_slots

    @property
    def staged_mulligans(self) -> tuple[StagedMulliganSubmission, ...]:
        return self.stored.staged_mulligans

    @property
    def version(self) -> int:
        return self.stored.version

    @property
    def created_at(self) -> datetime:
        return self.stored.created_at

    @property
    def updated_at(self) -> datetime:
        return self.stored.updated_at

    def slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        return self.stored.slot_for_service_player(service_player_id)

    def opponent_slot_for_service_player(self, service_player_id: str) -> StoredPlayerSlot:
        return self.stored.opponent_slot_for_service_player(service_player_id)


def snapshot_from_stored_match(
    stored_match: StoredMatch,
    *,
    adapter: EngineAdapter,
) -> MatchSnapshot:
    return MatchSnapshot(
        stored=stored_match,
        state=adapter.deserialize_state(stored_match.state_payload),
    )


def stored_match_from_snapshot(
    snapshot: MatchSnapshot,
    *,
    adapter: EngineAdapter,
) -> StoredMatch:
    return replace(snapshot.stored, state_payload=adapter.serialize_state(snapshot.state))
