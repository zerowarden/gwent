from __future__ import annotations

from collections.abc import Mapping

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext, TempoState
from gwent_engine.ai.baseline.leader_scoring import use_leader_action_score
from gwent_engine.ai.baseline.pass_logic import required_pass_lead
from gwent_engine.ai.baseline.pending_choice import (
    UnsupportedPendingChoiceError,
    explain_pending_choice_score_components,
)
from gwent_engine.ai.baseline.play_scoring import play_card_action_score
from gwent_engine.ai.baseline.profiles import HeuristicProfile
from gwent_engine.ai.baseline.projection import (
    current_public_board_projection,
)
from gwent_engine.ai.baseline.score_terms import (
    ActionScoreBreakdown,
    constant_term,
    term_detail,
    weighted_term,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.serialize.actions import action_to_id


def evaluate_action(
    action: GameAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> float:
    return explain_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=card_registry,
        leader_registry=leader_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    ).total


def explain_action_score(
    action: GameAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> ActionScoreBreakdown:
    if isinstance(action, LeaveAction):
        return _leave_action_score(action, profile=profile)
    if isinstance(action, PassAction):
        return _pass_action_score(
            action,
            observation=observation,
            assessment=assessment,
            context=context,
            profile=profile,
            card_registry=card_registry,
        )
    if isinstance(action, ResolveChoiceAction):
        return _resolve_choice_action_score(
            action,
            observation=observation,
            profile=profile,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if isinstance(action, UseLeaderAbilityAction):
        return use_leader_action_score(
            action,
            observation=observation,
            assessment=assessment,
            context=context,
            profile=profile,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if not isinstance(action, PlayCardAction):
        return _unsupported_action_score(action, profile=profile)
    return play_card_action_score(
        action,
        observation=observation,
        assessment=assessment,
        context=context,
        profile=profile,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )


def _leave_action_score(action: LeaveAction, *, profile: HeuristicProfile) -> ActionScoreBreakdown:
    return ActionScoreBreakdown(
        action=action,
        terms=(
            constant_term(
                "leave_penalty",
                profile.action_bonus.leave_penalty,
                formula="leave_penalty",
                details=(term_detail("leave_penalty", profile.action_bonus.leave_penalty),),
            ),
        ),
    )


def _pass_action_score(
    action: PassAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
) -> ActionScoreBreakdown:
    current_board = current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    if assessment.opponent_passed and current_board.score_gap > 0:
        return ActionScoreBreakdown(
            action=action,
            terms=(
                constant_term(
                    "pass_exact_finish_bonus",
                    profile.weights.exact_finish_bonus,
                    formula="exact_finish_bonus",
                    details=(
                        term_detail("exact_finish_bonus", profile.weights.exact_finish_bonus),
                    ),
                ),
                weighted_term(
                    "pass_resource_preservation",
                    raw_value=assessment.viewer.hand_value,
                    raw_label="viewer_hand_value",
                    weight=profile.weights.remaining_hand_value,
                    weight_label="remaining_hand_value",
                    details=(term_detail("viewer_hand_count", assessment.viewer.hand_count),),
                ),
            ),
        )
    required_lead = required_pass_lead(
        assessment,
        context=context,
        config=profile.pass_config,
    )
    pass_projection = current_board.score_gap - required_lead
    terms = [
        constant_term(
            "pass_tempo_penalty",
            -profile.weights.immediate_points,
            formula="-immediate_points",
            details=(term_detail("immediate_points", profile.weights.immediate_points),),
        ),
        weighted_term(
            "pass_projection",
            raw_value=pass_projection,
            raw_label="pass_projection_raw",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                term_detail("current_score_gap", current_board.score_gap),
                term_detail("required_pass_lead", required_lead),
            ),
        ),
    ]
    if _can_safely_preserve_resources_on_pass(
        context=context,
        pass_projection=pass_projection,
    ):
        terms.append(
            weighted_term(
                "pass_resource_preservation",
                raw_value=assessment.viewer.hand_value,
                raw_label="viewer_hand_value",
                weight=profile.weights.remaining_hand_value,
                weight_label="remaining_hand_value",
                details=(term_detail("viewer_hand_count", assessment.viewer.hand_count),),
            )
        )
    return ActionScoreBreakdown(action=action, terms=tuple(terms))


def _resolve_choice_action_score(
    action: ResolveChoiceAction,
    *,
    observation: PlayerObservation,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> ActionScoreBreakdown:
    try:
        components = explain_pending_choice_score_components(
            action,
            observation=observation,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    except UnsupportedPendingChoiceError as exc:
        return _unsupported_action_score(action, profile=profile, reason=str(exc))
    if not components:
        return _unsupported_action_score(action, profile=profile)
    return ActionScoreBreakdown(
        action=action,
        terms=tuple(
            constant_term(
                name,
                float(value),
                formula=name,
                details=(term_detail(name, float(value)),),
            )
            for name, value in components
        ),
    )


def _unsupported_action_score(
    action: GameAction,
    *,
    profile: HeuristicProfile,
    reason: str | None = None,
) -> ActionScoreBreakdown:
    penalty = profile.action_bonus.unsupported_action_penalty
    details = (
        (term_detail("unsupported_action_penalty", penalty),)
        if reason is None
        else (
            term_detail("unsupported_action_penalty", penalty),
            term_detail("unsupported_reason", reason),
        )
    )
    return ActionScoreBreakdown(
        action=action,
        terms=(
            constant_term(
                "unsupported_action_penalty",
                penalty,
                formula="unsupported_action_penalty",
                details=details,
            ),
        ),
    )


def explain_ranked_actions(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> tuple[ActionScoreBreakdown, ...]:
    return tuple(
        sorted(
            (
                explain_action_score(
                    action,
                    observation=observation,
                    assessment=assessment,
                    context=context,
                    profile=profile,
                    card_registry=card_registry,
                    leader_registry=leader_registry,
                    viewer_hand_definitions=viewer_hand_definitions,
                )
                for action in legal_actions
            ),
            key=lambda breakdown: (-breakdown.total, action_to_id(breakdown.action)),
        )
    )


def _can_safely_preserve_resources_on_pass(
    *,
    context: DecisionContext,
    pass_projection: int,
) -> bool:
    return context.tempo == TempoState.AHEAD and context.preserve_resources and pass_projection >= 0
