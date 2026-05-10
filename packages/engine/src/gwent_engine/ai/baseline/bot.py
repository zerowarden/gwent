from __future__ import annotations

from collections.abc import Sequence
from typing import final

from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.decision_plan import build_decision_plan
from gwent_engine.ai.baseline.mulligan import choose_mulligan_selection
from gwent_engine.ai.baseline.pending_choice import choose_pending_choice_action
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    get_base_profile_definition,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, BaselineConfig
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    ResolveChoiceAction,
)
from gwent_engine.leaders import LeaderRegistry


@final
class HeuristicBot:
    def __init__(
        self,
        *,
        config: BaselineConfig = DEFAULT_BASELINE_CONFIG,
        profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
        bot_id: str = "heuristic_bot",
    ) -> None:
        self.bot_id = bot_id
        self.display_name = (
            "HeuristicBot"
            if profile_definition.profile_id == DEFAULT_BASE_PROFILE.profile_id
            else f"HeuristicBot[{profile_definition.profile_id}]"
        )
        self._config = config
        self._profile_definition = profile_definition

    @staticmethod
    def from_profile_id(*, bot_id: str, profile_id: str | None) -> HeuristicBot:
        if profile_id is None:
            return HeuristicBot(bot_id=bot_id)
        return HeuristicBot(
            bot_id=bot_id,
            profile_definition=get_base_profile_definition(profile_id),
        )

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        del leader_registry
        options = tuple(legal_selections)
        if not options:
            raise ValueError("HeuristicBot requires at least one mulligan selection.")
        assessment = build_assessment(observation, card_registry)
        return choose_mulligan_selection(
            observation,
            options,
            assessment=assessment,
            card_registry=card_registry,
        )

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("HeuristicBot requires at least one legal action.")
        plan = build_decision_plan(
            observation,
            actions,
            card_registry=card_registry,
            leader_registry=leader_registry,
            config=self._config,
            profile_definition=self._profile_definition,
        )
        return plan.chosen_action

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        return choose_pending_choice_action(
            observation,
            tuple(legal_actions),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
