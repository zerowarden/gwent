from tests.api.support import api_client, create_match_payload


def test_get_match_returns_projected_safe_view() -> None:
    with api_client() as (client, _repository):
        client.post(
            "/matches",
            json=create_match_payload(match_id="api_get_match"),
        )
        response = client.get("/matches/api_get_match", params={"viewer_player_id": "bob"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["viewer_player_id"] == "bob"
    assert payload["opponent_player_id"] == "alice"
    assert len(payload["viewer_hand"]) == 10
    assert payload["opponent"]["hand_count"] == 10
    assert "p1_card_1" not in response.text


def test_get_match_rejects_unknown_match_player() -> None:
    with api_client() as (client, _repository):
        client.post(
            "/matches",
            json=create_match_payload(match_id="api_get_match_error"),
        )
        response = client.get(
            "/matches/api_get_match_error",
            params={"viewer_player_id": "mallory"},
        )

    assert response.status_code == 403
