from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from gwent_engine.core import ChoiceSourceKind
from gwent_engine.core.state import GameState
from gwent_engine.serialize import game_state_to_dict
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
from gwent_service.domain.repositories import MatchRepository
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.support import IdentityShuffle


def identity_rng_factory(seed: int | None, event_counter: int) -> IdentityShuffle:
    del seed, event_counter
    return IdentityShuffle()


def build_service() -> tuple[MatchService, InMemoryMatchRepository]:
    repository = InMemoryMatchRepository()
    return build_service_with_repository(repository), repository


def build_service_with_repository(repository: MatchRepository) -> MatchService:
    return MatchService(
        repository,
        GwentEngineAdapter(),
        rng_factory=identity_rng_factory,
    )


class StaleSnapshotRepository:
    def __init__(self, delegate: MatchRepository, stale_match: StoredMatch) -> None:
        self._delegate: MatchRepository = delegate
        self._stale_match: StoredMatch | None = stale_match

    def create(self, stored_match: StoredMatch) -> None:
        self._delegate.create(stored_match)

    def get(self, match_id: str) -> StoredMatch | None:
        stale_match = self._stale_match
        if stale_match is not None and stale_match.match_id == match_id:
            self._stale_match = None
            return stale_match
        return self._delegate.get(match_id)

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None:
        self._delegate.update(stored_match, expected_version=expected_version)


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


def pending_decoy_state(name: str) -> GameState:
    """A decoy pending choice owned by alice with one legal board target."""

    return (
        scenario(name)
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_source_decoy", "neutral_decoy")],
            board=rows(ranged=[card("p1_spy_target", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve_unit", "scoiatael_dol_blathanna_archer")],
        )
        .card_choice(
            choice_id="pending_choice_1",
            player_id=PLAYER_ONE_ID,
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_source_decoy",
            legal_target_card_instance_ids=("p1_spy_target",),
        )
        .build()
    )


def replace_match_state(
    repository: MatchRepository,
    *,
    match_id: str,
    state: GameState,
) -> StoredMatch:
    stored_match = repository.get(match_id)
    if stored_match is None:
        raise AssertionError(f"Match {match_id!r} does not exist.")
    updated = replace(
        stored_match,
        state_payload=game_state_to_dict(state),
        staged_mulligans=(),
        version=stored_match.version + 1,
    )
    repository.update(updated, expected_version=stored_match.version)
    return updated


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
