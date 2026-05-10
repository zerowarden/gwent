from __future__ import annotations

from gwent_engine.ai.actions import action_to_id
from gwent_engine.ai.search.types import SearchCandidate


def order_search_candidates(
    candidates: tuple[SearchCandidate, ...],
) -> tuple[SearchCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (-candidate.ordering_score, action_to_id(candidate.action)),
        )
    )
