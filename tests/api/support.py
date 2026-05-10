from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from gwent_service.application.match_service import MatchService
from gwent_service.dependencies import get_match_service
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository
from gwent_service.main import app

from tests.service.support import identity_rng_factory


@contextmanager
def api_client() -> Iterator[tuple[TestClient, InMemoryMatchRepository]]:
    repository = InMemoryMatchRepository()
    service = MatchService(
        repository=repository,
        adapter=GwentEngineAdapter(),
        rng_factory=identity_rng_factory,
    )
    app.dependency_overrides[get_match_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, repository
    finally:
        app.dependency_overrides.clear()


def create_match_payload(*, match_id: str, viewer_player_id: str = "alice") -> dict[str, object]:
    return {
        "match_id": match_id,
        "viewer_player_id": viewer_player_id,
        "participants": [
            {
                "service_player_id": "alice",
                "engine_player_id": "p1",
                "deck_id": "monsters_muster_swarm_strict",
            },
            {
                "service_player_id": "bob",
                "engine_player_id": "p2",
                "deck_id": "nilfgaard_spy_medic_control_strict",
            },
        ],
        "rng_seed": 7,
    }
