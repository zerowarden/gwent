from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from gwent_service.api import get_match_service
from gwent_service.engine_adapter import GwentEngineAdapter
from gwent_service.main import app
from gwent_service.match_service import MatchService
from gwent_service.persistence import InMemoryMatchRepository

from tests.service.support import (
    ALICE,
    ALICE_DECK_ID,
    BOB,
    BOB_DECK_ID,
    DEFAULT_RNG_SEED,
    identity_rng_factory,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


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
    viewer_player_id: str = ALICE,
    player_one_deck: str = ALICE_DECK_ID,
    player_two_deck: str = BOB_DECK_ID,
    rng_seed: int = DEFAULT_RNG_SEED,
) -> dict[str, object]:
    return {
        "match_id": match_id,
        "viewer_player_id": viewer_player_id,
        "participants": [
            {
                "service_player_id": ALICE,
                "engine_player_id": str(PLAYER_ONE_ID),
                "deck_id": player_one_deck,
            },
            {
                "service_player_id": BOB,
                "engine_player_id": str(PLAYER_TWO_ID),
                "deck_id": player_two_deck,
            },
        ],
        "rng_seed": rng_seed,
    }


def complete_mulligans(client: TestClient, match_id: str) -> None:
    """Submit empty mulligans for both seats so the match reaches in-round play."""
    for service_player_id in (ALICE, BOB):
        response = client.post(
            f"/matches/{match_id}/mulligan",
            json={"service_player_id": service_player_id, "card_instance_ids": []},
        )
        assert response.status_code == 200
