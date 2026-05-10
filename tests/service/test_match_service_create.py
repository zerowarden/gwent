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
