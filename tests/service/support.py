from __future__ import annotations

from datetime import UTC, datetime

from gwent_service.application.commands import (
    CreateMatchCommand,
    CreateMatchParticipantCommand,
    SubmitMulliganCommand,
)
from gwent_service.application.match_service import MatchService
from gwent_service.domain.models import (
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository

from tests.support import IdentityShuffle


def identity_rng_factory(seed: int | None, event_counter: int) -> IdentityShuffle:
    del seed, event_counter
    return IdentityShuffle()


def build_service() -> tuple[MatchService, InMemoryMatchRepository]:
    repository = InMemoryMatchRepository()
    service = MatchService(
        repository,
        GwentEngineAdapter(),
        rng_factory=identity_rng_factory,
    )
    return service, repository


def build_stored_match(
    *,
    match_id: str = "stored_match",
    version: int = 0,
    state_payload: dict[str, object] | None = None,
    event_log_payloads: tuple[dict[str, object], ...] = (),
    staged_mulligans: tuple[StagedMulliganSubmission, ...] = (),
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> StoredMatch:
    timestamp = datetime(2026, 4, 16, 12, 30, tzinfo=UTC)
    return StoredMatch(
        match_id=match_id,
        state_payload=(
            {"type": "game_state", "phase": "not_started"}
            if state_payload is None
            else state_payload
        ),
        event_log_payloads=event_log_payloads,
        player_slots=(
            StoredPlayerSlot(service_player_id="alice", engine_player_id="p1", deck_id="deck_one"),
            StoredPlayerSlot(service_player_id="bob", engine_player_id="p2", deck_id="deck_two"),
        ),
        staged_mulligans=staged_mulligans,
        version=version,
        created_at=created_at or timestamp,
        updated_at=updated_at or timestamp,
    )


def build_create_match_command(
    *,
    match_id: str = "service_match",
    alice_deck_id: str = "monsters_muster_swarm_strict",
    bob_deck_id: str = "nilfgaard_spy_medic_control_strict",
    rng_seed: int | None = 7,
) -> CreateMatchCommand:
    return CreateMatchCommand(
        match_id=match_id,
        participants=(
            CreateMatchParticipantCommand(
                service_player_id="alice",
                engine_player_id="p1",
                deck_id=alice_deck_id,
            ),
            CreateMatchParticipantCommand(
                service_player_id="bob",
                engine_player_id="p2",
                deck_id=bob_deck_id,
            ),
        ),
        rng_seed=rng_seed,
    )


def build_started_match(
    *,
    match_id: str = "service_match",
    alice_deck_id: str = "monsters_muster_swarm_strict",
    bob_deck_id: str = "nilfgaard_spy_medic_control_strict",
    rng_seed: int | None = 7,
) -> tuple[MatchService, InMemoryMatchRepository]:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(
            match_id=match_id,
            alice_deck_id=alice_deck_id,
            bob_deck_id=bob_deck_id,
            rng_seed=rng_seed,
        ),
        viewer_service_player_id="alice",
    )
    resolve_empty_mulligans(service, match_id=match_id)
    return service, repository


def resolve_empty_mulligans(service: MatchService, *, match_id: str) -> None:
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id=match_id,
            service_player_id="alice",
            card_instance_ids=(),
        )
    )
    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id=match_id,
            service_player_id="bob",
            card_instance_ids=(),
        )
    )
