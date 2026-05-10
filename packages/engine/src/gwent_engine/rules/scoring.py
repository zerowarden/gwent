from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, LeaderAbilityKind, Row, Zone
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import CardInstance, GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.battlefield_effects import active_weather_cards, weather_card_affects_row
from gwent_engine.rules.effect_applicability import is_hero
from gwent_engine.rules.leader_effects import (
    any_enabled_passive_leader_has_ability,
    player_has_enabled_passive_leader_ability,
)

_ROW_SCORE_CONTEXT_CACHE_PREFIX = "row_score_context"


@dataclass(frozen=True, slots=True)
class _RowScoreContext:
    weathered_rows: frozenset[Row]
    horn_rows: frozenset[tuple[PlayerId, Row]]
    morale_counts: Mapping[tuple[PlayerId, Row], int]
    tight_bond_multipliers: Mapping[CardInstanceId, int]
    halve_weather_penalty_players: frozenset[PlayerId]
    double_spy_strength_global: bool


@dataclass(frozen=True, slots=True)
class PlayerScore:
    player_id: PlayerId
    close: int
    ranged: int
    siege: int

    @property
    def total(self) -> int:
        return self.close + self.ranged + self.siege


def calculate_row_score(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    row: Row,
    *,
    leader_registry: LeaderRegistry | None = None,
) -> int:
    player = state.player(player_id)
    return sum(
        calculate_effective_strength(
            state,
            card_registry,
            card_id,
            leader_registry=leader_registry,
        )
        for card_id in player.rows.cards_for(row)
    )


def calculate_player_score(
    state: GameState,
    card_registry: CardRegistry,
    player_id: PlayerId,
    *,
    leader_registry: LeaderRegistry | None = None,
) -> PlayerScore:
    return PlayerScore(
        player_id=player_id,
        close=calculate_row_score(
            state,
            card_registry,
            player_id,
            Row.CLOSE,
            leader_registry=leader_registry,
        ),
        ranged=calculate_row_score(
            state,
            card_registry,
            player_id,
            Row.RANGED,
            leader_registry=leader_registry,
        ),
        siege=calculate_row_score(
            state,
            card_registry,
            player_id,
            Row.SIEGE,
            leader_registry=leader_registry,
        ),
    )


