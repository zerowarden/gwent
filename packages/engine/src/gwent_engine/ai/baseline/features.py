"""Small reusable heuristic signals for baseline evaluation.

These helpers are intentionally narrow and policy-free. Each function measures a
single tactical or strategic fact that higher-level modules can weight
differently depending on context or profile.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from typing import Protocol

from gwent_engine.cards import CardDefinition
from gwent_engine.core import AbilityKind, CardType, Row


class RowWeatherSummary(Protocol):
    @property
    def row(self) -> Row: ...

    @property
    def non_hero_unit_base_strength(self) -> int: ...

    @property
    def non_hero_unit_count(self) -> int: ...


def post_action_hand_value(definitions: Sequence[CardDefinition]) -> int:
    """Return the value of the hand that actually remains after a candidate play."""
    return sum(definition.base_strength for definition in definitions)


def preserved_leader_value(
    *,
    leader_used: bool,
    reserve_value: float,
) -> float:
    """Model the value of still having an unused leader ability in reserve."""
    return 0.0 if leader_used else reserve_value


def _duplicate_hand_synergy(definitions: Sequence[CardDefinition]) -> int:
    score = 0
    muster_counts = Counter(
        definition.muster_group for definition in definitions if definition.muster_group is not None
    )
    bond_counts = Counter(
        definition.bond_group for definition in definitions if definition.bond_group is not None
    )
    score += sum(count - 1 for count in muster_counts.values() if count > 1)
    score += sum(count - 1 for count in bond_counts.values() if count > 1)
    return score


def projected_synergy_value(
    remaining_hand: Sequence[CardDefinition],
    *,
    board_definitions: Sequence[CardDefinition] = (),
    discard_definitions: Sequence[CardDefinition] = (),
) -> int:
    """Estimate synergy still available after a candidate action resolves.

    This keeps the legacy hand-only duplicate count, but also values links
    between the remaining hand and the current board plus visible recursion
    value if a Medic line is still available later.
    """

    value = _duplicate_hand_synergy(remaining_hand)
    board_bond_groups = {
        definition.bond_group
        for definition in board_definitions
        if definition.bond_group is not None
    }
    board_muster_groups = {
        definition.muster_group
        for definition in board_definitions
        if definition.muster_group is not None
    }
    value += sum(definition.bond_group in board_bond_groups for definition in remaining_hand)
    value += sum(definition.muster_group in board_muster_groups for definition in remaining_hand)
    if any(AbilityKind.MEDIC in definition.ability_kinds for definition in remaining_hand):
        value += max(
            (
                definition.base_strength
                for definition in discard_definitions
                if definition.card_type == CardType.UNIT and not definition.is_hero
            ),
            default=0,
        )
    return value


def projected_scorch_loss(
    strengths: Sequence[int],
    *,
    threshold: int,
) -> int:
    """Measure the actual strength lost if Scorch hits the current top tier."""
    if not strengths:
        return 0
    highest = max(strengths)
    if highest < threshold:
        return 0
    return sum(strength for strength in strengths if strength == highest)


def dead_card_penalty(
    definitions: Sequence[CardDefinition],
    *,
    active_weather_rows: Collection[Row] = (),
) -> int:
    """Penalize weather cards in hand that are currently redundant or inactive."""
    active_rows = set(active_weather_rows)
    penalty = 0
    for definition in definitions:
        if AbilityKind.CLEAR_WEATHER in definition.ability_kinds and not active_rows:
            penalty += 1
        if AbilityKind.BITING_FROST in definition.ability_kinds and Row.CLOSE in active_rows:
            penalty += 1
        if AbilityKind.IMPENETRABLE_FOG in definition.ability_kinds and Row.RANGED in active_rows:
            penalty += 1
        if AbilityKind.TORRENTIAL_RAIN in definition.ability_kinds and Row.SIEGE in active_rows:
            penalty += 1
        if AbilityKind.SKELLIGE_STORM in definition.ability_kinds and {
            Row.RANGED,
            Row.SIEGE,
        }.issubset(active_rows):
            penalty += 1
    return penalty


def projected_weather_loss(
    row_summaries: Sequence[RowWeatherSummary],
    *,
    active_weather_rows: Collection[Row] = (),
) -> int:
    """Estimate current vulnerability as strength that weather would actually remove."""
    active_rows = set(active_weather_rows)
    return sum(
        max(0, summary.non_hero_unit_base_strength - summary.non_hero_unit_count)
        for summary in row_summaries
        if summary.row not in active_rows
    )
