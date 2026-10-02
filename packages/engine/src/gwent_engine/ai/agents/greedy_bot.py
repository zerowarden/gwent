from __future__ import annotations

from collections.abc import Sequence
from typing import final

from gwent_engine.ai.agents.protocol import require_resolve_choice
from gwent_engine.ai.mulligan_scoring import best_mulligan_selection
from gwent_engine.ai.observation_queries import (
    build_viewer_hand_definition_index,
    visible_definitions,
)
from gwent_engine.ai.observations import (
    PlayerObservation,
)
from gwent_engine.ai.policy import DEFAULT_GREEDY_ACTION_POLICY, DEFAULT_MULLIGAN_POLICY
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.serialize.actions import action_to_id


@final
class GreedyBot:
    def __init__(self, *, bot_id: str = "greedy_bot") -> None:
        self.bot_id = bot_id
        self.display_name = "GreedyBot"

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        del leader_registry
        if not legal_selections:
            raise ValueError("GreedyBot requires at least one mulligan selection.")
        hand_by_id = build_viewer_hand_definition_index(observation, card_registry)
        return best_mulligan_selection(
            legal_selections,
            hand_by_id,
            weights=DEFAULT_MULLIGAN_POLICY.greedy,
            policy=DEFAULT_MULLIGAN_POLICY,
            prefer_highest_card_ids=False,
        )

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del leader_registry
        if not legal_actions:
            raise ValueError("GreedyBot requires at least one legal action.")
        definition_index = visible_definitions(observation, card_registry)
        ranked = sorted(
            legal_actions,
            key=lambda action: (
                -_action_score(action, definition_index),
                action_to_id(action),
            ),
        )
        return ranked[0]

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> ResolveChoiceAction:
        del leader_registry
        action = self.choose_action(
            observation,
            legal_actions,
            card_registry=card_registry,
        )
        return require_resolve_choice(action, "GreedyBot")


def _action_score(
    action: GameAction,
    visible_definitions: dict[CardInstanceId, CardDefinition],
) -> int:
    if isinstance(action, ResolveChoiceAction):
        return _choice_action_score(action, visible_definitions)
    if isinstance(action, PlayCardAction):
        return _play_action_score(action, visible_definitions)
    return _non_play_action_score(action)


def _choice_action_score(
    action: ResolveChoiceAction,
    visible_definitions: dict[CardInstanceId, CardDefinition],
) -> int:
    return sum(
        _card_selection_score(visible_definitions.get(card_id))
        for card_id in action.selected_card_instance_ids
    )


def _play_action_score(
    action: PlayCardAction,
    visible_definitions: dict[CardInstanceId, CardDefinition],
) -> int:
    definition = visible_definitions.get(action.card_instance_id)
    if definition is None:
        return 0
    return _play_card_score(definition, target_row=action.target_row)


def _non_play_action_score(action: GameAction) -> int:
    if isinstance(action, UseLeaderAbilityAction):
        return DEFAULT_GREEDY_ACTION_POLICY.leader_action_score
    if isinstance(action, PassAction):
        return DEFAULT_GREEDY_ACTION_POLICY.pass_score
    if isinstance(action, StartGameAction):
        return 0
    return DEFAULT_GREEDY_ACTION_POLICY.unsupported_action_score


def _play_card_score(definition: CardDefinition, *, target_row: Row | None) -> int:
    score = definition.base_strength + _card_type_bonus(definition)
    if target_row is not None:
        score += _ROW_PREFERENCE[target_row]
    return score


_ROW_PREFERENCE = {Row.CLOSE: 3, Row.RANGED: 2, Row.SIEGE: 1}


def _card_type_bonus(definition: CardDefinition) -> int:
    if definition.card_type == CardType.UNIT:
        return _unit_card_bonus(definition)
    return _special_card_bonus(definition)


def _unit_card_bonus(definition: CardDefinition) -> int:
    policy = DEFAULT_GREEDY_ACTION_POLICY
    bonus = policy.hero_unit_bonus if definition.is_hero else 0
    bonus += policy.spy_unit_bonus if AbilityKind.SPY in definition.ability_kinds else 0
    bonus += policy.medic_unit_bonus if AbilityKind.MEDIC in definition.ability_kinds else 0
    bonus += (
        policy.morale_boost_unit_bonus
        if AbilityKind.MORALE_BOOST in definition.ability_kinds
        else 0
    )
    bonus += (
        policy.tight_bond_unit_bonus if AbilityKind.TIGHT_BOND in definition.ability_kinds else 0
    )
    bonus += (
        policy.unit_horn_bonus
        if AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds
        else 0
    )
    bonus += (
        policy.unit_scorch_row_bonus
        if AbilityKind.UNIT_SCORCH_ROW in definition.ability_kinds
        else 0
    )
    return bonus


def _special_card_bonus(definition: CardDefinition) -> int:
    policy = DEFAULT_GREEDY_ACTION_POLICY
    for ability_kind, bonus in policy.special_card_bonuses:
        if ability_kind in definition.ability_kinds:
            return bonus
    return policy.fallback_special_bonus


def _card_selection_score(definition: CardDefinition | None) -> int:
    if definition is None:
        return 0
    score = definition.base_strength
    if definition.is_hero:
        score += DEFAULT_GREEDY_ACTION_POLICY.selection_hero_bonus
    if AbilityKind.MEDIC in definition.ability_kinds:
        score += DEFAULT_GREEDY_ACTION_POLICY.selection_medic_bonus
    if AbilityKind.SPY in definition.ability_kinds:
        score += DEFAULT_GREEDY_ACTION_POLICY.selection_spy_bonus
    return score
