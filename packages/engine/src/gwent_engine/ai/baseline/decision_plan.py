from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.actions import filter_non_leave_actions
from gwent_engine.ai.baseline.assessment import DecisionAssessment, build_assessment
from gwent_engine.ai.baseline.candidates import (
    CandidateAction,
    build_candidate_pool,
    shortlist_actions,
)
from gwent_engine.ai.baseline.context import DecisionContext, classify_context
from gwent_engine.ai.baseline.evaluation import explain_ranked_actions
from gwent_engine.ai.baseline.pass_logic import (
    minimum_commitment_finish,
    should_cut_losses_after_pass,
    should_pass_now,
)
from gwent_engine.ai.baseline.profile_catalog import (
    DEFAULT_BASE_PROFILE,
    BaseProfileDefinition,
)
from gwent_engine.ai.baseline.profiles import HeuristicProfile, compose_profile
from gwent_engine.ai.baseline.score_terms import ActionScoreBreakdown
from gwent_engine.ai.observation_queries import build_viewer_hand_definition_index
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, BaselineConfig, PassConfig
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core.actions import GameAction, PassAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.serialize.actions import action_to_id


@dataclass(frozen=True, slots=True)
class DecisionPlan:
    observation: PlayerObservation
    legal_actions: tuple[GameAction, ...]
    candidate_actions: tuple[GameAction, ...]
    viewer_hand_definitions: dict[CardInstanceId, CardDefinition]
    assessment: DecisionAssessment
    context: DecisionContext
    profile: HeuristicProfile
    all_candidates: tuple[CandidateAction, ...]
    candidates: tuple[CandidateAction, ...]
    shortlisted_actions: tuple[GameAction, ...]
    ranked_actions: tuple[ActionScoreBreakdown, ...]
    override: TacticalOverride | None
    chosen_action: GameAction


def build_decision_plan(
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    config: BaselineConfig = DEFAULT_BASELINE_CONFIG,
    profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
) -> DecisionPlan:
    if not legal_actions:
        raise ValueError("Decision plan requires at least one legal action.")
    candidate_actions = filter_non_leave_actions(legal_actions)
    viewer_hand_definitions = build_viewer_hand_definition_index(observation, card_registry)
    assessment = build_assessment(
        observation,
        card_registry,
        legal_actions=candidate_actions,
    )
    context = classify_context(assessment)
    profile = compose_profile(
        config,
        assessment,
        context,
        base_profile=profile_definition,
    )
    candidate_pool = build_candidate_pool(
        observation,
        candidate_actions,
        config=config,
        card_registry=card_registry,
        leader_registry=leader_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    candidates = candidate_pool.retained_candidates
    shortlisted_actions = shortlist_actions(candidates, candidate_limit=profile.candidate_limit)
    ranked_actions = explain_ranked_actions(
        shortlisted_actions,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=card_registry,
        leader_registry=leader_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    override = explain_tactical_override(
        candidate_actions,
        observation=observation,
        assessment=assessment,
        context=context,
        card_registry=card_registry,
        pass_config=profile.pass_config,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    chosen_action = (
        override.action
        if override is not None
        else ranked_actions[0].action
        if ranked_actions
        else min(candidate_actions, key=action_to_id)
    )
    return DecisionPlan(
        observation=observation,
        legal_actions=legal_actions,
        candidate_actions=candidate_actions,
        viewer_hand_definitions=viewer_hand_definitions,
        assessment=assessment,
        context=context,
        profile=profile,
        all_candidates=candidate_pool.all_candidates,
        candidates=candidates,
        shortlisted_actions=shortlisted_actions,
        ranked_actions=ranked_actions,
        override=override,
        chosen_action=chosen_action,
    )


@dataclass(frozen=True, slots=True)
class TacticalOverride:
    action: GameAction
    reason: str


def explain_tactical_override(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    card_registry: CardRegistry,
    pass_config: PassConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> TacticalOverride | None:
    exact_finish = minimum_commitment_finish(
        legal_actions,
        observation=observation,
        assessment=assessment,
        card_registry=card_registry,
        config=pass_config,
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
        config=pass_config,
        viewer_hand_definitions=viewer_hand_definitions,
    ):
        for action in legal_actions:
            if isinstance(action, PassAction):
                return TacticalOverride(
                    action=action,
                    reason="hopeless_catch_up_pass",
                )
    if should_pass_now(assessment, context, config=pass_config):
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
