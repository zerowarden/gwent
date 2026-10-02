"""Small reusable heuristic signals for baseline evaluation.

These helpers are intentionally narrow and policy-free. Each function measures a
single tactical or strategic fact that higher-level modules can weight
differently depending on context or profile.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Protocol

from gwent_engine.cards import CardDefinition
from gwent_engine.core import AbilityKind, Row
from gwent_engine.rules.weather import weather_rows_for

_WEATHER_ABILITY_KINDS = (
    AbilityKind.BITING_FROST,
    AbilityKind.IMPENETRABLE_FOG,
    AbilityKind.TORRENTIAL_RAIN,
    AbilityKind.SKELLIGE_STORM,
)


class RowWeatherSummary(Protocol):
    @property
    def row(self) -> Row: ...

    @property
    def non_hero_unit_base_strength(self) -> int: ...

    @property
    def non_hero_unit_count(self) -> int: ...


def preserved_leader_value(
    *,
    leader_used: bool,
    reserve_value: float,
) -> float:
    """Model the value of still having an unused leader ability in reserve."""
    return 0.0 if leader_used else reserve_value


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
        penalty += sum(
            1
            for ability_kind in _WEATHER_ABILITY_KINDS
            if ability_kind in definition.ability_kinds
            and set(weather_rows_for(ability_kind)) <= active_rows
        )
    return penalty


def weather_row_delta(summary: RowWeatherSummary) -> int:
    """Strength that applying weather to one row would remove."""

    return max(0, summary.non_hero_unit_base_strength - summary.non_hero_unit_count)
