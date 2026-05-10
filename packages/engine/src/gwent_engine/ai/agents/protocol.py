from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import GameAction, MulliganSelection, ResolveChoiceAction
from gwent_engine.leaders import LeaderRegistry


class BotAgent(Protocol):
    bot_id: str
    display_name: str

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection: ...

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction: ...

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction: ...
