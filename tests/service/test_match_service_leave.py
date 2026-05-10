from tests.service.support import build_create_match_command, build_service


def test_match_service_leave_match_ends_the_match_for_the_other_player() -> None:
    from gwent_service.application.commands import LeaveMatchCommand

    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(
            match_id="leave_match",
            alice_deck_id="scoiatael_high_stakes",
            bob_deck_id="scoiatael_high_stakes",
        ),
        viewer_service_player_id="alice",
    )

    view = service.leave_match(
        LeaveMatchCommand(
            match_id="leave_match",
            service_player_id="alice",
        )
    )
    stored_match = repository.get("leave_match")

    assert stored_match is not None
    assert view.status == "match_ended"
    assert view.phase == "match_ended"
    assert view.match_winner == "p2"
    assert view.viewer.gems_remaining == 0
    assert view.opponent.gems_remaining == 2
    assert stored_match.state_payload["match_winner"] == "p2"
