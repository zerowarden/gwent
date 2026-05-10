from __future__ import annotations

from collections.abc import Sequence

from gwent_engine.ai.baseline import build_assessment, build_candidate_pool
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, SearchConfig
from gwent_engine.ai.search.types import SearchCandidate
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import GameAction
from gwent_engine.leaders import LeaderRegistry


def generate_search_candidates(
    observation: PlayerObservation,
    legal_actions: Sequence[GameAction],
    *,
    config: SearchConfig,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[SearchCandidate, ...]:
    """Build the root candidate set.

    Search owns the final choice, but it may still reuse baseline coarse
    candidate signals as ordering hints and branch-control guidance.
    """

    action_options = tuple(legal_actions)
    if not action_options:
        return ()
    assessment = build_assessment(
        observation,
        card_registry,
        legal_actions=action_options,
    )
    pool = build_candidate_pool(
        observation,
        action_options,
        assessment,
        config=DEFAULT_BASELINE_CONFIG,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    return tuple(
        SearchCandidate(
            action=candidate.action,
            ordering_score=candidate.coarse_score,
            reason=candidate.reason,
        )
        for candidate in pool.retained_candidates[: config.max_candidate_actions]
    )
