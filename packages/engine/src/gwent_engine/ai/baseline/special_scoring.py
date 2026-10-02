"""Scoring terms for Scorch, Decoy, and weather special cards."""

from __future__ import annotations

from gwent_engine.ai.baseline.assessment import DecisionAssessment, PlayerAssessment, RowSummary
from gwent_engine.ai.baseline.context import DecisionContext
from gwent_engine.ai.baseline.features import weather_row_delta
from gwent_engine.ai.baseline.profiles import HeuristicProfile
from gwent_engine.ai.baseline.projection import (
    ScorchImpact,
    current_public_board_projection,
)
from gwent_engine.ai.baseline.projection.context import visible_battlefield_cards
from gwent_engine.ai.baseline.score_terms import (
    ScoreTerm,
    constant_term,
    term_detail,
    weighted_term,
)
from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY
from gwent_engine.cards import CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.actions import (
    PlayCardAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.rules.weather import weather_rows_for


def weather_action_value(
    ability_kind: AbilityKind,
    *,
    assessment: DecisionAssessment,
    profile: HeuristicProfile,
) -> float:
    swing = 0
    for row in weather_rows_for(ability_kind):
        if row in assessment.active_weather_rows:
            continue
        swing += weather_row_delta(_player_row_summary(assessment.opponent, row))
        swing -= weather_row_delta(_player_row_summary(assessment.viewer, row))
    if swing == 0:
        return profile.action_bonus.weather_no_swing_penalty
    return 0.0


def _player_row_summary(
    player_assessment: PlayerAssessment,
    row: Row,
) -> RowSummary:
    for summary in player_assessment.row_summaries():
        if summary.row == row:
            return summary
    raise ValueError(f"Unknown row: {row!r}")


def scorch_score_terms(
    *,
    context: DecisionContext,
    profile: HeuristicProfile,
    scorch_impact: ScorchImpact,
) -> tuple[ScoreTerm, ...]:
    if not scorch_impact.has_live_targets:
        return (
            constant_term(
                "scorch_live_targets",
                profile.action_bonus.scorch_no_live_targets_penalty,
                formula="scorch_no_live_targets_penalty",
                details=(
                    term_detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                    term_detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                ),
            ),
        )
    if scorch_impact.self_damaging:
        return (
            constant_term(
                "scorch_live_targets",
                profile.action_bonus.scorch_self_damage_penalty,
                formula="scorch_self_damage_penalty",
                details=(
                    term_detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                    term_detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                    term_detail("net_scorch_swing", scorch_impact.net_swing),
                ),
            ),
        )
    return (
        constant_term(
            "scorch_policy",
            profile.scorch_policy.evaluate(scorch_impact, context, profile),
            formula="scorch_policy",
            details=(
                term_detail("scorch_policy", profile.scorch_policy.name),
                term_detail("viewer_scorch_damage", scorch_impact.viewer_strength_lost),
                term_detail("opponent_scorch_damage", scorch_impact.opponent_strength_lost),
                term_detail("net_scorch_swing", scorch_impact.net_swing),
            ),
        ),
    )


def decoy_score_terms(
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
            constant_term(
                "decoy_target",
                profile.action_bonus.invalid_target_penalty,
                formula="invalid_target_penalty",
                details=(
                    term_detail(
                        "invalid_target_penalty", profile.action_bonus.invalid_target_penalty
                    ),
                ),
            ),
        )
    target_definition = card_registry.get(target_card.definition_id)
    terms = [
        constant_term(
            "decoy_bonus",
            profile.action_bonus.decoy_bonus,
            formula="decoy_bonus",
            details=(term_detail("decoy_bonus", profile.action_bonus.decoy_bonus),),
        )
    ]
    terms.append(
        weighted_term(
            "decoy_target_value",
            raw_value=target_definition.base_strength,
            raw_label="decoy_target_base_strength",
            weight=profile.action_bonus.decoy_target_strength_bonus,
            weight_label="decoy_target_strength_bonus",
            details=(term_detail("decoy_target_name", target_definition.name),),
        )
    )
    if AbilityKind.SPY in target_definition.ability_kinds:
        terms.append(
            constant_term(
                "decoy_spy_reclaim",
                profile.action_bonus.decoy_spy_reclaim_bonus,
                formula="decoy_spy_reclaim_bonus",
                details=(
                    term_detail(
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
            constant_term(
                "decoy_scorch_save",
                profile.action_bonus.decoy_scorch_save_bonus,
                formula="decoy_scorch_save_bonus",
                details=(
                    term_detail(
                        "decoy_scorch_save_bonus",
                        profile.action_bonus.decoy_scorch_save_bonus,
                    ),
                ),
            )
        )
    if target_card.owner != assessment.viewer_player_id:
        terms.append(
            constant_term(
                "decoy_opponent_resource_swing",
                profile.weights.card_advantage,
                formula="card_advantage_weight",
                details=(term_detail("card_advantage_weight", profile.weights.card_advantage),),
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
