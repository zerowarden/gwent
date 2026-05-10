from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.actions import action_to_id
from gwent_engine.ai.baseline.projection import projected_future_card_value
from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.ai.policy import DEFAULT_PENDING_CHOICE_POLICY
from gwent_engine.ai.row_preference import row_preference
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, ChoiceSourceKind, LeaderAbilityKind
from gwent_engine.core.actions import GameAction, ResolveChoiceAction
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry


@dataclass(frozen=True, slots=True)
class _LeaderChoiceZones:
    viewer_hand_ids: set[CardInstanceId]
    viewer_deck_ids: set[CardInstanceId]
    viewer_discard_ids: set[CardInstanceId]
    opponent_discard_ids: set[CardInstanceId]


@dataclass(slots=True)
class _LeaderSelectionScore:
    discard_cost: int = 0
    deck_pick_value: int = 0
    own_discard_return_value: int = 0
    opponent_discard_steal_value: int = 0
    discarded_count: int = 0
    picked_count: int = 0


def choose_pending_choice_action(
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> ResolveChoiceAction:
    pending_choice = observation.visible_pending_choice
    if pending_choice is None:
        raise ValueError("No visible pending choice to resolve.")
    resolution_actions = tuple(
        action for action in legal_actions if isinstance(action, ResolveChoiceAction)
    )
    if not resolution_actions:
        raise ValueError("choose_pending_choice_action requires at least one legal action.")
    return max(
        resolution_actions,
        key=lambda action: (
            pending_choice_score(
                action,
                observation=observation,
                card_registry=card_registry,
                leader_registry=leader_registry,
            ),
            row_preference(action.selected_rows[0]) if action.selected_rows else 0,
            -len(action.selected_card_instance_ids),
            action_to_id(action),
        ),
    )


def pending_choice_score(
    action: ResolveChoiceAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> int:
    return sum(
        value
        for _, value in explain_pending_choice_score_components(
            action,
            observation=observation,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    )


def explain_pending_choice_score_components(
    action: ResolveChoiceAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[tuple[str, int], ...]:
    pending_choice = observation.visible_pending_choice
    if pending_choice is None:
        raise ValueError("No visible pending choice to explain.")
    target_definitions = _visible_definitions(observation, card_registry)
    if action.selected_rows:
        return (("row_preference", sum(row_preference(row) for row in action.selected_rows)),)
    if pending_choice.source_kind == ChoiceSourceKind.LEADER_ABILITY:
        return _leader_choice_score_components(
            action,
            observation=observation,
            card_registry=card_registry,
            target_definitions=target_definitions,
            leader_registry=leader_registry,
        )
    components = [
        _target_score_components(
            target_definitions.get(card_id),
            source_kind=pending_choice.source_kind,
            observation=observation,
        )
        for card_id in action.selected_card_instance_ids
    ]
    return tuple(
        (name, sum(component.get(name, 0) for component in components))
        for name in (
            "target_base_strength",
            "decoy_target_spy_bonus",
            "decoy_target_medic_bonus",
            "medic_target_spy_bonus",
            "medic_target_medic_bonus",
        )
        if any(component.get(name, 0) for component in components)
    )


def _leader_choice_score_components(
    action: ResolveChoiceAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    target_definitions: dict[CardInstanceId, CardDefinition],
    leader_registry: LeaderRegistry | None,
) -> tuple[tuple[str, int], ...]:
    pending_choice = observation.visible_pending_choice
    if pending_choice is None or pending_choice.source_leader_id is None or leader_registry is None:
        return ()
    leader_definition = leader_registry.get(pending_choice.source_leader_id)
    selection_score = _leader_selection_score(
        action.selected_card_instance_ids,
        observation=observation,
        card_registry=card_registry,
        target_definitions=target_definitions,
        leader_definition=leader_definition,
        zones=_leader_choice_zones(observation),
    )
    return _leader_selection_components(leader_definition, selection_score)


def _leader_choice_zones(observation: PlayerObservation) -> _LeaderChoiceZones:
    return _LeaderChoiceZones(
        viewer_hand_ids={card.instance_id for card in observation.viewer_hand},
        viewer_deck_ids={card.instance_id for card in observation.viewer_deck},
        viewer_discard_ids={
            card.instance_id
            for card in _public_player_discard(
                observation,
                player_id=observation.viewer_player_id,
            )
        },
        opponent_discard_ids={
            card.instance_id
            for card in _public_player_discard(
                observation,
                player_id=_opponent_player_id(observation),
            )
        },
    )


def _leader_selection_score(
    selected_card_ids: tuple[CardInstanceId, ...],
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    target_definitions: dict[CardInstanceId, CardDefinition],
    leader_definition: LeaderDefinition,
    zones: _LeaderChoiceZones,
) -> _LeaderSelectionScore:
    score = _LeaderSelectionScore()
    for card_id in selected_card_ids:
        definition = target_definitions.get(card_id)
        if definition is None or not _leader_target_is_eligible(definition, leader_definition):
            continue
        future_value = projected_future_card_value(
            definition,
            observation=observation,
            card_registry=card_registry,
        )
        _add_leader_selection_value(score, card_id, future_value, zones)
    return score


def _leader_target_is_eligible(
    definition: CardDefinition,
    leader_definition: LeaderDefinition,
) -> bool:
    if leader_definition.ability_kind not in {
        LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND,
        LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND,
    }:
        return True
    return definition.card_type == CardType.UNIT and not definition.is_hero


def _add_leader_selection_value(
    score: _LeaderSelectionScore,
    card_id: CardInstanceId,
    future_value: int,
    zones: _LeaderChoiceZones,
) -> None:
    if card_id in zones.viewer_hand_ids:
        score.discard_cost += future_value
        score.discarded_count += 1
    elif card_id in zones.viewer_deck_ids:
        score.deck_pick_value += future_value
        score.picked_count += 1
    elif card_id in zones.viewer_discard_ids:
        score.own_discard_return_value += future_value
    elif card_id in zones.opponent_discard_ids:
        score.opponent_discard_steal_value += future_value


def _leader_selection_components(
    leader_definition: LeaderDefinition,
    score: _LeaderSelectionScore,
) -> tuple[tuple[str, int], ...]:
    match leader_definition.ability_kind:
        case LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK:
            return _discard_and_choose_components(leader_definition, score)
        case LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND:
            return _single_component("leader_return_value", score.own_discard_return_value)
        case LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND:
            return _single_component("leader_steal_value", score.opponent_discard_steal_value)
        case _:
            return ()


def _discard_and_choose_components(
    leader_definition: LeaderDefinition,
    score: _LeaderSelectionScore,
) -> tuple[tuple[str, int], ...]:
    if (
        score.discarded_count != leader_definition.hand_discard_count
        or score.picked_count != leader_definition.deck_pick_count
    ):
        return (
            (
                "leader_invalid_selection_penalty",
                DEFAULT_PENDING_CHOICE_POLICY.invalid_leader_selection_penalty,
            ),
        )
    components: list[tuple[str, int]] = []
    if score.discard_cost:
        components.append(("leader_discard_cost", -score.discard_cost))
    if score.deck_pick_value:
        components.append(("leader_deck_pick_value", score.deck_pick_value))
    return tuple(components)


def _single_component(name: str, value: int) -> tuple[tuple[str, int], ...]:
    return ((name, value),) if value else ()


def _opponent_player_id(observation: PlayerObservation) -> PlayerId:
    return next(
        player.player_id
        for player in observation.public_state.players
        if player.player_id != observation.viewer_player_id
    )


def _public_player_discard(
    observation: PlayerObservation,
    *,
    player_id: PlayerId,
) -> tuple[ObservedCard, ...]:
    player = next(
        player for player in observation.public_state.players if player.player_id == player_id
    )
    return player.discard


def _target_score_components(
    definition: CardDefinition | None,
    *,
    source_kind: ChoiceSourceKind,
    observation: PlayerObservation,
) -> dict[str, int]:
    """Return explainable value terms for choosing a pending-choice target.

    The base-strength term is shared by all target choices, while each choice
    source adds only the tactical text it can actually exploit. Decoy values
    replayable Spy/Medic bodies directly; Medic values revived Spies using the
    viewer's remaining deck size so an empty deck does not create fake draw
    value.
    """
    if definition is None:
        return {}
    components: dict[str, int] = {"target_base_strength": definition.base_strength}
    match source_kind:
        case ChoiceSourceKind.DECOY:
            components.update(_decoy_target_score_components(definition))
        case ChoiceSourceKind.MEDIC:
            components.update(_medic_target_score_components(definition, observation))
        case _:
            pass
    return components


def _decoy_target_score_components(definition: CardDefinition) -> dict[str, int]:
    components: dict[str, int] = {}
    if AbilityKind.SPY in definition.ability_kinds:
        components["decoy_target_spy_bonus"] = DEFAULT_PENDING_CHOICE_POLICY.decoy_target_spy_bonus
    if AbilityKind.MEDIC in definition.ability_kinds:
        components["decoy_target_medic_bonus"] = (
            DEFAULT_PENDING_CHOICE_POLICY.decoy_target_medic_bonus
        )
    return components


def _medic_target_score_components(
    definition: CardDefinition,
    observation: PlayerObservation,
) -> dict[str, int]:
    components: dict[str, int] = {}
    if AbilityKind.SPY in definition.ability_kinds:
        spy_bonus = DEFAULT_PENDING_CHOICE_POLICY.medic_target_spy_draw_bonus * min(
            DEFAULT_PENDING_CHOICE_POLICY.medic_target_spy_max_draws,
            len(observation.viewer_deck),
        )
        if spy_bonus > 0:
            components["medic_target_spy_bonus"] = spy_bonus
    if AbilityKind.MEDIC in definition.ability_kinds:
        components["medic_target_medic_bonus"] = (
            DEFAULT_PENDING_CHOICE_POLICY.medic_target_medic_bonus
        )
    return components


def _visible_definitions(
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> dict[CardInstanceId, CardDefinition]:
    visible_cards = (
        *observation.viewer_hand,
        *observation.viewer_deck,
        *observation.public_state.players[0].discard,
        *observation.public_state.players[1].discard,
        *observation.public_state.players[0].rows.close,
        *observation.public_state.players[0].rows.ranged,
        *observation.public_state.players[0].rows.siege,
        *observation.public_state.players[1].rows.close,
        *observation.public_state.players[1].rows.ranged,
        *observation.public_state.players[1].rows.siege,
        *observation.public_state.battlefield_weather.close,
        *observation.public_state.battlefield_weather.ranged,
        *observation.public_state.battlefield_weather.siege,
    )
    return {card.instance_id: card_registry.get(card.definition_id) for card in visible_cards}
