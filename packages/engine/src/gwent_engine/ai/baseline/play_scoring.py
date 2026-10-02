"""Card-play scoring: generic value terms, commitment, tactical rebates, and overcommitment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.baseline.assessment import DecisionAssessment, RowSummary
from gwent_engine.ai.baseline.context import DecisionContext, PressureMode, TacticalMode
from gwent_engine.ai.baseline.pass_logic import required_pass_lead
from gwent_engine.ai.baseline.profiles import HeuristicProfile
from gwent_engine.ai.baseline.projection import (
    PlayActionProjection,
    ScorchImpact,
    project_play_action,
)
from gwent_engine.ai.baseline.score_terms import (
    ActionScoreBreakdown,
    ScoreTerm,
    ScoreTermDetail,
    constant_term,
    term_detail,
    weighted_term,
)
from gwent_engine.ai.baseline.special_scoring import (
    decoy_score_terms,
    scorch_score_terms,
    weather_action_value,
)
from gwent_engine.ai.observation_queries import viewer_hand_definition
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_EVALUATION_POLICY
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import (
    PlayCardAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.weather import is_weather_ability


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


def play_card_action_score(
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
                scorch_score_terms(
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
                constant_term(
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
                        term_detail("horn_policy", "adaptive_horn_scoring"),
                        term_detail("pressure", context.pressure.value),
                        term_detail("tempo", context.tempo.value),
                    ),
                )
            )
        elif is_weather_ability(ability_kind):
            terms.append(
                constant_term(
                    "weather_action_value",
                    weather_action_value(
                        ability_kind,
                        assessment=assessment,
                        profile=profile,
                    ),
                    formula="weather_action_value",
                    details=(term_detail("weather_ability", ability_kind.value),),
                )
            )
        elif ability_kind == AbilityKind.DECOY:
            terms.extend(
                decoy_score_terms(
                    action,
                    observation=observation,
                    assessment=assessment,
                    profile=profile,
                    card_registry=card_registry,
                )
            )
    elif AbilityKind.SPY in definition.ability_kinds:
        terms.append(
            constant_term(
                "spy_bonus",
                action_bonus.spy_bonus,
                formula="spy_bonus",
                details=(term_detail("spy_bonus", action_bonus.spy_bonus),),
            )
        )
    elif AbilityKind.MEDIC in definition.ability_kinds:
        terms.append(
            constant_term(
                "medic_bonus",
                action_bonus.medic_bonus,
                formula="medic_bonus",
                details=(term_detail("medic_bonus", action_bonus.medic_bonus),),
            )
        )
    elif definition.card_type == CardType.UNIT:
        terms.append(
            constant_term(
                "hero_commitment_value",
                _adaptive_unit_commitment_value(
                    definition,
                    context=context,
                    profile=profile,
                ),
                formula="unit_commitment_policy",
                details=(
                    term_detail("unit_commitment_policy", "adaptive_unit_commitment"),
                    term_detail("pressure", context.pressure.value),
                    term_detail("tempo", context.tempo.value),
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
            constant_term(
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
        weighted_term(
            "projected_net_board_swing",
            raw_value=projection.projected_net_board_swing,
            raw_label="projected_net_board_swing_raw",
            weight=profile.weights.immediate_points,
            weight_label="immediate_points",
            details=(
                term_detail("current_score_gap", projection.current_score_gap),
                term_detail("viewer_score_after", projection.viewer_score_after),
                term_detail("opponent_score_after", projection.opponent_score_after),
                term_detail("projected_score_gap_after", projection.projected_score_gap_after),
            ),
        ),
        weighted_term(
            "card_advantage",
            raw_value=projection.viewer_hand_count_after - projection.opponent_hand_count_after,
            raw_label="post_action_card_advantage",
            weight=profile.weights.card_advantage,
            weight_label="card_advantage_weight",
            details=(
                term_detail("viewer_hand_count_after", projection.viewer_hand_count_after),
                term_detail("opponent_hand_count_after", projection.opponent_hand_count_after),
            ),
        ),
        weighted_term(
            "post_action_hand_value",
            raw_value=projection.post_action_hand_value,
            raw_label="post_action_hand_value_raw",
            weight=profile.weights.remaining_hand_value,
            weight_label="remaining_hand_value",
        ),
        weighted_term(
            "projected_synergy_value",
            raw_value=projection.projected_synergy_value,
            raw_label="projected_synergy_value_raw",
            weight=profile.weights.synergy_retention,
            weight_label="synergy_retention",
        ),
        weighted_term(
            "projected_avenger_value",
            raw_value=projection.projected_avenger_value,
            raw_label="projected_avenger_value_raw",
            weight=profile.weights.synergy_retention,
            weight_label="synergy_retention",
        ),
        weighted_term(
            "horn_future_option_delta",
            raw_value=projection.horn_future_option_delta,
            raw_label="horn_future_option_delta_raw",
            weight=profile.weights.horn_potential,
            weight_label="horn_potential",
            details=(
                term_detail("horn_option_value_before", projection.horn_option_value_before),
                term_detail("horn_option_value_after", projection.horn_option_value_after),
            ),
        ),
        weighted_term(
            "projected_weather_loss",
            raw_value=projection.projected_weather_loss,
            raw_label="projected_weather_loss_raw",
            weight=profile.weights.weather_exposure,
            weight_label="weather_exposure",
        ),
        weighted_term(
            "projected_scorch_loss",
            raw_value=projection.projected_scorch_loss,
            raw_label="projected_scorch_loss_raw",
            weight=profile.weights.scorch_exposure,
            weight_label="scorch_exposure",
            details=(
                term_detail("viewer_scorch_damage", projection.viewer_scorch_damage),
                term_detail("opponent_scorch_damage", projection.opponent_scorch_damage),
                term_detail("net_scorch_swing", projection.net_scorch_swing),
            ),
        ),
        weighted_term(
            "dead_card_penalty",
            raw_value=projection.projected_dead_card_penalty,
            raw_label="projected_dead_card_penalty_raw",
            weight=profile.weights.dead_card_penalty,
            weight_label="dead_card_penalty_weight",
        ),
        weighted_term(
            "overcommit_penalty",
            raw_value=overcommit_breakdown.value,
            raw_label="overcommit_penalty_raw",
            weight=profile.weights.overcommit_penalty,
            weight_label="overcommit_penalty_weight",
            details=(
                term_detail("current_score_gap", overcommit_breakdown.current_score_gap),
                term_detail(
                    "projected_score_gap_after",
                    overcommit_breakdown.projected_score_gap_after,
                ),
                term_detail(
                    "required_score_gap_after",
                    overcommit_breakdown.required_score_gap_after,
                ),
                term_detail(
                    "true_overcommit_gap_after",
                    overcommit_breakdown.true_overcommit_gap_after,
                ),
                term_detail(
                    "opponent_counter_capacity",
                    overcommit_breakdown.opponent_counter_capacity,
                ),
                term_detail("trickery_allowance", overcommit_breakdown.trickery_allowance),
                term_detail(
                    "overcommit_window_active",
                    "yes" if overcommit_breakdown.overcommit_window_active else "no",
                ),
                term_detail("legal_play_count", overcommit_breakdown.legal_play_count),
                term_detail("excess_points", overcommit_breakdown.excess_points),
                term_detail("premium_cost", overcommit_breakdown.premium_cost),
            ),
        ),
        constant_term(
            "safe_pass_lead_established",
            profile.weights.exact_finish_bonus if safe_pass_lead_established else 0.0,
            formula="exact_finish_bonus if safe_pass_lead_established else 0",
            details=(
                term_detail(
                    "safe_pass_lead_established",
                    "yes" if safe_pass_lead_established else "no",
                ),
                term_detail("current_score_gap", projection.current_score_gap),
                term_detail("projected_score_gap_after", projection.projected_score_gap_after),
                term_detail(
                    "required_pass_lead",
                    required_pass_lead(
                        assessment,
                        context=context,
                        config=profile.pass_config,
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
            constant_term(
                "unit_row_scorch_reserve_penalty",
                -max(4, definition.base_strength // 2),
                formula="reserve body-only unit_row_scorch commit penalty",
                details=(
                    term_detail("card_definition_id", definition.definition_id),
                    term_detail("projected_net_board_swing", projection.projected_net_board_swing),
                    term_detail("base_strength", definition.base_strength),
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
    row_summary = assessment.viewer.row_summary(action.target_row)
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
        term_detail("tactical_family", _tactical_rebate_family(definition)),
        term_detail("projected_net_board_swing", projection.projected_net_board_swing),
        term_detail("realized_tactical_lift_raw", realized_lift),
        term_detail("realized_tactical_lift_score_cap", realized_lift_score),
        term_detail("projected_weather_loss", projection.projected_weather_loss),
        term_detail("projected_scorch_loss", projection.projected_scorch_loss),
        term_detail("speculative_penalty_score", speculative_penalty),
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
    ability_kind = special_ability_kind(definition)
    return is_weather_ability(ability_kind) or ability_kind in {
        AbilityKind.MARDROEME,
        AbilityKind.COMMANDERS_HORN,
        AbilityKind.SCORCH,
        AbilityKind.CLEAR_WEATHER,
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
    required_lead = required_pass_lead(
        assessment,
        context=context,
        config=profile.pass_config,
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

    The rule:
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
        else required_pass_lead(
            assessment,
            context=context,
            config=profile.pass_config,
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
            profile.pass_config.opponent_tempo_per_card(
                elimination=context.pressure == PressureMode.ELIMINATION
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
