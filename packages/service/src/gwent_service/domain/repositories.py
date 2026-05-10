from __future__ import annotations

from typing import Protocol

from gwent_service.domain.models import StoredMatch


class MatchReader(Protocol):
    def get(self, match_id: str) -> StoredMatch | None: ...


class MatchCreator(Protocol):
    def create(self, stored_match: StoredMatch) -> None: ...


class MatchUpdater(Protocol):
    def update(self, stored_match: StoredMatch) -> None: ...


class MatchRepository(MatchReader, MatchCreator, MatchUpdater, Protocol): ...
