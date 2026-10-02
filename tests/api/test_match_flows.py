"""End-to-end match flows over HTTP: mulligan, play, pending choice, leave."""

from typing import cast

from gwent_engine.core.ids import ChoiceId

from tests.api.support import api_client, complete_mulligans, create_match_payload
from tests.service.support import pending_decoy_state, replace_match_state


def test_mulligan_flow_works_across_two_players() -> None:
    with api_client() as (client, _repository):
        client.post(  # pyright: ignore[reportUnusedCallResult]
            "/matches",
            json=create_match_payload(
                match_id="api_mulligan",
                player_one_deck="monsters_muster_swarm_strict",
                player_two_deck="nilfgaard_spy_medic_control_strict",
            ),
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


def test_play_card_flow_works_via_http() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json=create_match_payload(
                match_id="api_play_card",
                player_one_deck="monsters_muster_swarm_strict",
                player_two_deck="monsters_muster_swarm_strict",
            ),
        )
        complete_mulligans(client, "api_play_card")
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
            json=create_match_payload(
                match_id="api_illegal_play",
                player_one_deck="scoiatael_high_stakes",
                player_two_deck="scoiatael_high_stakes",
            ),
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


def test_pending_choice_can_be_resolved_over_http() -> None:
    with api_client() as (client, repository):
        _ = client.post(
            "/matches",
            json=create_match_payload(
                match_id="api_pending_choice",
                player_one_deck="scoiatael_high_stakes",
                player_two_deck="scoiatael_high_stakes",
            ),
        )
        stored_match = repository.get("api_pending_choice")
        assert stored_match is not None
        pending_state = pending_decoy_state("api_pending_choice")
        _ = replace_match_state(repository, match_id="api_pending_choice", state=pending_state)

        pending_response = client.get(
            "/matches/api_pending_choice",
            params={"viewer_player_id": "alice"},
        )
        hidden_response = client.get(
            "/matches/api_pending_choice",
            params={"viewer_player_id": "bob"},
        )
        response_body = cast(dict[str, object], pending_response.json())
        pending_choice_payload = cast(
            dict[str, object],
            response_body["pending_choice"],
        )
        choice_id = ChoiceId(str(pending_choice_payload["choice_id"]))
        resolved_response = client.post(
            "/matches/api_pending_choice/actions/resolve-choice",
            json={
                "service_player_id": "alice",
                "choice_id": choice_id,
                "selected_card_instance_ids": ["p1_spy_target"],
            },
        )

    assert pending_response.status_code == 200
    assert pending_response.json()["pending_choice"] is not None
    assert hidden_response.status_code == 200
    assert hidden_response.json()["pending_choice"] is None
    assert resolved_response.status_code == 200
    assert resolved_response.json()["pending_choice"] is None


def test_leave_match_works_via_http() -> None:
    with api_client() as (client, _repository):
        _ = client.post(
            "/matches",
            json=create_match_payload(
                match_id="api_leave_match",
                player_one_deck="scoiatael_high_stakes",
                player_two_deck="scoiatael_high_stakes",
            ),
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
