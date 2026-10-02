"""Pending-choice classification and medic target eligibility."""

from __future__ import annotations

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import (
    AbilityKind,
    CardType,
    ChoiceKind,
    ChoiceSourceKind,
    LeaderAbilityKind,
    Row,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId, PlayerId
from gwent_engine.core.state import GameState, PendingChoice
from gwent_engine.rules.effect_applicability import can_target_for_medic
from gwent_engine.rules.row_effects import special_ability_kind

PENDING_CHOICE_LEADER_ABILITY_KINDS: frozenset[LeaderAbilityKind] = frozenset(
    (
        LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK,
        LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND,
        LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND,
    )
)


def card_requires_pending_choice(card_definition: CardDefinition) -> bool:
    if card_definition.card_type == CardType.UNIT:
        return AbilityKind.MEDIC in card_definition.ability_kinds
    if card_definition.card_type == CardType.SPECIAL:
        return special_ability_kind(card_definition) == AbilityKind.DECOY
    return False


def leader_requires_pending_choice(ability_kind: LeaderAbilityKind) -> bool:
    return ability_kind in PENDING_CHOICE_LEADER_ABILITY_KINDS


def eligible_medic_target_ids(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
) -> tuple[CardInstanceId, ...]:
    player = state.player(player_id)
    return tuple(
        card_id
        for card_id in player.discard
        if can_target_for_medic(
            state,
            card_registry,
            player=player,
            target_card_id=card_id,
        )
    )


def pending_medic_choice(
    state: GameState,
    *,
    card_registry: CardRegistry,
    player_id: PlayerId,
    source_card_instance_id: CardInstanceId,
    source_row: Row,
    event_counter: int,
) -> PendingChoice | None:
    legal_target_ids = eligible_medic_target_ids(state, card_registry, player_id)
    if not legal_target_ids:
        return None
    return PendingChoice(
        choice_id=ChoiceId(f"medic_{source_card_instance_id}_{event_counter}"),
        player_id=player_id,
        kind=ChoiceKind.SELECT_CARD_INSTANCE,
        source_kind=ChoiceSourceKind.MEDIC,
        source_card_instance_id=source_card_instance_id,
        legal_target_card_instance_ids=legal_target_ids,
        source_row=source_row,
    )
