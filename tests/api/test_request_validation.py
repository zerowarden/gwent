from typing import cast

from tests.api.support import api_client, create_match_payload


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
        leader_response = client.post(
            "/matches/api_row_validation/actions/use-leader",
            json={"service_player_id": "alice", "target_row": "invalid"},
        )
        choice_response = client.post(
            "/matches/api_row_validation/actions/resolve-choice",
            json={
                "service_player_id": "alice",
                "choice_id": "pending_choice_1",
                "selected_rows": ["invalid"],
            },
        )

    assert play_response.status_code == 422
    assert leader_response.status_code == 422
    assert choice_response.status_code == 422


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
