from __future__ import annotations

from collections.abc import Mapping
from math import ceil

from gwent_engine.ai.baseline.assessment import DecisionAssessment
from gwent_engine.ai.baseline.context import (
    DecisionContext,
    PressureMode,
    TacticalMode,
    TempoState,
)
from gwent_engine.ai.baseline.projection import project_leader_action, project_play_action
from gwent_engine.ai.baseline.projection.context import viewer_public
from gwent_engine.ai.observation_queries import viewer_deck_count, viewer_hand_definition
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_TACTICAL_VALUE_POLICY, PassConfig
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import GameAction, PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.serialize.actions import action_to_id


def should_pass_now(
    assessment: DecisionAssessment,
    context: DecisionContext,
    *,
    config: PassConfig,
) -> bool:
    if not assessment.legal_pass_available:
        return False
    if context.mode == TacticalMode.ALL_IN:
        # Elimination rounds never use the generic "protect lead" pass rule; an
        # opponent pass classifies as FINISH_AFTER_PASS, not ALL_IN.
        return False
    if assessment.opponent_passed and assessment.score_gap > 0:
        return True
    lead_margin = required_pass_lead(assessment, context=context, config=config)
    return (
        context.tempo == TempoState.AHEAD
        and assessment.score_gap >= lead_margin
        and context.preserve_resources
    )


def minimum_commitment_finish(
    legal_actions: tuple[GameAction, ...],
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    config: PassConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
    leader_registry: LeaderRegistry | None = None,
) -> GameAction | None:
    """Cheapest action projected to take the lead by more than the finish buffer.

    Only non-spy unit plays and leader abilities with a projected effect qualify;
    the projections account for weather, horns, bonds and other row effects.
    """
    if not assessment.opponent_passed or assessment.score_gap >= 0:
        return None
    finishing_actions = [
        action
        for action in legal_actions
        if _projects_finish(
            action,
            observation=observation,
            assessment=assessment,
            card_registry=card_registry,
            config=config,
            viewer_hand_definitions=viewer_hand_definitions,
            leader_registry=leader_registry,
        )
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
            ),
            action_to_id(action),
        ),
    )


def _projects_finish(
    action: GameAction,
    *,
    observation: PlayerObservation,
    assessment: DecisionAssessment,
    card_registry: CardRegistry,
    config: PassConfig,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None,
    leader_registry: LeaderRegistry | None,
) -> bool:
    match action:
        case PlayCardAction(card_instance_id=card_instance_id):
            if (
                _committable_unit(
                    card_instance_id,
                    observation=observation,
                    card_registry=card_registry,
                    viewer_hand_definitions=viewer_hand_definitions,
                )
                is None
            ):
                return False
            play = project_play_action(
                action,
                observation=observation,
                card_registry=card_registry,
                viewer_hand_definitions=viewer_hand_definitions,
            )
            return play.projected_score_gap_after > config.minimum_finish_buffer
        case UseLeaderAbilityAction():
            leader = project_leader_action(
                action,
                observation=observation,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
            return (
                leader is not None
                and leader.has_effect
                and assessment.score_gap + leader.projected_net_board_swing
                > config.minimum_finish_buffer
            )
        case _:
            return False


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

    Uses a *reachable upside* estimate: visible commitment plus optimistic
    draw-enabled follow-up value from the remaining deck, so spy and
    decoy-reclaim lines that can still expand the hand keep the round alive.

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

    deck_count = viewer_deck_count(observation)
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
    viewer = viewer_public(observation)
    return any(
        AbilityKind.SPY in card_registry.get(card.definition_id).ability_kinds
        for cards in (viewer.rows.close, viewer.rows.ranged, viewer.rows.siege)
        for card in cards
        if card.battlefield_side == viewer_player_id
    )


def _estimated_opponent_response(
    assessment: DecisionAssessment,
    *,
    context: DecisionContext,
    config: PassConfig,
) -> int:
    return assessment.opponent.hand_count * config.opponent_tempo_per_card(
        elimination=context.pressure == PressureMode.ELIMINATION
    )


def action_commitment_value(
    action: GameAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> int:
    """Printed strength of a non-spy unit play, or the flat leader estimate."""
    match action:
        case UseLeaderAbilityAction():
            return DEFAULT_TACTICAL_VALUE_POLICY.leader_commitment_value
        case PlayCardAction(card_instance_id=card_instance_id):
            definition = _committable_unit(
                card_instance_id,
                observation=observation,
                card_registry=card_registry,
                viewer_hand_definitions=viewer_hand_definitions,
            )
            return 0 if definition is None else definition.base_strength
        case _:
            return 0


def _committable_unit(
    card_instance_id: CardInstanceId,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None,
) -> CardDefinition | None:
    """The hand card's definition when it is a unit that commits points to the viewer's side."""
    definition = viewer_hand_definition(
        card_instance_id,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    )
    if (
        definition is None
        or definition.card_type != CardType.UNIT
        or AbilityKind.SPY in definition.ability_kinds
    ):
        return None
    return definition
