from gwent_service.application.commands import PassTurnCommand, PlayCardCommand

from tests.service.support import (
    build_started_match,
)


def test_match_service_play_card_and_pass_flow_work_end_to_end() -> None:
    service, repository = build_started_match(
        match_id="action_match",
        alice_deck_id="monsters_muster_swarm_strict",
        bob_deck_id="monsters_muster_swarm_strict",
    )

    played_view = service.play_card(
        PlayCardCommand(
            match_id="action_match",
            service_player_id="alice",
            card_instance_id="p1_card_1",
            target_row="close",
        )
    )
    after_play = repository.get("action_match")
    assert after_play is not None
    assert len(played_view.viewer_hand) == 9
    assert played_view.viewer.rows.close[0].instance_id == "p1_card_1"
    assert len(after_play.event_log_payloads) == 7

    passed_view = service.pass_turn(
        PassTurnCommand(
            match_id="action_match",
            service_player_id="bob",
        )
    )
    after_pass = repository.get("action_match")
    assert after_pass is not None
    assert passed_view.viewer.has_passed is True
    assert passed_view.current_player == "p1"
    assert len(after_pass.event_log_payloads) == 8
