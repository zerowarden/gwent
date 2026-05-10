from tests.api.support import api_client, create_match_payload


def test_create_match_works_via_http() -> None:
    with api_client() as (client, repository):
        response = client.post(
            "/matches",
            json=create_match_payload(match_id="api_create_match"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["match_id"] == "api_create_match"
    assert payload["phase"] == "mulligan"
    assert payload["viewer_player_id"] == "alice"
    assert len(payload["viewer_hand"]) == 10
    assert repository.get("api_create_match") is not None
