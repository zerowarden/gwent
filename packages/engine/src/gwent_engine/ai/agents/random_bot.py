from __future__ import annotations

from collections.abc import Sequence
from random import Random
from typing import final

from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
    ResolveChoiceAction,
)
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.leaders import LeaderRegistry


@final
class RandomBot:
    def __init__(self, *, seed: int | None = None, bot_id: str = "random_bot") -> None:
        self.bot_id = bot_id
        self.display_name = "RandomBot"
        self._random = Random(seed)

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        del observation, card_registry, leader_registry
        return _choose_random(self._random, legal_selections)

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del observation, card_registry, leader_registry
        non_leave_actions = tuple(
            action for action in legal_actions if not isinstance(action, LeaveAction)
        )
        non_pass_actions = tuple(
            action for action in non_leave_actions if not isinstance(action, PassAction)
        )
        return _choose_random(self._random, non_pass_actions or non_leave_actions or legal_actions)

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del observation, card_registry, leader_registry
        action = _choose_random(self._random, legal_actions)
        if not isinstance(action, ResolveChoiceAction):
            raise IllegalActionError("Pending choice selection requires ResolveChoiceAction.")
        return action


def _choose_random[T](random_source: Random, options: Sequence[T]) -> T:
    if not options:
        raise ValueError("RandomBot requires at least one legal option.")
    return options[random_source.randrange(len(options))]
