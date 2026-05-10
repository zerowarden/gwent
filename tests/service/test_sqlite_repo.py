from dataclasses import replace
from pathlib import Path

from gwent_service.domain.models import StagedMulliganSubmission, StoredMatch
from gwent_service.infrastructure.sqlite import SQLiteMatchRepository

from tests.service.support import build_stored_match


def _sqlite_match(*, version: int = 0) -> StoredMatch:
    return build_stored_match(
        match_id="sqlite_match",
        version=version,
        state_payload={
            "type": "game_state",
            "phase": "mulligan",
            "event_counter": 4,
            "players": [
                {"player_id": "p1"},
                {"player_id": "p2"},
            ],
        },
        event_log_payloads=(
            {"type": "game_started", "event_id": 1},
            {"type": "starting_player_chosen", "event_id": 2},
        ),
        staged_mulligans=(
            StagedMulliganSubmission(
                engine_player_id="p1",
                card_instance_ids=("p1_alpha_card",),
            ),
        ),
    )


def test_sqlite_repository_can_create_and_load_match_across_instances(tmp_path: Path) -> None:
    database_path = tmp_path / "matches.sqlite3"
    repository = SQLiteMatchRepository(database_path)
    stored_match = _sqlite_match()

    repository.create(stored_match)

    reloaded_repository = SQLiteMatchRepository(database_path)
    loaded_match = reloaded_repository.get("sqlite_match")

    assert loaded_match == stored_match


def test_sqlite_repository_update_persists_event_logs_and_staged_mulligans(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "matches.sqlite3"
    repository = SQLiteMatchRepository(database_path)
    repository.create(_sqlite_match())

    base_match = _sqlite_match(version=1)
    updated_match = replace(
        base_match,
        state_payload={
            **base_match.state_payload,
            "phase": "in_round",
        },
        event_log_payloads=(
            *base_match.event_log_payloads,
            {"type": "mulligan_resolved", "event_id": 3},
            {"type": "round_started", "event_id": 4},
        ),
        staged_mulligans=(
            StagedMulliganSubmission(
                engine_player_id="p1",
                card_instance_ids=("p1_replacement_card",),
            ),
            StagedMulliganSubmission(
                engine_player_id="p2",
                card_instance_ids=("p2_replacement_card",),
            ),
        ),
    )

    repository.update(updated_match)

    reloaded_repository = SQLiteMatchRepository(database_path)
    loaded_match = reloaded_repository.get("sqlite_match")

    assert loaded_match == updated_match
