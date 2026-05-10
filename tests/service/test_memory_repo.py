from dataclasses import replace

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
    repository.create(build_stored_match(match_id="memory_match"))

    updated_match = replace(
        build_stored_match(match_id="memory_match"),
        version=1,
        event_log_payloads=({"type": "starting_player_chosen", "event_id": 1},),
    )
    repository.update(updated_match)

    assert repository.get("memory_match") == updated_match
