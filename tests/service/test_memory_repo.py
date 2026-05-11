from dataclasses import replace

import pytest
from gwent_service.application.errors import MatchNotFoundError, MatchVersionConflictError
from gwent_service.infrastructure.memory_repo import InMemoryMatchRepository

from tests.service.support import build_stored_match


def test_memory_repository_can_create_and_load_match() -> None:
    repository = InMemoryMatchRepository()
    stored_match = build_stored_match(match_id="memory_match")

    repository.create(stored_match)
    loaded_match = repository.get("memory_match")

    assert loaded_match == stored_match
    assert loaded_match is not stored_match


def test_memory_repository_can_update_match() -> None:
    repository = InMemoryMatchRepository()
    created_match = build_stored_match(match_id="memory_match")
    repository.create(created_match)

    updated_match = replace(
        created_match,
        version=1,
        event_log_payloads=({"type": "starting_player_chosen", "event_id": 1},),
    )
    repository.update(updated_match, expected_version=created_match.version)

    assert repository.get("memory_match") == updated_match


def test_memory_repository_rejects_update_from_stale_version() -> None:
    repository = InMemoryMatchRepository()
    created_match = build_stored_match(match_id="memory_match")
    repository.create(created_match)

    first_writer_match = replace(created_match, version=1)
    second_writer_match = replace(
        created_match,
        version=1,
        event_log_payloads=({"type": "starting_player_chosen", "event_id": 1},),
    )

    repository.update(first_writer_match, expected_version=created_match.version)

    with pytest.raises(MatchVersionConflictError) as conflict:
        repository.update(second_writer_match, expected_version=created_match.version)

    assert conflict.value.expected_version == created_match.version
    assert conflict.value.actual_version == first_writer_match.version
    assert repository.get("memory_match") == first_writer_match


def test_memory_repository_update_of_missing_match_raises_not_found() -> None:
    repository = InMemoryMatchRepository()

    stale_match = build_stored_match(match_id="memory_match", version=1)

    with pytest.raises(MatchNotFoundError):
        repository.update(stale_match, expected_version=0)
