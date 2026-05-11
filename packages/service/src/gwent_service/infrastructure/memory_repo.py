from __future__ import annotations

from copy import deepcopy
from threading import Lock

from gwent_service.application.errors import (
    MatchAlreadyExistsError,
    MatchNotFoundError,
    MatchVersionConflictError,
)
from gwent_service.domain.models import StoredMatch


class InMemoryMatchRepository:
    def __init__(self) -> None:
        self._matches: dict[str, StoredMatch] = {}
        self._lock: Lock = Lock()

    def create(self, stored_match: StoredMatch) -> None:
        with self._lock:
            if stored_match.match_id in self._matches:
                raise MatchAlreadyExistsError(stored_match.match_id)
            self._matches[stored_match.match_id] = deepcopy(stored_match)

    def get(self, match_id: str) -> StoredMatch | None:
        with self._lock:
            stored_match = self._matches.get(match_id)
            if stored_match is None:
                return None
            return deepcopy(stored_match)

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None:
        with self._lock:
            current_match = self._matches.get(stored_match.match_id)
            if current_match is None:
                raise MatchNotFoundError(stored_match.match_id)
            if current_match.version != expected_version:
                raise MatchVersionConflictError(
                    stored_match.match_id,
                    expected_version=expected_version,
                    actual_version=current_match.version,
                )
            self._matches[stored_match.match_id] = deepcopy(stored_match)
