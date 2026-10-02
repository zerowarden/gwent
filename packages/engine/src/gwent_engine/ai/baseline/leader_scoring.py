"""Leader-ability scoring terms for the heuristic evaluator."""

from __future__ import annotations

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.policies import leader_policy_components
from gwent_engine.ai.baseline.profiles import HeuristicProfile
from gwent_engine.ai.baseline.projection import (
    LeaderActionProjection,
    project_leader_action,
)
from gwent_engine.ai.baseline.score_terms import (
    ActionScoreBreakdown,
    ScoreTerm,
    ScoreTermDetail,
    constant_term,
    term_detail,
    weighted_term,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_EVALUATION_POLICY
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    UseLeaderAbilityAction,
)
from gwent_engine.leaders import LeaderRegistry


def use_leader_action_score(
    action: UseLeaderAbilityAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> ActionScoreBreakdown:
    leader_projection = project_leader_action(
        action,
        observation=observation,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    return ActionScoreBreakdown(
        action=action,
        terms=_leader_action_terms(
            assessment=assessment,
            context=context,
            profile=profile,
            leader_projection=leader_projection,
        ),
    )


def _leader_action_terms(
    *,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    leader_projection: LeaderActionProjection | None,
) -> tuple[ScoreTerm, ...]:
    """Score leader usage from actual projected effect, not just urgency.

    Live leader activations keep the generic appetite terms. Leader lines with
    no projected effect collapse to reserve cost plus an explicit no-effect
    penalty so they do not outrank productive plays.
    """

    generic_terms = tuple(
        constant_term(
            name,
            value,
            formula=name,
            details=(
                term_detail("leader_policy", profile.policy_names.leader),
                term_detail("score_gap", assessment.score_gap),
                term_detail("pressure", context.pressure.value),
                term_detail("tempo", context.tempo.value),
            ),
        )
        for name, value in leader_policy_components(
            policy_name=profile.policy_names.leader,
            assessment=assessment,
            context=context,
            profile=profile,
        )
    )
    if leader_projection is None:
        return generic_terms
    reserve_cost = next(term.value for term in generic_terms if term.name == "leader_reserve_cost")
    live_context_terms = tuple(
        term
        for term in generic_terms
        if term.name not in {"leader_reserve_cost", "leader_round_pressure"}
    )
    if not leader_projection.has_effect:
        no_effect_penalty = (
            -profile.weights.exact_finish_bonus if assessment.opponent_passed else 0.0
        )
        return (
            constant_term(
                "leader_no_effect_penalty",
                no_effect_penalty,
                formula=(
                    "-exact_finish_bonus"
                    if assessment.opponent_passed
                    else "0 (no-op wait move allowed before opponent passes)"
                ),
                details=(
                    term_detail("exact_finish_bonus", profile.weights.exact_finish_bonus),
                    term_detail("opponent_passed", "yes" if assessment.opponent_passed else "no"),
                    *_leader_projection_details(leader_projection),
                    term_detail("leader_live_targets", leader_projection.live_targets),
                    term_detail("opponent_row_total", leader_projection.opponent_row_total or 0),
                    term_detail("minimum_row_total", leader_projection.minimum_row_total or 0),
                ),
            ),
            constant_term(
                "leader_reserve_cost",
                reserve_cost,
                formula="leader_reserve_cost",
                details=(term_detail("leader_policy", profile.policy_names.leader),),
            ),
        )
    evaluation_policy = DEFAULT_EVALUATION_POLICY
    live_commitment_cost = reserve_cost / max(
        profile.preserve_resources_bias * evaluation_policy.leader_live_commitment_bias_multiplier,
        evaluation_policy.leader_live_commitment_min_divisor,
    )
    terms: list[ScoreTerm] = [
        weighted_term(
            "leader_projected_swing",
            raw_value=leader_projection.projected_net_board_swing,
            raw_label="leader_projected_net_board_swing",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                *_leader_projection_details(leader_projection),
                term_detail("leader_live_targets", leader_projection.live_targets),
                term_detail("opponent_row_total", leader_projection.opponent_row_total or 0),
                term_detail("minimum_row_total", leader_projection.minimum_row_total or 0),
            ),
        ),
    ]
    if leader_projection.projected_hand_value_delta:
        terms.append(
            weighted_term(
                "leader_projected_hand_value",
                raw_value=leader_projection.projected_hand_value_delta,
                raw_label="leader_projected_hand_value_delta",
                weight=profile.weights.remaining_hand_value,
                weight_label="remaining_hand_value",
                details=_leader_projection_details(leader_projection),
            )
        )
    if leader_projection.viewer_hand_count_delta:
        terms.append(
            weighted_term(
                "leader_projected_card_advantage",
                raw_value=leader_projection.viewer_hand_count_delta,
                raw_label="leader_viewer_hand_count_delta",
                weight=profile.weights.card_advantage,
                weight_label="card_advantage",
                details=_leader_projection_details(leader_projection),
            )
        )
    terms.extend(live_context_terms)
    terms.append(
        constant_term(
            "leader_commitment_cost",
            live_commitment_cost,
            formula="leader_reserve_cost / max(preserve_resources_bias * 2, 3)",
            details=(
                term_detail("leader_policy", profile.policy_names.leader),
                term_detail("leader_reserve_cost", reserve_cost),
                term_detail("preserve_resources_bias", profile.preserve_resources_bias),
            ),
        )
    )
    return tuple(terms)


def _leader_projection_details(
    leader_projection: LeaderActionProjection,
) -> tuple[ScoreTermDetail, ...]:
    details = [term_detail("leader_ability_kind", leader_projection.ability_kind.value)]
    if leader_projection.projected_hand_value_delta:
        details.append(
            term_detail(
                "leader_projected_hand_value_delta",
                leader_projection.projected_hand_value_delta,
            )
        )
    if leader_projection.viewer_hand_count_delta:
        details.append(
            term_detail("leader_viewer_hand_count_delta", leader_projection.viewer_hand_count_delta)
        )
    if leader_projection.affected_row is not None:
        details.append(term_detail("affected_row", leader_projection.affected_row.value))
    if leader_projection.weather_rows_changed:
        details.append(
            term_detail(
                "weather_rows_changed",
                ", ".join(row.value for row in leader_projection.weather_rows_changed),
            )
        )
    if leader_projection.moved_units:
        details.append(term_detail("moved_units", leader_projection.moved_units))
    return tuple(details)
