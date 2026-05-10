"""Typed classification helpers for narrow pending-choice behavior."""

from gwent_engine.cards import CardDefinition
from gwent_engine.core import AbilityKind, CardType, LeaderAbilityKind
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
