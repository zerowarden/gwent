from gwent_service.application.commands import SubmitMulliganCommand

from tests.service.support import build_create_match_command, build_service


def test_match_service_stages_one_mulligan_then_resolves_on_second_submission() -> None:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(match_id="mulligan_match"),
        viewer_service_player_id="alice",
    )

    staged_view = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="mulligan_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_1",),
        )
    )
    staged_match = repository.get("mulligan_match")
    assert staged_match is not None
    assert staged_view.phase == "mulligan"
    assert len(staged_match.staged_mulligans) == 1
    assert len(staged_match.event_log_payloads) == 4

    resolved_view = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="mulligan_match",
            service_player_id="bob",
            card_instance_ids=(),
        )
    )
    alice_resolved_view = service.get_match("mulligan_match", viewer_service_player_id="alice")
    resolved_match = repository.get("mulligan_match")
    assert resolved_match is not None
    assert resolved_view.phase == "in_round"
    assert resolved_view.current_player == "p1"
    assert resolved_match.staged_mulligans == ()
    assert len(resolved_match.event_log_payloads) == 6
    assert "p1_card_1" not in {card.instance_id for card in alice_resolved_view.viewer_hand}
    assert "p1_card_11" in {card.instance_id for card in alice_resolved_view.viewer_hand}
