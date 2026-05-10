from __future__ import annotations

from collections.abc import Sequence

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.action_legality import is_legal_action
from gwent_engine.ai.mulligan_actions import enumerate_mulligan_selections
from gwent_engine.ai.turn_actions import enumerate_candidate_actions
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import GameAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry

__all__ = [
    "action_to_id",
    "enumerate_legal_actions",
    "enumerate_mulligan_selections",
    "legal_action_mask",
]


def enumerate_legal_actions(
    state: GameState,
    *,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
    rng: SupportsRandom | None = None,
    player_id: PlayerId | None = None,
) -> tuple[GameAction, ...]:
    candidate_actions = enumerate_candidate_actions(
        state,
        card_registry=card_registry,
        leader_registry=leader_registry,
        player_id=player_id,
    )
    return tuple(
        action
        for action in candidate_actions
        if is_legal_action(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    )


def legal_action_mask(
    candidates: Sequence[GameAction],
    legal_actions: Sequence[GameAction],
) -> tuple[int, ...]:
    legal_ids = {action_to_id(action) for action in legal_actions}
    return tuple(1 if action_to_id(action) in legal_ids else 0 for action in candidates)
