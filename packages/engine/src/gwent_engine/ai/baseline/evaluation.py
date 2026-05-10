from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass

from gwent_engine.ai.actions import action_to_id
from gwent_engine.ai.baseline.assessment import DecisionAssessment, PlayerAssessment, RowSummary
from gwent_engine.ai.baseline.context import DecisionContext, PressureMode, TacticalMode, TempoState
from gwent_engine.ai.baseline.pending_choice import explain_pending_choice_score_components
from gwent_engine.ai.baseline.policies.leader import leader_policy_components
from gwent_engine.ai.baseline.profiles import HeuristicProfile
from gwent_engine.ai.baseline.projection import (
    LeaderActionProjection,
    PlayActionProjection,
    ScorchImpact,
    current_public_board_projection,
    project_leader_action,
    project_play_action,
)
from gwent_engine.ai.baseline.projection.context import visible_battlefield_cards
from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.ai.policy import DEFAULT_EVALUATION_POLICY, DEFAULT_FEATURE_POLICY
from gwent_engine.ai.utils import viewer_hand_definition
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
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
from gwent_engine.rules.battlefield_effects import is_weather_ability, weather_rows_for
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True, slots=True)
class ScoreTermDetail:
    key: str
    value: float | int | str


@dataclass(frozen=True, slots=True)
class ScoreTerm:
    name: str
    value: float
    formula: str | None = None
    raw_value: float | None = None
    raw_label: str | None = None
    weight: float | None = None
    weight_label: str | None = None
    details: tuple[ScoreTermDetail, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionScoreBreakdown:
    action: GameAction
    terms: tuple[ScoreTerm, ...]

    @property
    def total(self) -> float:
        return sum(term.value for term in self.terms)


@dataclass(frozen=True, slots=True)
class OvercommitmentPenaltyBreakdown:
    value: float
    excess_points: int
    premium_cost: float
    current_score_gap: int
    projected_score_gap_after: int
    required_score_gap_after: int
    true_overcommit_gap_after: int
    opponent_counter_capacity: int
    trickery_allowance: int
    overcommit_window_active: bool
    legal_play_count: int


def _detail(key: str, value: float | int | str) -> ScoreTermDetail:
    return ScoreTermDetail(key=key, value=value)


def _constant_term(
    name: str,
    value: float,
    *,
    formula: str | None = None,
    details: tuple[ScoreTermDetail, ...] = (),
) -> ScoreTerm:
    return ScoreTerm(
        name=name,
        value=float(value),
        formula=formula,
        details=details,
    )


def _weighted_term(
    name: str,
    *,
    raw_value: float,
    raw_label: str,
    weight: float,
    weight_label: str,
    details: tuple[ScoreTermDetail, ...] = (),
) -> ScoreTerm:
    return ScoreTerm(
        name=name,
        value=float(weight) * float(raw_value),
        raw_value=float(raw_value),
        raw_label=raw_label,
        weight=float(weight),
        weight_label=weight_label,
        details=details,
    )


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
        return _use_leader_action_score(
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
    return _play_card_action_score(
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
            _constant_term(
                "leave_penalty",
                profile.action_bonus.leave_penalty,
                formula="leave_penalty",
                details=(_detail("leave_penalty", profile.action_bonus.leave_penalty),),
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
                _constant_term(
                    "pass_exact_finish_bonus",
                    profile.weights.exact_finish_bonus,
                    formula="exact_finish_bonus",
                    details=(_detail("exact_finish_bonus", profile.weights.exact_finish_bonus),),
                ),
                _weighted_term(
                    "pass_resource_preservation",
                    raw_value=assessment.viewer.hand_value,
                    raw_label="viewer_hand_value",
                    weight=profile.weights.remaining_hand_value,
                    weight_label="remaining_hand_value",
                    details=(_detail("viewer_hand_count", assessment.viewer.hand_count),),
                ),
            ),
        )
    required_lead = _required_pass_lead(
        assessment,
        context=context,
        profile=profile,
    )
    pass_projection = current_board.score_gap - required_lead
    terms = [
        _constant_term(
            "pass_tempo_penalty",
            -profile.weights.immediate_points,
            formula="-immediate_points",
            details=(_detail("immediate_points", profile.weights.immediate_points),),
        ),
        _weighted_term(
            "pass_projection",
            raw_value=pass_projection,
            raw_label="pass_projection_raw",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                _detail("current_score_gap", current_board.score_gap),
                _detail("required_pass_lead", required_lead),
            ),
        ),
    ]
    if _can_safely_preserve_resources_on_pass(
        context=context,
        pass_projection=pass_projection,
    ):
        terms.append(
            _weighted_term(
                "pass_resource_preservation",
                raw_value=assessment.viewer.hand_value,
                raw_label="viewer_hand_value",
                weight=profile.weights.remaining_hand_value,
                weight_label="remaining_hand_value",
                details=(_detail("viewer_hand_count", assessment.viewer.hand_count),),
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
    components: tuple[tuple[str, float], ...] = ()
    with suppress(ValueError):
        components = explain_pending_choice_score_components(
            action,
            observation=observation,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if not components:
        return _unsupported_action_score(action, profile=profile)
    return ActionScoreBreakdown(
        action=action,
        terms=tuple(
            _constant_term(
                name,
                float(value),
                formula=name,
                details=(_detail(name, float(value)),),
            )
            for name, value in components
        ),
    )


def _use_leader_action_score(
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


def _unsupported_action_score(
    action: GameAction,
    *,
    profile: HeuristicProfile,
) -> ActionScoreBreakdown:
    penalty = profile.action_bonus.unsupported_action_penalty
    return ActionScoreBreakdown(
        action=action,
        terms=(
            _constant_term(
                "unsupported_action_penalty",
                penalty,
                formula="unsupported_action_penalty",
                details=(_detail("unsupported_action_penalty", penalty),),
            ),
        ),
    )


def _play_card_action_score(
    action: PlayCardAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None,
) -> ActionScoreBreakdown:
    definition = viewer_hand_definition(
        action.card_instance_id,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    if definition is None:
        return ActionScoreBreakdown(action=action, terms=())
    action_bonus = profile.action_bonus
    projection = project_play_action(
        action,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    terms = list(
        _generic_play_card_terms(
            definition,
            projection=projection,
            assessment=assessment,
            context=context,
            profile=profile,
        )
    )
    if definition.card_type == CardType.SPECIAL:
        ability_kind = special_ability_kind(definition)
        if ability_kind == AbilityKind.SCORCH:
            terms.extend(
                _scorch_score_terms(
                    action,
                    assessment=assessment,
                    context=context,
                    profile=profile,
                    scorch_impact=ScorchImpact(
                        viewer_strength_lost=projection.viewer_scorch_damage,
                        opponent_strength_lost=projection.opponent_scorch_damage,
                    ),
                )
            )
        elif ability_kind == AbilityKind.COMMANDERS_HORN:
            terms.append(
                _constant_term(
                    "horn_commitment_value",
                    _adaptive_horn_commitment_value(
                        action=action,
                        projection=projection,
                        assessment=assessment,
                        context=context,
                        profile=profile,
                    ),
                    formula="horn_commitment_policy",
                    details=(
                        _detail("horn_policy", "adaptive_horn_scoring"),
                        _detail("pressure", context.pressure.value),
                        _detail("tempo", context.tempo.value),
                    ),
                )
            )
        elif is_weather_ability(ability_kind):
            terms.append(
                _constant_term(
                    "weather_action_value",
                    _weather_action_value(
                        ability_kind,
                        assessment=assessment,
                        profile=profile,
                    ),
                    formula="weather_action_value",
                    details=(_detail("weather_ability", ability_kind.value),),
                )
            )
        elif ability_kind == AbilityKind.DECOY:
            terms.extend(
                _decoy_score_terms(
                    action,
                    observation=observation,
                    assessment=assessment,
                    profile=profile,
                    card_registry=card_registry,
                )
            )
    elif AbilityKind.SPY in definition.ability_kinds:
        terms.append(
            _constant_term(
                "spy_bonus",
                action_bonus.spy_bonus,
                formula="spy_bonus",
                details=(_detail("spy_bonus", action_bonus.spy_bonus),),
            )
        )
    elif AbilityKind.MEDIC in definition.ability_kinds:
        terms.append(
            _constant_term(
                "medic_bonus",
                action_bonus.medic_bonus,
                formula="medic_bonus",
                details=(_detail("medic_bonus", action_bonus.medic_bonus),),
            )
        )
    elif definition.card_type == CardType.UNIT:
        terms.append(
            _constant_term(
                "hero_commitment_value",
                _adaptive_unit_commitment_value(
                    definition,
                    context=context,
                    profile=profile,
                ),
                formula="unit_commitment_policy",
                details=(
                    _detail("unit_commitment_policy", "adaptive_unit_commitment"),
                    _detail("pressure", context.pressure.value),
                    _detail("tempo", context.tempo.value),
                ),
            )
        )
    deterministic_tactical_rebate = _deterministic_tactical_rebate(
        definition,
        projection=projection,
        profile=profile,
    )
    if deterministic_tactical_rebate > 0:
        terms.append(
            _constant_term(
                "deterministic_tactical_rebate",
                deterministic_tactical_rebate,
                formula=(
                    "min(speculative_penalty_score, "
                    "realized_tactical_lift_raw * combined_speculative_sensitivity)"
                ),
                details=_deterministic_tactical_rebate_details(
                    definition,
                    projection=projection,
                    profile=profile,
                ),
            )
        )
    return ActionScoreBreakdown(action=action, terms=tuple(terms))


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


def _leader_action_terms(
    *,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    leader_projection: LeaderActionProjection | None,
) -> tuple[ScoreTerm, ...]:
    """Score leader usage from actual projected effect, not just urgency.

    The previous generic leader scoring rewarded spending leader whenever the
    round looked urgent, even if the concrete leader effect would do nothing.
    We keep the generic appetite terms for live leader activations, but dead
    leader lines now collapse to reserve-cost plus an explicit no-effect
    penalty so they do not outrank productive plays.
    """

    generic_terms = tuple(
        _constant_term(
            name,
            value,
            formula=name,
            details=(
                _detail("leader_policy", profile.leader_policy.name),
                _detail("score_gap", assessment.score_gap),
                _detail("pressure", context.pressure.value),
                _detail("tempo", context.tempo.value),
            ),
        )
        for name, value in leader_policy_components(
            policy_name=profile.leader_policy.name,
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
            _constant_term(
                "leader_no_effect_penalty",
                no_effect_penalty,
                formula=(
                    "-exact_finish_bonus"
                    if assessment.opponent_passed
                    else "0 (no-op wait move allowed before opponent passes)"
                ),
                details=(
                    _detail("exact_finish_bonus", profile.weights.exact_finish_bonus),
                    _detail("opponent_passed", "yes" if assessment.opponent_passed else "no"),
                    *_leader_projection_details(leader_projection),
                    _detail("leader_live_targets", leader_projection.live_targets),
                    _detail("opponent_row_total", leader_projection.opponent_row_total or 0),
                    _detail("minimum_row_total", leader_projection.minimum_row_total or 0),
                ),
            ),
            _constant_term(
                "leader_reserve_cost",
                reserve_cost,
                formula="leader_reserve_cost",
                details=(_detail("leader_policy", profile.leader_policy.name),),
            ),
        )
    evaluation_policy = DEFAULT_EVALUATION_POLICY
    live_commitment_cost = reserve_cost / max(
        profile.preserve_resources_bias * evaluation_policy.leader_live_commitment_bias_multiplier,
        evaluation_policy.leader_live_commitment_min_divisor,
    )
    terms: list[ScoreTerm] = [
        _weighted_term(
            "leader_projected_swing",
            raw_value=leader_projection.projected_net_board_swing,
            raw_label="leader_projected_net_board_swing",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                *_leader_projection_details(leader_projection),
                _detail("leader_live_targets", leader_projection.live_targets),
                _detail("opponent_row_total", leader_projection.opponent_row_total or 0),
                _detail("minimum_row_total", leader_projection.minimum_row_total or 0),
            ),
        ),
    ]
    if leader_projection.projected_hand_value_delta:
        terms.append(
            _weighted_term(
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
            _weighted_term(
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
        _constant_term(
            "leader_commitment_cost",
            live_commitment_cost,
            formula="leader_reserve_cost / max(preserve_resources_bias * 2, 3)",
            details=(
                _detail("leader_policy", profile.leader_policy.name),
                _detail("leader_reserve_cost", reserve_cost),
                _detail("preserve_resources_bias", profile.preserve_resources_bias),
            ),
        )
    )
    return tuple(terms)


def _leader_projection_details(
    leader_projection: LeaderActionProjection,
) -> tuple[ScoreTermDetail, ...]:
    details = [_detail("leader_ability_kind", leader_projection.ability_kind.value)]
    if leader_projection.projected_hand_value_delta:
        details.append(
            _detail(
                "leader_projected_hand_value_delta",
                leader_projection.projected_hand_value_delta,
            )
        )
    if leader_projection.viewer_hand_count_delta:
        details.append(
            _detail("leader_viewer_hand_count_delta", leader_projection.viewer_hand_count_delta)
        )
    if leader_projection.affected_row is not None:
        details.append(_detail("affected_row", leader_projection.affected_row.value))
    if leader_projection.weather_rows_changed:
        details.append(
            _detail(
                "weather_rows_changed",
                ", ".join(row.value for row in leader_projection.weather_rows_changed),
            )
        )
    if leader_projection.moved_units:
        details.append(_detail("moved_units", leader_projection.moved_units))
    return tuple(details)


def _generic_play_card_terms(
    definition: CardDefinition,
    *,
    projection: PlayActionProjection,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> tuple[ScoreTerm, ...]:
    overcommit_breakdown = _projected_overcommitment_penalty(
        definition,
        assessment=assessment,
        current_score_gap=projection.current_score_gap,
        projected_score_gap_after=projection.projected_score_gap_after,
        context=context,
        profile=profile,
    )
    safe_pass_lead_established = _establishes_safe_pass_lead(
        current_score_gap=projection.current_score_gap,
        projected_score_gap_after=projection.projected_score_gap_after,
        context=context,
        profile=profile,
        assessment=assessment,
    )
    terms = [
        _weighted_term(
            "projected_net_board_swing",
            raw_value=projection.projected_net_board_swing,
            raw_label="projected_net_board_swing_raw",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                _detail("current_score_gap", projection.current_score_gap),
                _detail("viewer_score_after", projection.viewer_score_after),
                _detail("opponent_score_after", projection.opponent_score_after),
                _detail("projected_score_gap_after", projection.projected_score_gap_after),
            ),
        ),
        _weighted_term(
            "card_advantage",
            raw_value=projection.viewer_hand_count_after - projection.opponent_hand_count_after,
            raw_label="post_action_card_advantage",
            weight=profile.weights.card_advantage,
            weight_label="card_advantage_weight",
            details=(
                _detail("viewer_hand_count_after", projection.viewer_hand_count_after),
                _detail("opponent_hand_count_after", projection.opponent_hand_count_after),
            ),
        ),
        _weighted_term(
            "post_action_hand_value",
            raw_value=projection.post_action_hand_value,
            raw_label="post_action_hand_value_raw",
            weight=profile.weights.remaining_hand_value,
            weight_label="remaining_hand_value",
        ),
        _weighted_term(
            "projected_synergy_value",
            raw_value=projection.projected_synergy_value,
            raw_label="projected_synergy_value_raw",
            weight=profile.weights.synergy_retention,
            weight_label="synergy_retention",
        ),
        _weighted_term(
            "projected_avenger_value",
            raw_value=projection.projected_avenger_value,
            raw_label="projected_avenger_value_raw",
            weight=profile.weights.synergy_retention,
            weight_label="synergy_retention",
        ),
        _weighted_term(
            "horn_future_option_delta",
            raw_value=projection.horn_future_option_delta,
            raw_label="horn_future_option_delta_raw",
            weight=profile.weights.horn_potential,
            weight_label="horn_potential",
            details=(
                _detail("horn_option_value_before", projection.horn_option_value_before),
                _detail("horn_option_value_after", projection.horn_option_value_after),
            ),
        ),
        _weighted_term(
            "projected_weather_loss",
            raw_value=projection.projected_weather_loss,
            raw_label="projected_weather_loss_raw",
            weight=profile.weights.weather_exposure,
            weight_label="weather_exposure",
        ),
        _weighted_term(
            "projected_scorch_loss",
            raw_value=projection.projected_scorch_loss,
            raw_label="projected_scorch_loss_raw",
            weight=profile.weights.scorch_exposure,
            weight_label="scorch_exposure",
            details=(
                _detail("viewer_scorch_damage", projection.viewer_scorch_damage),
                _detail("opponent_scorch_damage", projection.opponent_scorch_damage),
                _detail("net_scorch_swing", projection.net_scorch_swing),
            ),
        ),
        _weighted_term(
            "dead_card_penalty",
            raw_value=projection.projected_dead_card_penalty,
            raw_label="projected_dead_card_penalty_raw",
            weight=profile.weights.dead_card_penalty,
            weight_label="dead_card_penalty_weight",
        ),
        _weighted_term(
            "overcommit_penalty",
            raw_value=overcommit_breakdown.value,
            raw_label="overcommit_penalty_raw",
            weight=profile.weights.overcommit_penalty,
            weight_label="overcommit_penalty_weight",
            details=(
                _detail("current_score_gap", overcommit_breakdown.current_score_gap),
                _detail(
                    "projected_score_gap_after",
                    overcommit_breakdown.projected_score_gap_after,
                ),
                _detail(
                    "required_score_gap_after",
                    overcommit_breakdown.required_score_gap_after,
                ),
                _detail(
                    "true_overcommit_gap_after",
                    overcommit_breakdown.true_overcommit_gap_after,
                ),
                _detail(
                    "opponent_counter_capacity",
                    overcommit_breakdown.opponent_counter_capacity,
                ),
                _detail("trickery_allowance", overcommit_breakdown.trickery_allowance),
                _detail(
                    "overcommit_window_active",
                    "yes" if overcommit_breakdown.overcommit_window_active else "no",
                ),
                _detail("legal_play_count", overcommit_breakdown.legal_play_count),
                _detail("excess_points", overcommit_breakdown.excess_points),
                _detail("premium_cost", overcommit_breakdown.premium_cost),
            ),
        ),
        _constant_term(
            "safe_pass_lead_established",
            profile.weights.exact_finish_bonus if safe_pass_lead_established else 0.0,
            formula="exact_finish_bonus if safe_pass_lead_established else 0",
            details=(
                _detail(
                    "safe_pass_lead_established",
                    "yes" if safe_pass_lead_established else "no",
                ),
                _detail("current_score_gap", projection.current_score_gap),
                _detail("projected_score_gap_after", projection.projected_score_gap_after),
                _detail(
                    "required_pass_lead",
                    _required_pass_lead(
                        assessment,
                        context=context,
                        profile=profile,
                    ),
                ),
            ),
        ),
    ]
    if (
        AbilityKind.UNIT_SCORCH_ROW in definition.ability_kinds
        and projection.projected_net_board_swing <= definition.base_strength
    ):
        terms.append(
            _constant_term(
                "unit_row_scorch_reserve_penalty",
                -max(4, definition.base_strength // 2),
                formula="reserve body-only unit_row_scorch commit penalty",
                details=(
                    _detail("card_definition_id", definition.definition_id),
                    _detail("projected_net_board_swing", projection.projected_net_board_swing),
                    _detail("base_strength", definition.base_strength),
                ),
            )
        )
    return tuple(terms)


def _adaptive_horn_commitment_value(
    *,
    action: PlayCardAction,
    projection: PlayActionProjection,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> float:
    if action.target_row is None:
        return profile.action_bonus.invalid_target_penalty
    if projection.projected_net_board_swing <= 0:
        return profile.action_bonus.horn_no_valid_targets_penalty
    row_summary = _viewer_row_summary(assessment, action.target_row)
    base_value = _horn_base_value(row_summary, profile=profile)
    if row_summary.non_hero_unit_count == 0:
        return base_value
    if context.prioritize_immediate_points:
        return base_value * max(1.0, profile.minimum_commitment_bias)
    if context.preserve_resources:
        return _preserved_horn_commitment_value(
            base_value,
            row_summary=row_summary,
            assessment=assessment,
            profile=profile,
        )
    return base_value


def _preserved_horn_commitment_value(
    base_value: float,
    *,
    row_summary: RowSummary,
    assessment: DecisionAssessment,
    profile: HeuristicProfile,
) -> float:
    if row_summary.non_hero_unit_count <= 1 and assessment.viewer.unit_hand_count > 0:
        base_value -= profile.action_bonus.horn_setup_penalty
    return base_value / max(profile.preserve_resources_bias, 1.0)


def _deterministic_tactical_rebate(
    definition: CardDefinition,
    *,
    projection: PlayActionProjection,
    profile: HeuristicProfile,
) -> float:
    """Rebate speculative punishment-risk when tactical value is already real.

    The generic weather/scorch exposure terms are intentionally speculative:
    they ask how punishable the *resulting* board might be later. That is
    useful, but it can misfire when an action has already realized a visible,
    deterministic tactical gain right now.

    This helper therefore adds back part of the speculative penalty, but only
    up to the score value of deterministic tactical lift that is already on the
    board. The lift is defined as projected swing beyond the card's plain body:

    - for tactical specials, the whole projected swing is deterministic lift
    - for tactical units, only swing above `base_strength` counts

    This keeps the evaluator honest about the difference between:
    - value the action has already concretely realized
    - hypothetical future punishment that may or may not happen later

    The cap is expressed in the same risk units as the rebated penalty:
    realized tactical lift multiplied by the combined configured sensitivity of
    the speculative weather and scorch channels. This keeps the rebate tied to
    the exact future-risk channels it is discounting.

    The helper is intentionally narrow and only applies to tactical families
    whose immediate public effect is already modeled precisely.
    """

    realized_lift = _realized_tactical_lift_raw(
        definition,
        projection=projection,
    )
    if realized_lift <= 0:
        return 0.0
    speculative_penalty = _speculative_penalty_score(
        projection=projection,
        profile=profile,
    )
    if speculative_penalty <= 0:
        return 0.0
    realized_lift_score = realized_lift * _combined_speculative_sensitivity(profile)
    return min(speculative_penalty, realized_lift_score)


def _deterministic_tactical_rebate_details(
    definition: CardDefinition,
    *,
    projection: PlayActionProjection,
    profile: HeuristicProfile,
) -> tuple[ScoreTermDetail, ...]:
    realized_lift = _realized_tactical_lift_raw(
        definition,
        projection=projection,
    )
    realized_lift_score = realized_lift * _combined_speculative_sensitivity(profile)
    speculative_penalty = _speculative_penalty_score(
        projection=projection,
        profile=profile,
    )
    return (
        _detail("tactical_family", _tactical_rebate_family(definition)),
        _detail("projected_net_board_swing", projection.projected_net_board_swing),
        _detail("realized_tactical_lift_raw", realized_lift),
        _detail("realized_tactical_lift_score_cap", realized_lift_score),
        _detail("projected_weather_loss", projection.projected_weather_loss),
        _detail("projected_scorch_loss", projection.projected_scorch_loss),
        _detail("speculative_penalty_score", speculative_penalty),
    )


def _realized_tactical_lift_raw(
    definition: CardDefinition,
    *,
    projection: PlayActionProjection,
) -> float:
    if projection.projected_net_board_swing <= 0:
        return 0.0
    if definition.card_type == CardType.SPECIAL and _is_tactical_special(definition):
        return float(projection.projected_net_board_swing)
    if definition.card_type == CardType.UNIT and _is_tactical_unit(definition):
        return float(max(0, projection.projected_net_board_swing - definition.base_strength))
    return 0.0


def _speculative_penalty_score(
    *,
    projection: PlayActionProjection,
    profile: HeuristicProfile,
) -> float:
    weather_penalty = (
        max(0.0, -profile.weights.weather_exposure) * projection.projected_weather_loss
    )
    scorch_penalty = max(0.0, -profile.weights.scorch_exposure) * projection.projected_scorch_loss
    return weather_penalty + scorch_penalty


def _combined_speculative_sensitivity(profile: HeuristicProfile) -> float:
    return max(0.0, -profile.weights.weather_exposure) + max(
        0.0,
        -profile.weights.scorch_exposure,
    )


def _is_tactical_special(definition: CardDefinition) -> bool:
    return special_ability_kind(definition) in {
        AbilityKind.MARDROEME,
        AbilityKind.COMMANDERS_HORN,
        AbilityKind.SCORCH,
        AbilityKind.CLEAR_WEATHER,
        AbilityKind.BITING_FROST,
        AbilityKind.IMPENETRABLE_FOG,
        AbilityKind.TORRENTIAL_RAIN,
        AbilityKind.SKELLIGE_STORM,
    }


def _is_tactical_unit(definition: CardDefinition) -> bool:
    return any(
        ability_kind in definition.ability_kinds
        for ability_kind in {
            AbilityKind.MUSTER,
            AbilityKind.MEDIC,
            AbilityKind.SPY,
            AbilityKind.UNIT_SCORCH_ROW,
            AbilityKind.UNIT_COMMANDERS_HORN,
            AbilityKind.MORALE_BOOST,
            AbilityKind.BERSERKER,
        }
    )


def _tactical_rebate_family(definition: CardDefinition) -> str:
    if definition.card_type == CardType.SPECIAL:
        return special_ability_kind(definition).value
    for ability_kind in (
        AbilityKind.MUSTER,
        AbilityKind.MEDIC,
        AbilityKind.SPY,
        AbilityKind.UNIT_SCORCH_ROW,
        AbilityKind.UNIT_COMMANDERS_HORN,
        AbilityKind.MORALE_BOOST,
        AbilityKind.BERSERKER,
    ):
        if ability_kind in definition.ability_kinds:
            return ability_kind.value
    return "none"


def _adaptive_unit_commitment_value(
    definition: CardDefinition,
    *,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> float:
    if not definition.is_hero:
        return 0.0
    if context.prioritize_immediate_points:
        return (
            profile.weights.immediate_points
            * definition.base_strength
            * max(1.0, profile.minimum_commitment_bias)
        )
    if context.preserve_resources:
        return (
            -profile.weights.remaining_hand_value
            * definition.base_strength
            * max(profile.preserve_resources_bias, 1.0)
        )
    return 0.0


def _viewer_row_summary(
    assessment: DecisionAssessment,
    row: Row,
) -> RowSummary:
    for summary in assessment.viewer.row_summaries():
        if summary.row == row:
            return summary
    raise ValueError(f"Unknown row: {row!r}")


def _horn_base_value(
    row_summary: RowSummary,
    *,
    profile: HeuristicProfile,
) -> float:
    if row_summary.non_hero_unit_count == 0:
        return profile.action_bonus.horn_no_valid_targets_penalty
    return (
        profile.action_bonus.horn_target_count_bonus * row_summary.non_hero_unit_count
        + profile.action_bonus.horn_valid_strength_delta_bonus
        * row_summary.non_hero_unit_base_strength
    )


def _required_pass_lead(
    assessment: DecisionAssessment,
    *,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> int:
    tempo_per_card = _estimated_opponent_tempo_per_card(
        context=context,
        profile=profile,
    )
    return max(
        profile.pass_lead_margin,
        assessment.opponent.hand_count * tempo_per_card,
    )


def _can_safely_preserve_resources_on_pass(
    *,
    context: DecisionContext,
    pass_projection: int,
) -> bool:
    return context.tempo == TempoState.AHEAD and context.preserve_resources and pass_projection >= 0


def _establishes_safe_pass_lead(
    *,
    current_score_gap: int,
    projected_score_gap_after: int,
    context: DecisionContext,
    profile: HeuristicProfile,
    assessment: DecisionAssessment,
) -> bool:
    if assessment.opponent_passed or not context.preserve_resources:
        return False
    required_lead = _required_pass_lead(
        assessment,
        context=context,
        profile=profile,
    )
    return current_score_gap < required_lead <= projected_score_gap_after


def _projected_overcommitment_penalty(
    definition: CardDefinition,
    *,
    assessment: DecisionAssessment,
    current_score_gap: int,
    projected_score_gap_after: int,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> OvercommitmentPenaltyBreakdown:
    """Measure true resource waste after accounting for opponent pressure.

    This intentionally does not treat every large projected lead as
    overcommitment. A move only overcommits when it spends materially more than
    is needed to secure the round against the opponent's remaining pressure.

    The rule is stricter than the old excess-gap check:
    - if the opponent has already passed, the true finish target is just `+1`
    - if the opponent is still live, we first estimate their counter-pressure
      from remaining cards, then add a small "trickery allowance" when their
      current board is still low enough that they may simply be sandbagging
    - pure opening/probe positions do not use open-round overcommit yet,
      because the board is still too undercommitted for a large lead to be a
      trustworthy waste signal
    - no overcommit penalty is applied from even or behind positions, because
      the bot is still genuinely contesting rather than safely protecting an
      already-secured lead, unless the chosen action itself creates a fully
      safe lead while a real alternative play also existed
    """

    premium_cost = 0.0
    evaluation_policy = DEFAULT_EVALUATION_POLICY
    if definition.is_hero:
        premium_cost += max(
            evaluation_policy.hero_overcommit_min_cost,
            definition.base_strength / evaluation_policy.hero_overcommit_strength_divisor,
        )
    if AbilityKind.MEDIC in definition.ability_kinds:
        premium_cost += evaluation_policy.medic_overcommit_cost
    if AbilityKind.SPY in definition.ability_kinds:
        premium_cost += evaluation_policy.spy_overcommit_cost
    if definition.card_type == CardType.SPECIAL:
        match special_ability_kind(definition):
            case AbilityKind.DECOY | AbilityKind.SCORCH | AbilityKind.COMMANDERS_HORN:
                premium_cost += evaluation_policy.premium_special_overcommit_cost
            case _:
                pass

    required_score_gap_after = (
        1
        if assessment.opponent_passed
        else _required_pass_lead(
            assessment,
            context=context,
            profile=profile,
        )
    )
    opponent_counter_capacity = (
        0
        if assessment.opponent_passed
        else max(
            0,
            required_score_gap_after - profile.pass_lead_margin,
        )
    )
    trickery_allowance = 0
    if (
        not assessment.opponent_passed
        and assessment.opponent.hand_count > 0
        and assessment.opponent.board_strength <= assessment.viewer.board_strength
    ):
        trickery_allowance = max(
            1,
            _estimated_opponent_tempo_per_card(
                context=context,
                profile=profile,
            ),
        )
    true_overcommit_gap_after = required_score_gap_after + trickery_allowance
    overcommit_window_active = assessment.opponent_passed or (
        context.preserve_resources
        and context.mode != TacticalMode.PROBE
        and (
            current_score_gap > 0
            or (
                assessment.legal_play_count > 1
                and projected_score_gap_after >= required_score_gap_after
            )
        )
    )
    excess_points = (
        max(0, projected_score_gap_after - true_overcommit_gap_after)
        if overcommit_window_active
        else 0
    )
    if context.preserve_resources:
        premium_cost *= max(profile.preserve_resources_bias, 1.0)
    excess_value = float(excess_points)
    if not assessment.opponent_passed:
        # Open-round excess is less certain because the opponent can still hide
        # real strength behind weak probe plays. Penalize only part of the
        # apparent excess until the round is actually closed.
        excess_value /= evaluation_policy.open_round_excess_divisor
    ## TODO: Consider whether to use max/min/clamp
    premium_cost_applies = excess_points > 0 and (
        assessment.opponent_passed
        or current_score_gap >= required_score_gap_after
        or assessment.legal_play_count > 1
    )
    value = (
        0.0
        if excess_points <= 0
        else excess_value + (premium_cost if premium_cost_applies else 0.0)
    )
    return OvercommitmentPenaltyBreakdown(
        value=value,
        excess_points=excess_points,
        premium_cost=premium_cost,
        current_score_gap=current_score_gap,
        projected_score_gap_after=projected_score_gap_after,
        required_score_gap_after=required_score_gap_after,
        true_overcommit_gap_after=true_overcommit_gap_after,
        opponent_counter_capacity=opponent_counter_capacity,
        trickery_allowance=trickery_allowance,
        overcommit_window_active=overcommit_window_active,
        legal_play_count=assessment.legal_play_count,
    )


def _estimated_opponent_tempo_per_card(
    *,
    context: DecisionContext,
    profile: HeuristicProfile,
) -> int:
    if context.pressure == PressureMode.ELIMINATION:
        return profile.elimination_estimated_opponent_tempo_per_card
    return profile.estimated_opponent_tempo_per_card


def rank_actions(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> tuple[tuple[GameAction, float], ...]:
    ranked = sorted(
        (
            (
                breakdown.action,
                breakdown.total,
            )
            for breakdown in explain_ranked_actions(
                legal_actions,
                observation=observation,
                assessment=assessment,
                context=context,
                profile=profile,
                card_registry=card_registry,
                viewer_hand_definitions=viewer_hand_definitions,
            )
        ),
        key=lambda item: (-item[1], action_to_id(item[0])),
    )
    return tuple(ranked)


def _weather_action_value(
    ability_kind: AbilityKind,
    *,
    assessment: DecisionAssessment,
    profile: HeuristicProfile,
) -> float:
    swing = 0
    for row in weather_rows_for(ability_kind):
        if row in assessment.active_weather_rows:
            continue
        swing += _weather_row_delta(_player_row_summary(assessment.opponent, row))
        swing -= _weather_row_delta(_player_row_summary(assessment.viewer, row))
    if swing == 0:
        return profile.action_bonus.weather_no_swing_penalty
    return 0.0


def _weather_row_delta(summary: RowSummary) -> int:
    return max(0, summary.non_hero_unit_base_strength - summary.non_hero_unit_count)


def _player_row_summary(
    player_assessment: PlayerAssessment,
    row: Row,
) -> RowSummary:
    for summary in player_assessment.row_summaries():
        if summary.row == row:
            return summary
    raise ValueError(f"Unknown row: {row!r}")


def _scorch_score_terms(
    action: PlayCardAction,
    *,
    assessment: DecisionAssessment,
    context: DecisionContext,
    profile: HeuristicProfile,
    scorch_impact: ScorchImpact,
) -> tuple[ScoreTerm, ...]:
    if not scorch_impact.has_live_targets:
        return (
            _constant_term(
                "scorch_live_targets",
                profile.action_bonus.scorch_no_live_targets_penalty,
                formula="scorch_no_live_targets_penalty",
                details=(
                    _detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                    _detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                ),
            ),
        )
    if scorch_impact.self_damaging:
        return (
            _constant_term(
                "scorch_live_targets",
                profile.action_bonus.scorch_self_damage_penalty,
                formula="scorch_self_damage_penalty",
                details=(
                    _detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                    _detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                    _detail("net_scorch_swing", scorch_impact.net_swing),
                ),
            ),
        )
    return (
        _constant_term(
            "scorch_policy",
            profile.scorch_policy.evaluate(
                action=action,
                assessment=assessment,
                context=context,
                scorch_impact=scorch_impact,
                profile=profile,
            ),
            formula="scorch_policy",
            details=(
                _detail("scorch_policy", profile.scorch_policy.name),
                _detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                _detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                _detail("net_scorch_swing", scorch_impact.net_swing),
            ),
        ),
    )


def _decoy_score_terms(
    action: PlayCardAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
) -> tuple[ScoreTerm, ...]:
    target_card = (
        _find_visible_battlefield_card(observation, action.target_card_instance_id)
        if action.target_card_instance_id is not None
        else _best_decoy_target(
            observation,
            profile=profile,
            card_registry=card_registry,
        )
    )
    if target_card is None:
        return (
            _constant_term(
                "decoy_target",
                profile.action_bonus.invalid_target_penalty,
                formula="invalid_target_penalty",
                details=(
                    _detail("invalid_target_penalty", profile.action_bonus.invalid_target_penalty),
                ),
            ),
        )
    target_definition = card_registry.get(target_card.definition_id)
    terms = [
        _constant_term(
            "decoy_bonus",
            profile.action_bonus.decoy_bonus,
            formula="decoy_bonus",
            details=(_detail("decoy_bonus", profile.action_bonus.decoy_bonus),),
        )
    ]
    terms.append(
        _weighted_term(
            "decoy_target_value",
            raw_value=target_definition.base_strength,
            raw_label="decoy_target_base_strength",
            weight=profile.action_bonus.decoy_target_strength_bonus,
            weight_label="decoy_target_strength_bonus",
            details=(_detail("decoy_target_name", target_definition.name),),
        )
    )
    if AbilityKind.SPY in target_definition.ability_kinds:
        terms.append(
            _constant_term(
                "decoy_spy_reclaim",
                profile.action_bonus.decoy_spy_reclaim_bonus,
                formula="decoy_spy_reclaim_bonus",
                details=(
                    _detail(
                        "decoy_spy_reclaim_bonus",
                        profile.action_bonus.decoy_spy_reclaim_bonus,
                    ),
                ),
            )
        )
    if _is_scorch_risk_target(
        observation,
        target_card.instance_id,
        card_registry=card_registry,
    ):
        terms.append(
            _constant_term(
                "decoy_scorch_save",
                profile.action_bonus.decoy_scorch_save_bonus,
                formula="decoy_scorch_save_bonus",
                details=(
                    _detail(
                        "decoy_scorch_save_bonus",
                        profile.action_bonus.decoy_scorch_save_bonus,
                    ),
                ),
            )
        )
    if target_card.owner != assessment.viewer_player_id:
        terms.append(
            _constant_term(
                "decoy_opponent_resource_swing",
                profile.weights.card_advantage,
                formula="card_advantage_weight",
                details=(_detail("card_advantage_weight", profile.weights.card_advantage),),
            )
        )
    return tuple(terms)


def _is_scorch_risk_target(
    observation: PlayerObservation,
    target_card_id: CardInstanceId,
    *,
    card_registry: CardRegistry,
) -> bool:
    board = current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    target_card = _find_visible_battlefield_card(observation, target_card_id)
    if target_card is None or target_card.battlefield_side != observation.viewer_player_id:
        return False
    all_strengths = {
        strength
        for rows in (board.viewer_rows, board.opponent_rows)
        for row in rows
        for strength in row.scorchable_unit_strengths
    }
    if not all_strengths:
        return False
    highest = max(all_strengths)
    if highest < DEFAULT_FEATURE_POLICY.scorch_threshold:
        return False
    return (
        _visible_battlefield_card_strength(
            observation,
            target_card_id,
            card_registry=card_registry,
        )
        == highest
    )


def _visible_battlefield_card_strength(
    observation: PlayerObservation,
    target_card_id: CardInstanceId,
    *,
    card_registry: CardRegistry,
) -> int | None:
    board = current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    target_card = _find_visible_battlefield_card(observation, target_card_id)
    if target_card is None or target_card.row is None or target_card.battlefield_side is None:
        return None
    rows = (
        board.viewer_rows
        if target_card.battlefield_side == observation.viewer_player_id
        else board.opponent_rows
    )
    row_projection = next(
        row_projection for row_projection in rows if row_projection.row == target_card.row
    )
    definition = card_registry.get(target_card.definition_id)
    if definition.card_type != CardType.UNIT or definition.is_hero:
        return None
    visible_row_cards = [
        card
        for card in visible_battlefield_cards(observation)
        if (card.battlefield_side == target_card.battlefield_side and card.row == target_card.row)
    ]
    unit_positions = [
        index
        for index, card in enumerate(visible_row_cards)
        if (
            card_registry.get(card.definition_id).card_type == CardType.UNIT
            and not card_registry.get(card.definition_id).is_hero
        )
    ]
    position = next(
        (
            position
            for position, card in enumerate(visible_row_cards)
            if card.instance_id == target_card_id
        ),
        None,
    )
    if position is None or position not in unit_positions:
        return None
    scorchable_index = unit_positions.index(position)
    return row_projection.scorchable_unit_strengths[scorchable_index]


def _find_visible_battlefield_card(
    observation: PlayerObservation,
    card_instance_id: CardInstanceId,
) -> ObservedCard | None:
    for card in visible_battlefield_cards(observation):
        if card.instance_id == card_instance_id:
            return card
    return None


def _best_decoy_target(
    observation: PlayerObservation,
    *,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
) -> ObservedCard | None:
    viewer_side_cards = tuple(
        card
        for card in visible_battlefield_cards(observation)
        if card.battlefield_side == observation.viewer_player_id
    )
    if not viewer_side_cards:
        return None
    return max(
        viewer_side_cards,
        key=lambda card: _decoy_target_priority(
            observation,
            card,
            profile=profile,
            card_registry=card_registry,
        ),
    )


def _decoy_target_priority(
    observation: PlayerObservation,
    target_card: ObservedCard,
    *,
    profile: HeuristicProfile,
    card_registry: CardRegistry,
) -> float:
    definition = card_registry.get(target_card.definition_id)
    score = float(definition.base_strength)
    if AbilityKind.SPY in definition.ability_kinds:
        score += profile.action_bonus.decoy_spy_reclaim_bonus
    if _is_scorch_risk_target(
        observation,
        target_card.instance_id,
        card_registry=card_registry,
    ):
        score += profile.action_bonus.decoy_scorch_save_bonus
    if target_card.owner != observation.viewer_player_id:
        score += profile.weights.card_advantage
    return score
