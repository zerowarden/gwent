from __future__ import annotations

from collections.abc import Mapping
from math import ceil

from gwent_engine.ai.actions import action_to_id
from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import (
    DecisionContext,
    PressureMode,
    TacticalMode,
    TempoState,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import PassConfig
from gwent_engine.ai.tactical_values import action_commitment_value, estimated_response_value
from gwent_engine.ai.utils import viewer_hand_definition
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import GameAction, PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.rules.row_effects import special_ability_kind


def should_pass_now(
    assessment: DecisionAssessment,
    context: DecisionContext,
    *,
    config: PassConfig,
) -> bool:
    if not assessment.legal_pass_available:
        return False
    if context.mode == TacticalMode.ALL_IN:
        # Final / elimination rounds should not use the generic "protect lead
        # and preserve resources" pass rule. In these states, passing is only
        # correct when the opponent has already passed and the current effective
        # board state is still winning.
        return assessment.opponent_passed and assessment.score_gap > 0
    if assessment.opponent_passed and assessment.score_gap > 0:
        return True
    lead_margin = required_pass_lead(assessment, context=context, config=config)
    return (
        context.tempo == TempoState.AHEAD
        and assessment.score_gap >= lead_margin
        and context.preserve_resources
    )


def should_continue_contesting(
    assessment: DecisionAssessment,
    context: DecisionContext,
    *,
    config: PassConfig,
) -> bool:
    if assessment.is_elimination_round and assessment.score_gap < 0:
        return True
    return not should_pass_now(assessment, context, config=config)


def minimum_commitment_finish(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    config: PassConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> GameAction | None:
    if not assessment.opponent_passed or assessment.score_gap >= 0:
        return None
    required_points = abs(assessment.score_gap) + 1 + config.minimum_finish_buffer
    finishing_actions = [
        action
        for action in legal_actions
        if action_commitment_value(
            action,
            observation=observation,
            card_registry=card_registry,
            viewer_hand_definitions=viewer_hand_definitions,
            units_only=True,
            include_spies=False,
        )
        >= required_points
    ]
    if not finishing_actions:
        return None
    return min(
        finishing_actions,
        key=lambda action: (
            action_commitment_value(
                action,
                observation=observation,
                card_registry=card_registry,
                viewer_hand_definitions=viewer_hand_definitions,
                units_only=True,
                include_spies=False,
            ),
            action_to_id(action),
        ),
    )


def should_cut_losses_after_pass(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    config: PassConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> bool:
    """Return whether passing is the only remaining sensible line after a pass.

    The old version compared the visible score gap against flat visible tempo
    only. That is too pessimistic in rounds where the viewer can still expand
    the hand with a spy or a decoy-reclaim line. This function now uses a more
    conservative *reachable upside* estimate: visible commitment plus optimistic
    draw-enabled follow-up value from the remaining deck.

    The estimate is intentionally biased against declaring a round hopeless in
    final-round / elimination spots. If the viewer can still increase hand size
    from the deck, we prefer continuing over auto-passing unless even that
    optimistic line cannot catch up.
    """

    if (
        not assessment.legal_pass_available
        or not assessment.opponent_passed
        or assessment.score_gap >= 0
    ):
        return False
    required_points = abs(assessment.score_gap) + 1 + config.minimum_finish_buffer
    return (
        reachable_catch_up_potential(
            legal_actions,
            observation=observation,
            assessment=assessment,
            card_registry=card_registry,
            viewer_hand_definitions=viewer_hand_definitions,
        )
        < required_points
    )


def reachable_catch_up_potential(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> int:
    """Estimate how much catch-up upside still exists after the opponent passes.

    This intentionally combines two sources of upside:

    - visible commitment the viewer can already spend from the current hand
    - optimistic follow-up value from legal lines that can draw extra cards

    The second term matters because a spy, a medic reviving a spy, or a decoy
    reclaiming a spy can transform an apparently losing board into a live line.
    For hopeless-catch-up gating, that possibility matters more than precise
    tempo accounting, so this helper errs on the side of keeping the round live.
    """

    return total_commitment_potential(
        legal_actions,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    ) + _estimated_draw_followup_potential(
        legal_actions,
        observation=observation,
        assessment=assessment,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )


def required_pass_lead(
    assessment: DecisionAssessment,
    *,
    context: DecisionContext,
    config: PassConfig,
) -> int:
    static_margin = (
        config.elimination_safe_lead_margin
        if context.pressure == PressureMode.ELIMINATION
        else config.safe_lead_margin
    )
    return max(
        static_margin,
        _estimated_opponent_response(
            assessment,
            context=context,
            config=config,
        ),
    )


def total_commitment_potential(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> int:
    per_card_value: dict[CardInstanceId, int] = {}
    leader_value = 0
    for action in legal_actions:
        match action:
            case PlayCardAction(card_instance_id=card_instance_id):
                per_card_value[card_instance_id] = max(
                    per_card_value.get(card_instance_id, 0),
                    action_commitment_value(
                        action,
                        observation=observation,
                        card_registry=card_registry,
                        viewer_hand_definitions=viewer_hand_definitions,
                        units_only=True,
                        include_spies=False,
                    ),
                )
            case UseLeaderAbilityAction():
                leader_value = max(
                    leader_value,
                    action_commitment_value(
                        action,
                        observation=observation,
                        card_registry=card_registry,
                        viewer_hand_definitions=viewer_hand_definitions,
                        units_only=True,
                        include_spies=False,
                    ),
                )
            case _:
                continue
    return sum(per_card_value.values()) + leader_value


def _estimated_draw_followup_potential(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> int:
    """Estimate hidden upside from draw-enabling lines.

    The observation layer exposes only deck count, not the actual hidden deck
    order or remaining definitions. For hopeless-catch-up checks, we therefore
    use a conservative optimistic proxy: if a legal line can draw from a
    non-empty deck, treat each reachable draw as worth roughly one strong
    visible unit card. This prevents premature passes in spots where continuing
    is still strategically live.
    """

    deck_count = _viewer_deck_count(observation)
    if deck_count <= 0:
        return 0
    per_action_draws: dict[CardInstanceId, int] = {}
    for action in legal_actions:
        match action:
            case PlayCardAction(card_instance_id=card_instance_id):
                per_action_draws[card_instance_id] = max(
                    per_action_draws.get(card_instance_id, 0),
                    _draw_count_for_action(
                        action,
                        observation=observation,
                        assessment=assessment,
                        card_registry=card_registry,
                        viewer_hand_definitions=viewer_hand_definitions,
                    ),
                )
            case _:
                continue
    total_draws = min(deck_count, sum(per_action_draws.values()))
    if total_draws <= 0:
        return 0
    return total_draws * _optimistic_hidden_draw_value(assessment)


def _draw_count_for_action(
    action: PlayCardAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> int:
    definition = viewer_hand_definition(
        action.card_instance_id,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    if definition is None:
        return 0
    if AbilityKind.SPY in definition.ability_kinds:
        return 2
    if AbilityKind.MEDIC in definition.ability_kinds and _viewer_discard_has_spy(assessment):
        return 2
    if (
        definition.card_type == CardType.SPECIAL
        and special_ability_kind(definition) == AbilityKind.DECOY
        and _viewer_board_has_reclaimable_spy(observation, card_registry=card_registry)
    ):
        return 2
    return 0


def _optimistic_hidden_draw_value(assessment: DecisionAssessment) -> int:
    visible_unit_strengths = sorted(
        definition.base_strength
        for definition in (
            *assessment.viewer.hand_definitions,
            *assessment.viewer.discard_definitions,
        )
        if definition.card_type == CardType.UNIT and AbilityKind.SPY not in definition.ability_kinds
    )
    if not visible_unit_strengths:
        return 4
    strongest_visible = visible_unit_strengths[-min(len(visible_unit_strengths), 3) :]
    return max(4, ceil(sum(strongest_visible) / len(strongest_visible)))


def _viewer_discard_has_spy(assessment: DecisionAssessment) -> bool:
    return any(
        AbilityKind.SPY in definition.ability_kinds
        for definition in assessment.viewer.discard_definitions
    )


def _viewer_board_has_reclaimable_spy(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
) -> bool:
    viewer_player_id = observation.viewer_player_id
    public_players = observation.public_state.players
    viewer_public = (
        public_players[0] if public_players[0].player_id == viewer_player_id else public_players[1]
    )
    return any(
        AbilityKind.SPY in card_registry.get(card.definition_id).ability_kinds
        for cards in (
            viewer_public.rows.close,
            viewer_public.rows.ranged,
            viewer_public.rows.siege,
        )
        for card in cards
        if card.battlefield_side == viewer_player_id
    )


def _viewer_deck_count(observation: PlayerObservation) -> int:
    public_players = observation.public_state.players
    if public_players[0].player_id == observation.viewer_player_id:
        return public_players[0].deck_count
    return public_players[1].deck_count


def _estimated_opponent_response(
    assessment: DecisionAssessment,
    *,
    context: DecisionContext,
    config: PassConfig,
) -> int:
    return estimated_response_value(
        hand_count=assessment.opponent.hand_count,
        tempo_per_card=(
            config.elimination_estimated_opponent_tempo_per_card
            if context.pressure == PressureMode.ELIMINATION
            else config.estimated_opponent_tempo_per_card
        ),
    )