def calculate_round_scores(
    state: GameState,
    card_registry: CardRegistry,
    *,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[PlayerScore, PlayerScore]:
    first_player, second_player = state.players
    return (
        calculate_player_score(
            state,
            card_registry,
            first_player.player_id,
            leader_registry=leader_registry,
        ),
        calculate_player_score(
            state,
            card_registry,
            second_player.player_id,
            leader_registry=leader_registry,
        ),
    )


def calculate_effective_strength(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    *,
    leader_registry: LeaderRegistry | None = None,
) -> int:
    score_context = _row_score_context(state, card_registry, leader_registry)
    card = state.card(card_id)
    definition = card_registry.get(card.definition_id)
    if definition.card_type != CardType.UNIT:
        return 0
    if card.zone != Zone.BATTLEFIELD or card.row is None:
        return definition.base_strength
    if is_hero(state, card_registry, card_id):
        return definition.base_strength
    strength = _base_battlefield_strength(
        state,
        card_id,
        definition.base_strength,
        score_context=score_context,
    )
    strength = _apply_leader_strength_modifiers(
        strength,
        definition=definition,
        score_context=score_context,
    )
    strength = _apply_tight_bond(score_context, card_id, strength)
    strength = _apply_morale_boost(score_context, definition, card, strength)
    return _apply_horn(score_context, card, strength)


def battlefield_effective_strengths(
    state: GameState,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> dict[CardInstanceId, int]:
    return {
        card.instance_id: calculate_effective_strength(
            state,
            card_registry,
            card.instance_id,
            leader_registry=leader_registry,
        )
        for card in state.card_instances
        if card.zone == Zone.BATTLEFIELD
    }


def _base_battlefield_strength(
    state: GameState,
    card_id: CardInstanceId,
    base_strength: int,
    *,
    score_context: _RowScoreContext,
) -> int:
    return _apply_weather(
        state,
        card_id,
        base_strength,
        score_context=score_context,
    )


def _apply_weather(
    state: GameState,
    card_id: CardInstanceId,
    strength: int,
    *,
    score_context: _RowScoreContext,
) -> int:
    card = state.card(card_id)
    assert card.row is not None
    if card.row not in score_context.weathered_rows:
        return strength
    battlefield_side = _battlefield_side_for_strength(state, card_id)
    if battlefield_side in score_context.halve_weather_penalty_players:
        return (strength + 1) // 2
    return 1


def _apply_leader_strength_modifiers(
    strength: int,
    *,
    definition: CardDefinition,
    score_context: _RowScoreContext,
) -> int:
    if score_context.double_spy_strength_global and AbilityKind.SPY in definition.ability_kinds:
        return strength * 2
    return strength


def _apply_tight_bond(
    score_context: _RowScoreContext,
    card_id: CardInstanceId,
    strength: int,
) -> int:
    return strength * score_context.tight_bond_multipliers.get(card_id, 1)


def _apply_morale_boost(
    score_context: _RowScoreContext,
    definition: CardDefinition,
    card: CardInstance,
    strength: int,
) -> int:
    assert card.row is not None
    if card.battlefield_side is None:
        return strength
    morale_count = score_context.morale_counts.get((card.battlefield_side, card.row), 0)
    if AbilityKind.MORALE_BOOST in definition.ability_kinds:
        morale_count -= 1
    return strength + max(0, morale_count)


def _apply_horn(
    score_context: _RowScoreContext,
    card: CardInstance,
    strength: int,
) -> int:
    assert card.row is not None
    battlefield_side = _battlefield_side_for_card(card)
    if (battlefield_side, card.row) in score_context.horn_rows:
        return strength * 2
    return strength


def _battlefield_side_for_strength(state: GameState, card_id: CardInstanceId) -> PlayerId:
    return _battlefield_side_for_card(state.card(card_id))


def _battlefield_side_for_card(card: CardInstance) -> PlayerId:
    battlefield_side = card.battlefield_side
    if battlefield_side is None:
        raise ValueError(f"Battlefield unit {card.instance_id!r} is missing battlefield_side.")
    return battlefield_side


def _row_score_context(
    state: GameState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> _RowScoreContext:
    cache_key = (_ROW_SCORE_CONTEXT_CACHE_PREFIX, id(card_registry), id(leader_registry))
    return state.cached_or_compute(
        cache_key,
        lambda: _build_row_score_context(state, card_registry, leader_registry),
    )


def _build_row_score_context(
    state: GameState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> _RowScoreContext:
    weathered_rows = _weathered_rows(state, card_registry)
    horn_rows: set[tuple[PlayerId, Row]] = set()
    morale_counts: dict[tuple[PlayerId, Row], int] = {}
    tight_bond_multipliers: dict[CardInstanceId, int] = {}

    for player in state.players:
        for row in Row:
            row_card_ids = player.rows.cards_for(row)
            definitions = _definitions_by_card_id(state, card_registry, row_card_ids)
            morale_count, has_row_horn, bond_groups = _row_signals(definitions)
            morale_counts[(player.player_id, row)] = morale_count
            if has_row_horn or player.leader.horn_row == row:
                horn_rows.add((player.player_id, row))
            for card_id, definition in definitions.items():
                if (
                    definition.card_type == CardType.UNIT
                    and AbilityKind.TIGHT_BOND in definition.ability_kinds
                    and definition.bond_group is not None
                ):
                    tight_bond_multipliers[card_id] = max(1, bond_groups[definition.bond_group])

    halve_weather_penalty_players = frozenset(
        player.player_id
        for player in state.players
        if player_has_enabled_passive_leader_ability(
            state,
            leader_registry,
            player_id=player.player_id,
            ability_kind=LeaderAbilityKind.HALVE_WEATHER_PENALTY,
        )
    )
    return _RowScoreContext(
        weathered_rows=weathered_rows,
        horn_rows=frozenset(horn_rows),
        morale_counts=MappingProxyType(morale_counts),
        tight_bond_multipliers=MappingProxyType(tight_bond_multipliers),
        halve_weather_penalty_players=halve_weather_penalty_players,
        double_spy_strength_global=any_enabled_passive_leader_has_ability(
            state,
            leader_registry,
            LeaderAbilityKind.DOUBLE_SPY_STRENGTH_GLOBAL,
        ),
    )


def _weathered_rows(state: GameState, card_registry: CardRegistry) -> frozenset[Row]:
    weather_card_ids = active_weather_cards(state)
    return frozenset(
        row
        for row in Row
        if any(
            weather_card_affects_row(state, card_registry, card_id, row)
            for card_id in weather_card_ids
        )
    )


def _definitions_by_card_id(
    state: GameState,
    card_registry: CardRegistry,
    card_ids: tuple[CardInstanceId, ...],
) -> dict[CardInstanceId, CardDefinition]:
    return {card_id: card_registry.get(state.card(card_id).definition_id) for card_id in card_ids}


def _row_signals(
    definitions: Mapping[CardInstanceId, CardDefinition],
) -> tuple[int, bool, Counter[str]]:
    morale_count = 0
    bond_groups: Counter[str] = Counter()
    has_row_horn = False
    for definition in definitions.values():
        if _is_unit_definition(definition):
            morale_count += _unit_morale_signal(definition)
            _add_unit_bond_signal(definition, bond_groups)
            has_row_horn = has_row_horn or _unit_has_horn_signal(definition)
            continue
        has_row_horn = has_row_horn or _special_has_horn_signal(definition)
    return morale_count, has_row_horn, bond_groups


def _is_unit_definition(definition: CardDefinition) -> bool:
    return definition.card_type == CardType.UNIT


def _unit_morale_signal(definition: CardDefinition) -> int:
    return int(AbilityKind.MORALE_BOOST in definition.ability_kinds)


def _add_unit_bond_signal(
    definition: CardDefinition,
    bond_groups: Counter[str],
) -> None:
    if AbilityKind.TIGHT_BOND in definition.ability_kinds and definition.bond_group is not None:
        bond_groups[definition.bond_group] += 1


def _unit_has_horn_signal(definition: CardDefinition) -> bool:
    return AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds


def _special_has_horn_signal(definition: CardDefinition) -> bool:
    return definition.card_type == CardType.SPECIAL and definition.ability_kinds == (
        AbilityKind.COMMANDERS_HORN,
    )
