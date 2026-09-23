import pytest
from gwent_engine.core.errors import IllegalActionError
from gwent_service.application.commands import SubmitMulliganCommand
from gwent_service.application.errors import MatchVersionConflictError

from tests.service.support import (
    StaleSnapshotRepository,
    build_create_match_command,
    build_service,
    build_service_with_repository,
)


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


def test_invalid_mulligan_submission_leaves_match_unchanged_and_can_be_corrected() -> None:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(match_id="mulligan_match"),
        viewer_service_player_id="alice",
    )
    match_before_submission = repository.get("mulligan_match")
    assert match_before_submission is not None

    with pytest.raises(IllegalActionError, match="is not in player"):
        _ = service.submit_mulligan(
            SubmitMulliganCommand(
                match_id="mulligan_match",
                service_player_id="alice",
                card_instance_ids=("p1_card_not_in_hand",),
            )
        )

    assert repository.get("mulligan_match") == match_before_submission

    staged_view = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="mulligan_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_1",),
        )
    )
    resolved_view = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="mulligan_match",
            service_player_id="bob",
            card_instance_ids=(),
        )
    )

    assert staged_view.phase == "mulligan"
    assert resolved_view.phase == "in_round"


def test_submit_mulligan_from_stale_snapshot_does_not_overwrite_committed_state() -> None:
    service, repository = build_service()
    _ = service.create_match(
        build_create_match_command(match_id="mulligan_match"),
        viewer_service_player_id="alice",
    )
    stale_snapshot = repository.get("mulligan_match")
    assert stale_snapshot is not None

    _ = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="mulligan_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_1",),
        )
    )

    stale_service = build_service_with_repository(
        StaleSnapshotRepository(repository, stale_snapshot)
    )
    with pytest.raises(MatchVersionConflictError):
        _ = stale_service.submit_mulligan(
            SubmitMulliganCommand(
                match_id="mulligan_match",
                service_player_id="bob",
                card_instance_ids=(),
            )
        )

    committed_match = repository.get("mulligan_match")
    assert committed_match is not None
    staged_engine_player_ids = [
        submission.engine_player_id for submission in committed_match.staged_mulligans
    ]
    assert committed_match.version == stale_snapshot.version + 1
    assert staged_engine_player_ids == ["p1"]
