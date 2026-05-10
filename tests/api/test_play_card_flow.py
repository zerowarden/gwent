from typing import cast

from tests.api.support import api_client


def test_play_card_flow_works_via_http() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json={
                "match_id": "api_play_card",
                "viewer_player_id": "alice",
                "participants": [
                    {
                        "service_player_id": "alice",
                        "engine_player_id": "p1",
                        "deck_id": "monsters_muster_swarm_strict",
                    },
                    {
                        "service_player_id": "bob",
                        "engine_player_id": "p2",
                        "deck_id": "monsters_muster_swarm_strict",
                    },
                ],
                "rng_seed": 7,
            },
        )
        _ = client.post(
            "/matches/api_play_card/mulligan",
            json={"service_player_id": "alice", "card_instance_ids": []},
        )
        _ = client.post(
            "/matches/api_play_card/mulligan",
            json={"service_player_id": "bob", "card_instance_ids": []},
        )
        response = client.post(
            "/matches/api_play_card/actions/play-card",
            json={
                "service_player_id": "alice",
                "card_instance_id": "p1_card_1",
                "target_row": "close",
            },
        )

    assert response.status_code == 200
    payload = cast(dict[str, object], response.json())
    viewer = cast(dict[str, object], payload["viewer"])
    rows = cast(dict[str, object], viewer["rows"])
    close_row = cast(list[dict[str, object]], rows["close"])
    assert payload["phase"] == "in_round"
    assert close_row[0]["instance_id"] == "p1_card_1"


def test_illegal_action_surfaces_cleanly_over_http() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json={
                "match_id": "api_illegal_play",
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
            "/matches/api_illegal_play/actions/play-card",
            json={
                "service_player_id": "alice",
                "card_instance_id": "p1_card_1",
                "target_row": "close",
            },
        )

    assert response.status_code == 400
