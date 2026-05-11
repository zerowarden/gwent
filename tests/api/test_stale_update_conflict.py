from gwent_service.dependencies import get_match_service
from gwent_service.main import app

from tests.api.support import api_client, create_match_payload
from tests.service.support import StaleSnapshotRepository, build_service_with_repository


def test_stale_mulligan_submission_returns_conflict() -> None:
    with api_client() as (client, repository):
        _ = client.post("/matches", json=create_match_payload(match_id="api_conflict"))
        stale_snapshot = repository.get("api_conflict")
        assert stale_snapshot is not None

        first_response = client.post(
            "/matches/api_conflict/mulligan",
            json={"service_player_id": "alice", "card_instance_ids": ["p1_card_1"]},
        )
        assert first_response.status_code == 200

        app.dependency_overrides[get_match_service] = lambda: build_service_with_repository(
            StaleSnapshotRepository(repository, stale_snapshot)
        )
        stale_response = client.post(
            "/matches/api_conflict/mulligan",
            json={"service_player_id": "bob", "card_instance_ids": []},
        )

    assert stale_response.status_code == 409
