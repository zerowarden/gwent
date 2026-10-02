from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import final

from gwent_engine.ai.baseline.assessment import DecisionAssessment, build_assessment
from gwent_engine.ai.baseline.decision_plan import build_decision_plan
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.baseline.pending_choice import choose_pending_choice_action
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
    profile_bot_display_name,
)
from gwent_engine.ai.mulligan_scoring import best_mulligan_selection
from gwent_engine.ai.observation_queries import build_viewer_hand_definition_index
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, DEFAULT_MULLIGAN_POLICY, BaselineConfig
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
        # Keep the configuration codec independent of baseline's eager exports.
        from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration

        self._configuration = HeuristicConfiguration(baseline=config, profile=profile_definition)
        self.bot_id = bot_id
        self.display_name = profile_bot_display_name("HeuristicBot", self._configuration.profile)

    @property
    def configuration(self) -> HeuristicConfiguration:
        return self._configuration

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
            config=self._configuration.baseline,
            profile_definition=self._configuration.profile,
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


def choose_mulligan_selection(
    observation: PlayerObservation,
    legal_selections: tuple[MulliganSelection, ...],
    *,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
) -> MulliganSelection:
    if not legal_selections:
        raise ValueError("choose_mulligan_selection requires at least one legal selection.")
    return best_mulligan_selection(
        legal_selections,
        build_viewer_hand_definition_index(observation, card_registry),
        Counter(definition.definition_id for definition in assessment.viewer.hand_definitions),
        weights=DEFAULT_MULLIGAN_POLICY.baseline,
        prefer_highest_card_ids=True,
    )
