from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.pass_logic import (
    minimum_commitment_finish,
    should_cut_losses_after_pass,
    should_pass_now,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import BaselineConfig
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core.actions import GameAction, PassAction
from gwent_engine.core.ids import CardInstanceId


@dataclass(frozen=True, slots=True)
class TacticalOverride:
    action: GameAction
    reason: str


def choose_tactical_override(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    card_registry: CardRegistry,
    config: BaselineConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> GameAction | None:
    override = explain_tactical_override(
        legal_actions,
        observation=observation,
        assessment=assessment,
        context=context,
        card_registry=card_registry,
        config=config,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    return None if override is None else override.action


def explain_tactical_override(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    card_registry: CardRegistry,
    config: BaselineConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> TacticalOverride | None:
    exact_finish = minimum_commitment_finish(
        legal_actions,
        observation=observation,
        assessment=assessment,
        card_registry=card_registry,
        config=config.pass_logic,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    if exact_finish is not None:
        return TacticalOverride(
            action=exact_finish,
            reason="minimum_commitment_finish",
        )
    if should_cut_losses_after_pass(
        legal_actions,
        observation=observation,
        assessment=assessment,
        card_registry=card_registry,
        config=config.pass_logic,
        viewer_hand_definitions=viewer_hand_definitions,
    ):
        for action in legal_actions:
            if isinstance(action, PassAction):
                return TacticalOverride(
                    action=action,
                    reason="hopeless_catch_up_pass",
                )
    if should_pass_now(assessment, context, config=config.pass_logic):
        for action in legal_actions:
            if isinstance(action, PassAction):
                return TacticalOverride(
                    action=action,
                    reason="safe_pass",
                )
    if len(legal_actions) == 1:
        return TacticalOverride(
            action=legal_actions[0],
            reason="single_legal_action",
        )
    return None
