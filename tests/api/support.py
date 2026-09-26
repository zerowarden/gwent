from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from gwent_service.application.match_service import MatchService
from gwent_service.dependencies import get_match_service
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository
from gwent_service.main import app

from tests.service.support import identity_rng_factory


@contextmanager
def api_client() -> Generator[tuple[TestClient, InMemoryMatchRepository], None, None]:
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


def create_match_payload(
    *,
    match_id: str,
    viewer_player_id: str = "alice",
    player_one_deck: str = "monsters_muster_swarm_strict",
    player_two_deck: str = "nilfgaard_spy_medic_control_strict",
    rng_seed: int = 7,
) -> dict[str, object]:
    return {
        "match_id": match_id,
        "viewer_player_id": viewer_player_id,
        "participants": [
            {
                "service_player_id": "alice",
                "engine_player_id": "p1",
                "deck_id": player_one_deck,
            },
            {
                "service_player_id": "bob",
                "engine_player_id": "p2",
                "deck_id": player_two_deck,
            },
        ],
        "rng_seed": rng_seed,
    }
