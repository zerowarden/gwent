from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from math import comb

from gwent_engine.ai.baseline.projection.battlefield import (
    merged_projected_battlefield_cards,
    projected_row_has_active_mardroeme,
)
from gwent_engine.ai.baseline.projection.board import (
    BoardProjectionContext,
    ProjectedBattlefieldCard,
    board_projection,
    current_public_board_projection,
    current_public_scorch_impact,
)
from gwent_engine.ai.baseline.projection.context import active_weather_rows, viewer_public
from gwent_engine.ai.baseline.projection.models import ProjectedRowState, PublicBoardProjection
from gwent_engine.ai.observations import ObservedCard, PlayerObservation
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY, DEFAULT_PROJECTION_POLICY
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.rules.battlefield_effects import is_weather_ability, weather_rows_for
from gwent_engine.rules.row_effects import special_ability_kind


def projected_future_card_value(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    board: PublicBoardProjection | None = None,
) -> int:
    """Estimate the future utility of adding one visible card to the viewer hand.

    This is intentionally coarser than full action evaluation. It provides one
    stable value surface for leader abilities and leader-driven pending-choice
    selections that move cards into or out of hand without playing them
    immediately.
    """

    resolved_board = board or current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    value = definition.base_strength
    if definition.is_hero:
        value += 2
    if definition.card_type == CardType.UNIT:
        value += _projected_future_unit_bonus(
            definition,
            observation=observation,
            card_registry=card_registry,
            board=resolved_board,
        )
    elif definition.card_type == CardType.SPECIAL:
        value += _projected_future_special_bonus(
            definition,
            observation=observation,
            card_registry=card_registry,
            board=resolved_board,
        )
    return max(value, 0)


def _projected_future_unit_bonus(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    board: PublicBoardProjection,
) -> int:
    bonus = projected_held_unit_tactical_reserve_value(
        definition,
        observation=observation,
        card_registry=card_registry,
        board=board,
    )
    if AbilityKind.SPY in definition.ability_kinds:
        bonus += min(2, len(observation.viewer_deck)) * 4
    if AbilityKind.MEDIC in definition.ability_kinds:
        bonus += best_visible_revival_strength(
            viewer_public(observation).discard,
            card_registry=card_registry,
        )
    bonus += _projected_future_muster_bonus(
        definition,
        observation=observation,
        card_registry=card_registry,
    )
    bonus += _projected_future_tight_bond_bonus(
        definition,
        observation=observation,
        card_registry=card_registry,
    )
    return bonus


