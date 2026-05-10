from __future__ import annotations

from gwent_engine.core import ChoiceSourceKind
from gwent_engine.core.actions import StartGameAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.serialize import game_state_to_dict
from gwent_service.application.projections import project_match_for_player
from gwent_service.domain.models import (
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.engine.contracts import CreateMatchStateSpec, EnginePlayerDeckSpec

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.support import IdentityShuffle


def test_projection_hides_opponent_hand_contents_and_never_exposes_staged_mulligans() -> None:
    adapter = GwentEngineAdapter()
    rng = IdentityShuffle()
    base_state = adapter.create_match_state(
        CreateMatchStateSpec(
            game_id="projection_match",
            players=(
                EnginePlayerDeckSpec(player_id="p1", deck_id="scoiatael_high_stakes"),
                EnginePlayerDeckSpec(player_id="p2", deck_id="nilfgaard_spy_medic_control_strict"),
            ),
        )
    )
    transition = adapter.apply_engine_action(
        base_state,
        StartGameAction(starting_player=PlayerId("p1")),
        rng=rng,
    )
    stored_match = StoredMatch(
        match_id="projection_match",
        state_payload=adapter.serialize_state(transition.next_state),
        event_log_payloads=adapter.serialize_events(transition.events),
        player_slots=(
            StoredPlayerSlot(
                service_player_id="alice",
                engine_player_id="p1",
                deck_id="scoiatael_high_stakes",
            ),
            StoredPlayerSlot(
                service_player_id="bob",
                engine_player_id="p2",
                deck_id="nilfgaard_spy_medic_control_strict",
            ),
        ),
        staged_mulligans=(
            StagedMulliganSubmission(
                engine_player_id="p1",
                card_instance_ids=("hidden_staged_card_1", "hidden_staged_card_2"),
            ),
        ),
    )

    projected = project_match_for_player(stored_match, "alice", adapter=adapter)
    dumped = projected.model_dump_json()

    assert projected.viewer.service_player_id == "alice"
    assert projected.opponent.service_player_id == "bob"
    assert len(projected.viewer_hand) == 10
    assert projected.viewer.hand_count == 10
    assert projected.opponent.hand_count == 10
    assert projected.pending_choice is None
    assert "hidden_staged_card_1" not in dumped
    assert "hidden_staged_card_2" not in dumped
    assert "p2_card_1" not in dumped
    assert {
        status.service_player_id: status.submitted for status in projected.mulligan_submissions
    } == {
        "alice": True,
        "bob": False,
    }


def test_projection_restricts_pending_choice_to_chooser() -> None:
    adapter = GwentEngineAdapter()
    state = (
        scenario("pending_choice_match")
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
    stored_match = StoredMatch(
        match_id="pending_choice_match",
        state_payload=game_state_to_dict(state),
        event_log_payloads=(),
        player_slots=(
            StoredPlayerSlot(
                service_player_id="alice",
                engine_player_id="p1",
                deck_id="scoiatael_high_stakes",
            ),
            StoredPlayerSlot(
                service_player_id="bob",
                engine_player_id="p2",
                deck_id="scoiatael_high_stakes",
            ),
        ),
    )

    chooser_view = project_match_for_player(stored_match, "alice", adapter=adapter)
    opponent_view = project_match_for_player(stored_match, "bob", adapter=adapter)

    assert chooser_view.pending_choice is not None
    assert chooser_view.pending_choice.chooser_engine_player_id == "p1"
    assert len(chooser_view.pending_choice.legal_target_cards) >= 1
    assert opponent_view.pending_choice is None
