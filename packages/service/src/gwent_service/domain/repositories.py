from __future__ import annotations

from typing import Protocol

from gwent_service.domain.models import StoredMatch


class MatchRepository(Protocol):
    """Persistence port for match snapshots."""

    def get(self, match_id: str) -> StoredMatch | None: ...

    def create(self, stored_match: StoredMatch) -> None: ...

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None: ...
