from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from gwent_engine.ai.policy import DEFAULT_MULLIGAN_POLICY, MulliganScoreWeights
from gwent_engine.cards import CardDefinition
from gwent_engine.core import AbilityKind, CardType
from gwent_engine.core.actions import MulliganSelection
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId


def best_mulligan_selection(
    legal_selections: Sequence[MulliganSelection],
    hand_by_id: Mapping[CardInstanceId, CardDefinition],
    definition_counts: Counter[CardDefinitionId],
    *,
    weights: MulliganScoreWeights,
    prefer_highest_card_ids: bool,
) -> MulliganSelection:
    """Highest-scoring selection, then fewest replacements, then the card-id tie-break.

    Bots differ only in the final tie-break between equally scored selections of
    equal size: the lowest or the highest card-id tuple.
    """

    def rank(selection: MulliganSelection) -> tuple[int, int]:
        score = mulligan_selection_score(selection, hand_by_id, definition_counts, weights=weights)
        return score, -len(selection.cards_to_replace)

    best_rank = max(rank(selection) for selection in legal_selections)
    tied = [selection for selection in legal_selections if rank(selection) == best_rank]
    pick = max if prefer_highest_card_ids else min
    return pick(tied, key=lambda selection: tuple(map(str, selection.cards_to_replace)))


def mulligan_selection_score(
    selection: MulliganSelection,
    hand_by_id: Mapping[CardInstanceId, CardDefinition],
    definition_counts: Counter[CardDefinitionId],
    *,
    weights: MulliganScoreWeights,
) -> int:
    if not selection.cards_to_replace:
        return 0
    return sum(
        mulligan_card_score(hand_by_id[card_id], definition_counts, weights=weights)
        for card_id in selection.cards_to_replace
    )


def mulligan_card_score(
    definition: CardDefinition,
    definition_counts: Counter[CardDefinitionId],
    *,
    weights: MulliganScoreWeights,
) -> int:
    if definition.is_hero:
        return DEFAULT_MULLIGAN_POLICY.hero_keep_bonus
    score = max(0, DEFAULT_MULLIGAN_POLICY.low_strength_anchor - definition.base_strength)
    if definition.card_type == CardType.SPECIAL:
        score += DEFAULT_MULLIGAN_POLICY.special_card_penalty
    if definition_counts[definition.definition_id] > 1 and definition.bond_group is None:
        score += DEFAULT_MULLIGAN_POLICY.duplicate_non_bond_penalty
    if AbilityKind.SPY in definition.ability_kinds:
        score += DEFAULT_MULLIGAN_POLICY.spy_keep_bonus
    if AbilityKind.MEDIC in definition.ability_kinds:
        score += weights.medic_keep_bonus
    if AbilityKind.TIGHT_BOND in definition.ability_kinds:
        score += weights.tight_bond_keep_bonus
    if AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds:
        score += weights.unit_horn_keep_bonus
    return score