def _projected_future_muster_bonus(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> int:
    if (
        AbilityKind.MUSTER not in definition.ability_kinds
        or definition.resolved_musters_group is None
    ):
        return 0
    return sum(
        card_registry.get(card.definition_id).base_strength
        for card in observation.viewer_deck
        if card_registry.get(card.definition_id).muster_group == definition.resolved_musters_group
    )


def _projected_future_tight_bond_bonus(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> int:
    if AbilityKind.TIGHT_BOND not in definition.ability_kinds or definition.bond_group is None:
        return 0
    visible_bond_matches = sum(
        1
        for card in (
            *observation.viewer_hand,
            *observation.viewer_deck,
            *viewer_public(observation).discard,
            *viewer_public(observation).rows.close,
            *viewer_public(observation).rows.ranged,
            *viewer_public(observation).rows.siege,
        )
        if card_registry.get(card.definition_id).bond_group == definition.bond_group
    )
    return max(0, visible_bond_matches - 1) * definition.base_strength


def _projected_future_special_bonus(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    board: PublicBoardProjection,
) -> int:
    bonus = 0
    ability_kind = special_ability_kind(definition)
    match ability_kind:
        case AbilityKind.SCORCH:
            bonus += max(
                0,
                current_public_scorch_impact(
                    observation,
                    card_registry=card_registry,
                ).net_swing,
            )
        case AbilityKind.COMMANDERS_HORN:
            bonus += max(
                (
                    row.non_hero_effective_strength
                    for row in board.viewer_rows
                    if not row.horn_active and row.non_hero_unit_count > 0
                ),
                default=0,
            )
        case kind if is_weather_ability(kind):
            bonus += max(
                0,
                project_weather_card_swing(
                    kind,
                    observation=observation,
                    card_registry=card_registry,
                ),
            )
        case AbilityKind.CLEAR_WEATHER:
            current_board = current_public_board_projection(
                observation,
                card_registry=card_registry,
            )
            bonus += max(
                0,
                board_projection(
                    observation,
                    card_registry=card_registry,
                    projected_cards=(),
                    active_weather_rows=(),
                ).score_gap
                - current_board.score_gap,
            )
        case AbilityKind.DECOY:
            bonus += projected_decoy_reclaim_value(
                observation,
                card_registry=card_registry,
            )
        case AbilityKind.MARDROEME:
            bonus += projected_mardroeme_setup_value(
                observation,
                card_registry=card_registry,
            )
        case _:
            pass
    return bonus


def best_visible_revival_strength(
    cards: tuple[ObservedCard, ...],
    *,
    card_registry: CardRegistry,
) -> int:
    return max(
        (
            card_registry.get(card.definition_id).base_strength
            for card in cards
            if (
                card_registry.get(card.definition_id).card_type == CardType.UNIT
                and not card_registry.get(card.definition_id).is_hero
            )
        ),
        default=0,
    )


def project_weather_card_swing(
    ability_kind: AbilityKind,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> int:
    current_board = current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    current_weather_rows = set(active_weather_rows(observation))
    board_after = board_projection(
        observation,
        card_registry=card_registry,
        projected_cards=(),
        active_weather_rows=tuple(
            sorted(
                current_weather_rows | set(weather_rows_for(ability_kind)),
                key=lambda row: row.value,
            )
        ),
    )
    return board_after.score_gap - current_board.score_gap


def projected_decoy_reclaim_value(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
) -> int:
    targets = (
        *viewer_public(observation).rows.close,
        *viewer_public(observation).rows.ranged,
        *viewer_public(observation).rows.siege,
    )
    best_target = 0
    for card in targets:
        definition = card_registry.get(card.definition_id)
        target_value = definition.base_strength
        if AbilityKind.SPY in definition.ability_kinds:
            target_value += DEFAULT_PROJECTION_POLICY.decoy_spy_reclaim_bonus
        if AbilityKind.MEDIC in definition.ability_kinds:
            target_value += DEFAULT_PROJECTION_POLICY.decoy_medic_reclaim_bonus
        best_target = max(best_target, target_value)
    return best_target


def projected_mardroeme_setup_value(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
) -> int:
    board_cards = (
        *viewer_public(observation).rows.close,
        *viewer_public(observation).rows.ranged,
        *viewer_public(observation).rows.siege,
    )
    if any(
        card_registry.get(card.definition_id).definition_id
        in {
            "skellige_berserker",
            "skellige_young_berserker",
        }
        for card in board_cards
    ):
        return DEFAULT_PROJECTION_POLICY.mardroeme_setup_value
    return 0


def reachable_horn_option_value(
    rows: Iterable[ProjectedRowState],
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    hand_definitions: Iterable[CardDefinition],
    draw_count: int,
) -> float:
    """Return the remaining horn option value reachable from this position.

    This is not the immediate payoff from playing a horn card. It is the best
    horn-enabled row upside that remains accessible after the action, which lets
    the caller compute a before/after delta for future horn flexibility.

    Horn option value is:
    - guaranteed when a horn-capable source is already in hand
    - guaranteed on one specific row when an unused horn-own-row leader exists
    - otherwise probabilistic only when the current action immediately draws
      from deck
    """

    row_gains = {
        row.row: row.non_hero_effective_strength
        for row in rows
        if row.non_hero_unit_count > 0 and not row.horn_active
    }
    if not row_gains:
        return 0.0

    guaranteed_rows: set[Row] = set()
    for definition in hand_definitions:
        guaranteed_rows.update(_horn_source_rows(definition))

    viewer_leader = viewer_public(observation).leader
    if viewer_leader.available_horn_row is not None:
        guaranteed_rows.add(viewer_leader.available_horn_row)

    guaranteed_gain = max(
        (row_gains[row] for row in guaranteed_rows if row in row_gains),
        default=0.0,
    )
    if draw_count <= 0 or not observation.viewer_deck:
        return guaranteed_gain

    draws = min(draw_count, len(observation.viewer_deck))
    deck_definitions = [card_registry.get(card.definition_id) for card in observation.viewer_deck]
    probabilistic_gain = 0.0
    for row, gain in row_gains.items():
        if row in guaranteed_rows:
            probabilistic_gain = max(probabilistic_gain, float(gain))
            continue
        matching_sources = sum(
            row in _horn_source_rows(definition) for definition in deck_definitions
        )
        if matching_sources <= 0:
            continue
        probabilistic_gain = max(
            probabilistic_gain,
            gain
            * _draw_any_probability(
                population_size=len(deck_definitions),
                success_count=matching_sources,
                draws=draws,
            ),
        )
    return max(guaranteed_gain, probabilistic_gain)


def projected_weather_loss(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None,
    active_weather_rows: tuple[Row, ...],
) -> int:
    context = BoardProjectionContext(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
        replacement_cards=replacement_cards,
        active_weather_rows=active_weather_rows,
    )
    current_board = context.board()
    total_loss = 0
    current_weather_rows = set(context.active_weather_rows)
    for row in Row:
        if row in current_weather_rows:
            continue
        forced_board = BoardProjectionContext(
            observation=observation,
            card_registry=card_registry,
            projected_cards=projected_cards,
            replacement_cards=replacement_cards,
            active_weather_rows=tuple(
                sorted(
                    current_weather_rows | {row},
                    key=lambda value: value.value,
                )
            ),
        ).board()
        total_loss += current_board.viewer_score - forced_board.viewer_score
    return total_loss


def projected_scorch_loss(
    rows: Iterable[ProjectedRowState],
    *,
    threshold: int = DEFAULT_FEATURE_POLICY.scorch_threshold,
) -> int:
    strengths = [strength for row in rows for strength in row.scorchable_unit_strengths]
    if not strengths:
        return 0
    highest = max(strengths)
    if highest < threshold:
        return 0
    return sum(strength for strength in strengths if strength == highest)


def projected_synergy_value(
    remaining_hand: list[CardDefinition],
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None,
) -> int:
    context = BoardProjectionContext(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
        replacement_cards=replacement_cards,
    )
    viewer_cards = [
        card.definition for row in Row for card in context.cards_for(context.viewer.player_id, row)
    ]
    hand_bond = Counter(
        definition.bond_group for definition in remaining_hand if definition.bond_group is not None
    )
    hand_muster = Counter(
        definition.muster_group
        for definition in remaining_hand
        if definition.muster_group is not None
    )
    board_bond_groups = {
        definition.bond_group for definition in viewer_cards if definition.bond_group is not None
    }
    board_muster_groups = {
        definition.muster_group
        for definition in viewer_cards
        if definition.muster_group is not None
    }
    synergy = sum(count - 1 for count in hand_bond.values() if count > 1)
    synergy += sum(count - 1 for count in hand_muster.values() if count > 1)
    synergy += sum(definition.bond_group in board_bond_groups for definition in remaining_hand)
    synergy += sum(definition.muster_group in board_muster_groups for definition in remaining_hand)
    if any(AbilityKind.MEDIC in definition.ability_kinds for definition in remaining_hand):
        synergy += max(
            (
                card_registry.get(card.definition_id).base_strength
                for card in context.viewer.discard
                if (
                    card_registry.get(card.definition_id).card_type == CardType.UNIT
                    and not card_registry.get(card.definition_id).is_hero
                )
            ),
            default=0,
        )
    return synergy


def projected_future_hand_value(
    definitions: list[CardDefinition],
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    board: PublicBoardProjection,
) -> int:
    """Estimate the quality of the hand that remains after a play.

    This intentionally values latent tactical text, not just printed strength.
    Holding a card with stored option value, such as a row-Scorch unit, should
    usually be worth more than holding an otherwise identical vanilla unit.
    """

    return sum(
        projected_future_card_value(
            definition,
            observation=observation,
            card_registry=card_registry,
            board=board,
        )
        for definition in definitions
    )


def projected_held_unit_tactical_reserve_value(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    board: PublicBoardProjection,
) -> int:
    """Estimate deterministic tactical value preserved by holding a unit card.

    This helper is intentionally narrow. It is not a generic latent-value
    engine. It only covers cases where a unit's main value is visibly parked in
    delayed tactical text rather than its current printed body, and where that
    delayed value can already be estimated from the public board:

    - `UNIT_SCORCH_ROW` units such as Villentretenmerth
    - `UNIT_COMMANDERS_HORN` units such as Dandelion
    - `MORALE_BOOST` units such as Olaf
    - `BERSERKER` units when an allowed row already has active Mardroeme

    This keeps `projected_future_card_value()` grounded in deterministic,
    already-live reserve value rather than speculative future combo hopes.
    """

    reserve = 0
    if AbilityKind.UNIT_SCORCH_ROW in definition.ability_kinds:
        reserve += _projected_unit_row_scorch_reserve_value(
            definition,
            board=board,
        )
    if AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds:
        reserve += _projected_unit_horn_reserve_value(
            definition,
            board=board,
        )
    if AbilityKind.MORALE_BOOST in definition.ability_kinds:
        reserve += _projected_morale_boost_reserve_value(
            definition,
            board=board,
        )
    if AbilityKind.BERSERKER in definition.ability_kinds:
        reserve += _projected_berserker_transform_reserve_value(
            definition,
            observation=observation,
            card_registry=card_registry,
        )
    return reserve


def projected_avenger_value(
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None,
) -> int:
    """Estimate delayed value still parked on the board via Avenger units.

    Avenger does not change the board immediately when played, but it does
    store visible future board value. We model that reserve conservatively as
    the strength delta between the current Avenger body and the unit it will
    summon when destroyed.

    In the final round there is no future-round conversion left to preserve, so
    this latent reserve should not be valued unless we later add explicit
    same-round self-trigger modeling.
    """

    if observation.public_state.round_number >= 3:
        return 0

    context = BoardProjectionContext(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
        replacement_cards=replacement_cards,
    )
    total = 0
    for row in Row:
        for card in context.cards_for(context.viewer.player_id, row):
            definition = card.definition
            if (
                definition.card_type != CardType.UNIT
                or AbilityKind.AVENGER not in definition.ability_kinds
                or definition.avenger_summon_definition_id is None
            ):
                continue
            summoned = card_registry.get(definition.avenger_summon_definition_id)
            total += max(0, summoned.base_strength - definition.base_strength)
    return total


def _horn_source_rows(definition: CardDefinition) -> tuple[Row, ...]:
    if (
        AbilityKind.COMMANDERS_HORN not in definition.ability_kinds
        and AbilityKind.UNIT_COMMANDERS_HORN not in definition.ability_kinds
    ):
        return ()
    return definition.allowed_rows if definition.allowed_rows else tuple(Row)


def _draw_any_probability(
    *,
    population_size: int,
    success_count: int,
    draws: int,
) -> float:
    if population_size <= 0 or success_count <= 0 or draws <= 0:
        return 0.0
    resolved_draws = min(population_size, draws)
    if success_count >= population_size:
        return 1.0
    misses = population_size - success_count
    if resolved_draws > misses:
        return 1.0
    return 1.0 - (comb(misses, resolved_draws) / comb(population_size, resolved_draws))


def _projected_unit_row_scorch_reserve_value(
    definition: CardDefinition,
    *,
    board: PublicBoardProjection,
) -> int:
    best_live_swing = 0
    for row in definition.allowed_rows:
        viewer_row = next(
            projected_row for projected_row in board.viewer_rows if projected_row.row == row
        )
        opponent_row = next(
            projected_row for projected_row in board.opponent_rows if projected_row.row == row
        )
        row_total = (
            viewer_row.effective_strength
            + opponent_row.effective_strength
            + definition.base_strength
        )
        if row_total < DEFAULT_FEATURE_POLICY.scorch_threshold:
            continue
        row_strengths = [
            *viewer_row.scorchable_unit_strengths,
            *opponent_row.scorchable_unit_strengths,
        ]
        if not row_strengths:
            continue
        highest = max(row_strengths)
        viewer_loss = sum(
            strength for strength in viewer_row.scorchable_unit_strengths if strength == highest
        )
        opponent_gain = sum(
            strength for strength in opponent_row.scorchable_unit_strengths if strength == highest
        )
        best_live_swing = max(best_live_swing, opponent_gain - viewer_loss)
    return max(best_live_swing, max(1, definition.base_strength // 2))


def _projected_unit_horn_reserve_value(
    definition: CardDefinition,
    *,
    board: PublicBoardProjection,
) -> int:
    return _max_allowed_row_value(
        definition,
        board=board,
        row_value=lambda row: row.non_hero_effective_strength,
        require_inactive_horn=True,
    )


def _projected_morale_boost_reserve_value(
    definition: CardDefinition,
    *,
    board: PublicBoardProjection,
) -> int:
    return _max_allowed_row_value(
        definition,
        board=board,
        row_value=lambda row: row.non_hero_unit_count,
    )


def _max_allowed_row_value(
    definition: CardDefinition,
    *,
    board: PublicBoardProjection,
    row_value: Callable[[ProjectedRowState], int],
    require_inactive_horn: bool = False,
) -> int:
    return max(
        (
            row_value(row)
            for row in board.viewer_rows
            if row.row in definition.allowed_rows
            and row.non_hero_unit_count > 0
            and (not require_inactive_horn or not row.horn_active)
        ),
        default=0,
    )


def _projected_berserker_transform_reserve_value(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
) -> int:
    if definition.transforms_into_definition_id is None:
        return 0

    viewer_side = viewer_public(observation).player_id
    cards = list(
        merged_projected_battlefield_cards(
            observation,
            card_registry=card_registry,
            projected_cards=(),
        )
    )
    if not any(
        projected_row_has_active_mardroeme(
            cards,
            battlefield_side=viewer_side,
            row=row,
        )
        for row in definition.allowed_rows
    ):
        return 0

    transformed = card_registry.get(definition.transforms_into_definition_id)
    return max(0, transformed.base_strength - definition.base_strength)
