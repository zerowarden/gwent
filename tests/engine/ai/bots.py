"""Reusable bot doubles for match-driver and evaluation tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import override

from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardRegistry
from gwent_engine.core import Row
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry

from tests.engine.support import LEADER_REGISTRY


@dataclass
class DelegatingBot:
    """Base double that forwards every decision to a wrapped agent.

    Subclasses override only the decisions they need to intercept.
    """

    delegate: BotAgent
    bot_id: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.bot_id:
            self.bot_id = self.delegate.bot_id
        if not self.display_name:
            self.display_name = self.delegate.display_name

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        return self.delegate.choose_mulligan(
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        return self.delegate.choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        return self.delegate.choose_pending_choice(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


@dataclass
class CountingBot(DelegatingBot):
    mulligan_calls: int = 0
    action_calls: int = 0
    pending_choice_calls: int = 0

    @override
    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        self.mulligan_calls += 1
        return super().choose_mulligan(
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        self.action_calls += 1
        return super().choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    @override
    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        self.pending_choice_calls += 1
        return super().choose_pending_choice(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


@dataclass
class LeaderChoiceBot(DelegatingBot):
    """Plays the first legal leader action and resolves its pending choice."""

    valid_split: bool = True
    bot_id: str = "leader_choice_bot"
    display_name: str = "LeaderChoiceBot"

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        leader_action = _first_leader_action(legal_actions)
        if leader_action is not None:
            return leader_action
        return super().choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    @override
    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del card_registry, leader_registry
        if self.valid_split:
            return _valid_leader_selection(observation, legal_actions)
        return _invalid_leader_selection(observation, legal_actions)


@dataclass
class FailingBot(DelegatingBot):
    error: Exception = field(default_factory=lambda: RuntimeError("fixture failure"))
    bot_id: str = "failing_bot"
    display_name: str = "FailingBot"

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del observation, legal_actions, card_registry, leader_registry
        raise self.error

    @override
    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del observation, legal_actions, card_registry, leader_registry
        raise self.error


@dataclass
class FailingAfterBot(DelegatingBot):
    """Delegates until `fail_after` actions have been chosen, then raises."""

    fail_after: int = 0
    error: Exception = field(default_factory=lambda: RuntimeError("fixture failure"))
    action_calls: int = field(default=0, init=False)
    bot_id: str = "failing_after_bot"
    display_name: str = "FailingAfterBot"

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        self.action_calls += 1
        if self.action_calls > self.fail_after:
            raise self.error
        return super().choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


@dataclass
class AlwaysPassBot(DelegatingBot):
    bot_id: str = "always_pass_bot"
    display_name: str = "AlwaysPassBot"

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del legal_actions, card_registry, leader_registry
        return PassAction(player_id=observation.viewer_player_id)


@dataclass
class IllegalActionBot(DelegatingBot):
    bot_id: str = "illegal_action_bot"
    display_name: str = "IllegalActionBot"

    @override
    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del legal_actions, card_registry, leader_registry
        return PlayCardAction(
            player_id=observation.viewer_player_id,
            card_instance_id=CardInstanceId("not_a_real_card"),
            target_row=Row.CLOSE,
        )

    @override
    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del observation, legal_actions, card_registry, leader_registry
        raise AssertionError("IllegalActionBot does not expect a pending choice.")


@dataclass
class ThrowingBot:
    """Agent double that raises from every decision entry point."""

    bot_id: str
    display_name: str = "ThrowingBot"
    message: str = "fixture failure"

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        del observation, legal_selections, card_registry, leader_registry
        raise RuntimeError(self.message)

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del observation, legal_actions, card_registry, leader_registry
        raise RuntimeError(self.message)

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del observation, legal_actions, card_registry, leader_registry
        raise RuntimeError(self.message)


def _first_leader_action(legal_actions: Sequence[GameAction]) -> UseLeaderAbilityAction | None:
    return next(
        (action for action in legal_actions if isinstance(action, UseLeaderAbilityAction)),
        None,
    )


def _valid_leader_selection(
    observation: PlayerObservation,
    legal_actions: Sequence[GameAction],
) -> ResolveChoiceAction:
    visible = observation.visible_pending_choice
    assert visible is not None
    assert visible.source_leader_id is not None
    leader_definition = LEADER_REGISTRY.get(visible.source_leader_id)
    hand_ids = [card.instance_id for card in observation.viewer_hand]
    deck_ids = [
        instance_id
        for entry in observation.viewer_deck_composition
        for instance_id in entry.instance_ids
    ]
    desired = frozenset(
        hand_ids[: leader_definition.hand_discard_count]
        + deck_ids[: leader_definition.deck_pick_count]
    )
    for action in legal_actions:
        if (
            isinstance(action, ResolveChoiceAction)
            and frozenset(action.selected_card_instance_ids) == desired
        ):
            return action
    raise AssertionError("No legal selection matched the scripted discard-and-choose split.")


def _invalid_leader_selection(
    observation: PlayerObservation,
    legal_actions: Sequence[GameAction],
) -> ResolveChoiceAction:
    hand_ids = {card.instance_id for card in observation.viewer_hand}
    for action in legal_actions:
        if (
            isinstance(action, ResolveChoiceAction)
            and len(frozenset(action.selected_card_instance_ids) & hand_ids) != 2
        ):
            return action
    raise AssertionError("No shallow-valid selection with an invalid hand/deck split was offered.")
