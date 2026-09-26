from typing import cast

from gwent_engine.core.ids import ChoiceId

from tests.api.support import api_client, create_match_payload
from tests.service.support import pending_decoy_state, replace_match_state


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
