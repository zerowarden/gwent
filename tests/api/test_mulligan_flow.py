from tests.api.support import api_client


def test_mulligan_flow_works_across_two_players() -> None:
    with api_client() as (client, _repository):
        client.post(  # pyright: ignore[reportUnusedCallResult]
            "/matches",
            json={
                "match_id": "api_mulligan",
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
                        "deck_id": "nilfgaard_spy_medic_control_strict",
                    },
                ],
                "rng_seed": 7,
            },
        )
        first_response = client.post(
            "/matches/api_mulligan/mulligan",
            json={"service_player_id": "alice", "card_instance_ids": ["p1_card_1"]},
        )
        second_response = client.post(
            "/matches/api_mulligan/mulligan",
            json={"service_player_id": "bob", "card_instance_ids": []},
        )

    assert first_response.status_code == 200
    assert first_response.json()["phase"] == "mulligan"
    assert second_response.status_code == 200
    assert second_response.json()["phase"] == "in_round"
    assert second_response.json()["current_player"] == "p1"
