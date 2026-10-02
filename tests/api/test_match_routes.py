"""HTTP route contracts: health, match creation and lookup, validation, conflicts."""

from typing import cast

from gwent_service.api import get_match_service
from gwent_service.main import app

from tests.api.support import api_client, create_match_payload
from tests.service.support import StaleSnapshotRepository, build_service_with_repository


def test_health_endpoint_returns_ok() -> None:
    with api_client() as (client, _repository):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_match_works_via_http() -> None:
    with api_client() as (client, repository):
        response = client.post(
            "/matches",
            json=create_match_payload(match_id="api_create_match"),
        )

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    viewer_hand = cast(list[object], payload["viewer_hand"])
    assert payload["match_id"] == "api_create_match"
    assert payload["phase"] == "mulligan"
    assert payload["viewer_player_id"] == "alice"
    assert len(viewer_hand) == 10
    assert repository.get("api_create_match") is not None


def test_get_match_returns_projected_safe_view() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json=create_match_payload(match_id="api_get_match"),
        )
        response = client.get("/matches/api_get_match", params={"viewer_player_id": "bob"})

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    viewer_hand = cast(list[object], payload["viewer_hand"])
    opponent = cast(dict[str, object], payload["opponent"])
    assert payload["viewer_player_id"] == "bob"
    assert payload["opponent_player_id"] == "alice"
    assert len(viewer_hand) == 10
    assert opponent["hand_count"] == 10
    assert "p1_card_1" not in response.text


def test_get_match_rejects_unknown_match_player() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json=create_match_payload(match_id="api_get_match_error"),
        )
        response = client.get(
            "/matches/api_get_match_error",
            params={"viewer_player_id": "mallory"},
        )

    assert response.status_code == 403


def test_invalid_row_values_are_rejected_as_client_errors() -> None:
    with api_client() as (client, _repository):
        _ = client.post("/matches", json=create_match_payload(match_id="api_row_validation"))
        play_response = client.post(
            "/matches/api_row_validation/actions/play-card",
            json={
                "service_player_id": "alice",
                "card_instance_id": "p1_card_1",
                "target_row": "invalid",
            },
        )

    assert play_response.status_code == 422


def test_unknown_deck_is_rejected_as_client_error_without_persisting() -> None:
    with api_client() as (client, repository):
        payload = create_match_payload(match_id="api_bad_deck")
        participants = cast(list[dict[str, object]], payload["participants"])
        participants[0]["deck_id"] = "no_such_deck"

        response = client.post("/matches", json=payload)

        assert response.status_code == 400
        assert repository.get("api_bad_deck") is None


def test_duplicate_or_blank_participants_are_rejected_as_client_errors() -> None:
    with api_client() as (client, repository):
        duplicate_payload = create_match_payload(match_id="api_duplicate_players")
        duplicate_participants = cast(list[dict[str, object]], duplicate_payload["participants"])
        duplicate_participants[1]["engine_player_id"] = "p1"

        duplicate_response = client.post("/matches", json=duplicate_payload)
        blank_response = client.post("/matches", json=create_match_payload(match_id=""))

        assert duplicate_response.status_code == 422
        assert blank_response.status_code == 422
        assert repository.get("api_duplicate_players") is None


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
