"""Match creation and leaving through MatchService."""

import pytest
from gwent_service.domain import UnknownMatchPlayerError
from gwent_service.dto import LeaveMatchCommand

from tests.service.support import build_create_match_command, build_service


def test_match_service_create_match_starts_game_and_returns_safe_projection() -> None:
    service, repository = build_service()

    alice_view = service.create_match(
        build_create_match_command(match_id="create_match"),
        viewer_service_player_id="alice",
    )
    bob_view = service.get_match("create_match", viewer_service_player_id="bob")
    stored_match = repository.get("create_match")

    assert stored_match is not None
    assert alice_view.phase == "mulligan"
    assert alice_view.status == "in_progress"
    assert len(alice_view.viewer_hand) == 10
    assert alice_view.opponent.hand_count == 10
    assert bob_view.viewer_player_id == "bob"
    assert len(stored_match.event_log_payloads) == 4
    assert stored_match.state_payload["phase"] == "mulligan"
    assert stored_match.version == 1
    assert "p2_card_1" not in alice_view.model_dump_json()
    assert "p1_card_1" not in bob_view.model_dump_json()


def test_create_match_with_unknown_viewer_leaves_no_stored_match() -> None:
    service, repository = build_service()

    with pytest.raises(UnknownMatchPlayerError):
        _ = service.create_match(
            build_create_match_command(match_id="create_match"),
            viewer_service_player_id="mallory",
        )

    assert repository.get("create_match") is None

    created_view = service.create_match(
        build_create_match_command(match_id="create_match"),
        viewer_service_player_id="alice",
    )

    assert created_view.viewer_player_id == "alice"


def test_match_service_leave_match_ends_the_match_for_the_other_player() -> None:
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
