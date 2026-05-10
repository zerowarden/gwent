from __future__ import annotations

from copy import deepcopy

from gwent_service.application.errors import MatchAlreadyExistsError, MatchNotFoundError
from gwent_service.domain.models import StoredMatch


class InMemoryMatchRepository:
    def __init__(self) -> None:
        self._matches: dict[str, StoredMatch] = {}

    def create(self, stored_match: StoredMatch) -> None:
        if stored_match.match_id in self._matches:
            raise MatchAlreadyExistsError(stored_match.match_id)
        self._matches[stored_match.match_id] = deepcopy(stored_match)

    def get(self, match_id: str) -> StoredMatch | None:
        stored_match = self._matches.get(match_id)
        if stored_match is None:
            return None
        return deepcopy(stored_match)

    def update(self, stored_match: StoredMatch) -> None:
        if stored_match.match_id not in self._matches:
            raise MatchNotFoundError(stored_match.match_id)
        self._matches[stored_match.match_id] = deepcopy(stored_match)
