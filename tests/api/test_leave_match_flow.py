from typing import cast

from tests.api.support import api_client


def test_leave_match_works_via_http() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json={
                "match_id": "api_leave_match",
                "viewer_player_id": "alice",
                "participants": [
                    {
                        "service_player_id": "alice",
                        "engine_player_id": "p1",
                        "deck_id": "scoiatael_high_stakes",
                    },
                    {
                        "service_player_id": "bob",
                        "engine_player_id": "p2",
                        "deck_id": "scoiatael_high_stakes",
                    },
                ],
                "rng_seed": 7,
            },
        )
        response = client.post(
            "/matches/api_leave_match/actions/leave",
            json={"service_player_id": "alice"},
        )

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    viewer = cast(dict[str, object], payload["viewer"])
    assert payload["status"] == "match_ended"
    assert payload["phase"] == "match_ended"
    assert payload["match_winner"] == "p2"
    assert viewer["gems_remaining"] == 0
