from typing import cast

from gwent_engine.core import ChoiceSourceKind
from gwent_engine.core.ids import ChoiceId
from gwent_engine.serialize import game_state_to_dict
from gwent_service.domain.models import StoredMatch

from tests.api.support import api_client
from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario


def test_pending_choice_can_be_resolved_over_http() -> None:
    with api_client() as (client, repository):
        _ = client.post(
            "/matches",
            json={
                "match_id": "api_pending_choice",
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
        stored_match = repository.get("api_pending_choice")
        assert stored_match is not None
        pending_state = (
            scenario("api_pending_choice")
            .player(
                PLAYER_ONE_ID,
                hand=[card("p1_source_decoy", "neutral_decoy")],
                board=rows(ranged=[card("p1_spy_target", "scoiatael_dol_blathanna_archer")]),
            )
            .player(
                PLAYER_TWO_ID,
                hand=[card("p2_reserve_unit", "scoiatael_dol_blathanna_archer")],
            )
            .card_choice(
                choice_id="pending_choice_1",
                player_id=PLAYER_ONE_ID,
                source_kind=ChoiceSourceKind.DECOY,
                source_card_instance_id="p1_source_decoy",
                legal_target_card_instance_ids=("p1_spy_target",),
            )
            .build()
        )
        repository.update(
            StoredMatch(
                match_id=stored_match.match_id,
                state_payload=game_state_to_dict(pending_state),
                event_log_payloads=stored_match.event_log_payloads,
                player_slots=stored_match.player_slots,
                staged_mulligans=(),
                version=stored_match.version + 1,
                created_at=stored_match.created_at,
                updated_at=stored_match.updated_at,
            )
        )
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
