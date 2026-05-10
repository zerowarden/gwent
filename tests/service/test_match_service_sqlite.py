from pathlib import Path

from gwent_service.application.commands import PassTurnCommand, SubmitMulliganCommand
from gwent_service.application.match_service import MatchService
from gwent_service.engine.adapter import GwentEngineAdapter
from gwent_service.infrastructure.sqlite import SQLiteMatchRepository

from tests.service.support import build_create_match_command, identity_rng_factory


def _build_sqlite_service(database_path: Path) -> tuple[MatchService, SQLiteMatchRepository]:
    repository = SQLiteMatchRepository(database_path)
    service = MatchService(
        repository=repository,
        adapter=GwentEngineAdapter(),
        rng_factory=identity_rng_factory,
    )
    return service, repository


def test_match_service_works_unchanged_with_sqlite_repository(tmp_path: Path) -> None:
    database_path = tmp_path / "matches.sqlite3"
    service, repository = _build_sqlite_service(database_path)

    created_view = service.create_match(
        build_create_match_command(
            match_id="sqlite_service_match",
            alice_deck_id="scoiatael_high_stakes",
            bob_deck_id="scoiatael_high_stakes",
        ),
        viewer_service_player_id="alice",
    )
    staged_view = service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="sqlite_service_match",
            service_player_id="alice",
            card_instance_ids=("p1_card_1",),
        )
    )

    staged_match = repository.get("sqlite_service_match")
    assert staged_match is not None
    assert created_view.phase == "mulligan"
    assert staged_view.phase == "mulligan"
    assert len(staged_match.staged_mulligans) == 1
    assert len(staged_match.event_log_payloads) == 4

    restarted_service, _ = _build_sqlite_service(database_path)
    reloaded_view = restarted_service.get_match(
        "sqlite_service_match",
        viewer_service_player_id="alice",
    )
    assert reloaded_view.phase == "mulligan"
    assert reloaded_view.mulligan_submissions[0].submitted is True
    assert reloaded_view.mulligan_submissions[1].submitted is False

    resolved_view = restarted_service.submit_mulligan(
        SubmitMulliganCommand(
            match_id="sqlite_service_match",
            service_player_id="bob",
            card_instance_ids=(),
        )
    )
    assert resolved_view.phase == "in_round"
    assert resolved_view.current_player == "p1"

    restarted_service_again, repository_again = _build_sqlite_service(database_path)
    loaded_match = repository_again.get("sqlite_service_match")
    assert loaded_match is not None
    assert loaded_match.staged_mulligans == ()
    assert len(loaded_match.event_log_payloads) == 6

    passed_view = restarted_service_again.pass_turn(
        PassTurnCommand(
            match_id="sqlite_service_match",
            service_player_id="alice",
        )
    )

    final_service, final_repository = _build_sqlite_service(database_path)
    final_match = final_repository.get("sqlite_service_match")
    bob_view = final_service.get_match("sqlite_service_match", viewer_service_player_id="bob")

    assert final_match is not None
    assert passed_view.viewer.has_passed is True
    assert passed_view.current_player == "p2"
    assert len(final_match.event_log_payloads) == 7
    assert bob_view.phase == "in_round"
    assert bob_view.current_player == "p2"
