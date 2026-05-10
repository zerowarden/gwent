from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.baseline.projection.context import (
    PublicPlayerContext,
    active_weather_rows,
    visible_battlefield_cards,
)
from gwent_engine.ai.baseline.projection.models import (
    ProjectedRowState,
    PublicBoardProjection,
    ScorchImpact,
)
from gwent_engine.ai.observations import (
    ObservedCard,
    PlayerObservation,
)
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.ids import PlayerId
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True, slots=True)
class ProjectedBattlefieldCard:
    definition: CardDefinition
    owner: PlayerId
    battlefield_side: PlayerId
    row: Row


@dataclass(frozen=True)
class BoardProjectionContext(PublicPlayerContext):
    """Bundle the deterministic public board inputs for one projection pass.

    The old board helpers passed the same `observation`, registry, projected
    cards, replacement cards, and weather rows through every call. This context
    keeps that bundle in one place so the board subsystem reads as a coherent
    unit rather than a long chain of parameter plumbing.
    """

    observation: PlayerObservation
    card_registry: CardRegistry
    projected_cards: tuple[ProjectedBattlefieldCard, ...] = ()
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None = None
    active_weather_rows: tuple[Row, ...] = ()

    @cached_property
    def visible_battlefield_cards(self) -> tuple[ObservedCard, ...]:
        return visible_battlefield_cards(self.observation)

    @cached_property
    def active_weather_row_set(self) -> frozenset[Row]:
        return frozenset(self.active_weather_rows)

    @cached_property
    def horn_rows(self) -> frozenset[tuple[PlayerId, Row]]:
        horn_rows: set[tuple[PlayerId, Row]] = set()
        for player in self.observation.public_state.players:
            if player.leader.horn_row is not None:
                horn_rows.add((player.player_id, player.leader.horn_row))
            for row in Row:
                for card in self.cards_for(player.player_id, row):
                    if AbilityKind.UNIT_COMMANDERS_HORN in card.definition.ability_kinds:
                        horn_rows.add((player.player_id, row))
                    if (
                        card.definition.card_type == CardType.SPECIAL
                        and special_ability_kind(card.definition) == AbilityKind.COMMANDERS_HORN
                    ):
                        horn_rows.add((player.player_id, row))
        return frozenset(horn_rows)

    def board(self) -> PublicBoardProjection:
        viewer_rows = self._rows_for(self.viewer.player_id)
        opponent_rows = self._rows_for(self.opponent.player_id)
        return PublicBoardProjection(
            viewer_score=sum(row.effective_strength for row in viewer_rows),
            opponent_score=sum(row.effective_strength for row in opponent_rows),
            viewer_rows=viewer_rows,
            opponent_rows=opponent_rows,
            active_weather_rows=self.active_weather_rows,
        )

    def cards_for(
        self,
        battlefield_side: PlayerId,
        row: Row,
    ) -> tuple[ProjectedBattlefieldCard, ...]:
        if self.replacement_cards is not None:
            return tuple(
                card
                for card in self.replacement_cards
                if card.battlefield_side == battlefield_side and card.row == row
            )
        cards = [
            ProjectedBattlefieldCard(
                definition=self.card_registry.get(card.definition_id),
                owner=card.owner,
                battlefield_side=card.battlefield_side or battlefield_side,
                row=row,
            )
            for card in self.visible_battlefield_cards
            if card.battlefield_side == battlefield_side and card.row == row
        ]
        cards.extend(
            card
            for card in self.projected_cards
            if card.battlefield_side == battlefield_side and card.row == row
        )
        return tuple(cards)

    def horn_active_for_row(
        self,
        battlefield_side: PlayerId,
        row: Row,
    ) -> bool:
        player = next(
            player
            for player in self.observation.public_state.players
            if player.player_id == battlefield_side
        )
        if player.leader.horn_row == row:
            return True
        for card in self.cards_for(battlefield_side, row):
            definition = card.definition
            if AbilityKind.UNIT_COMMANDERS_HORN in definition.ability_kinds:
                return True
            if (
                definition.card_type == CardType.SPECIAL
                and special_ability_kind(definition) == AbilityKind.COMMANDERS_HORN
            ):
                return True
        return False

    def _rows_for(
        self,
        battlefield_side: PlayerId,
    ) -> tuple[ProjectedRowState, ProjectedRowState, ProjectedRowState]:
        rows = tuple(
            _row_projection(
                row,
                self.cards_for(battlefield_side, row),
                weathered=row in self.active_weather_row_set,
                horn_active=self.horn_active_for_row(battlefield_side, row),
            )
            for row in Row
        )
        return (rows[0], rows[1], rows[2])


def current_public_board_projection(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
) -> PublicBoardProjection:
    return BoardProjectionContext(
        observation=observation,
        card_registry=card_registry,
        active_weather_rows=active_weather_rows(observation),
    ).board()


def current_public_scorch_impact(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
) -> ScorchImpact:
    return scorch_impact_from_board(
        current_public_board_projection(
            observation,
            card_registry=card_registry,
        )
    )


def scorch_impact_from_board(
    board: PublicBoardProjection,
    *,
    threshold: int = DEFAULT_FEATURE_POLICY.scorch_threshold,
) -> ScorchImpact:
    viewer_strengths = [
        strength for row in board.viewer_rows for strength in row.scorchable_unit_strengths
    ]
    opponent_strengths = [
        strength for row in board.opponent_rows for strength in row.scorchable_unit_strengths
    ]
    all_strengths = [*viewer_strengths, *opponent_strengths]
    if not all_strengths:
        return ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=0)
    highest = max(all_strengths)
    if highest < threshold:
        return ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=0)
    return ScorchImpact(
        viewer_strength_lost=sum(strength for strength in viewer_strengths if strength == highest),
        opponent_strength_lost=sum(
            strength for strength in opponent_strengths if strength == highest
        ),
    )


def board_projection(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None = None,
    active_weather_rows: tuple[Row, ...],
) -> PublicBoardProjection:
    return BoardProjectionContext(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
        replacement_cards=replacement_cards,
        active_weather_rows=active_weather_rows,
    ).board()


def _row_projection(
    row: Row,
    cards: tuple[ProjectedBattlefieldCard, ...],
    *,
    weathered: bool,
    horn_active: bool,
) -> ProjectedRowState:
    morale_count = sum(
        AbilityKind.MORALE_BOOST in card.definition.ability_kinds
        for card in cards
        if card.definition.card_type == CardType.UNIT
    )
    bond_counts = Counter(
        card.definition.bond_group
        for card in cards
        if (
            card.definition.card_type == CardType.UNIT
            and AbilityKind.TIGHT_BOND in card.definition.ability_kinds
            and card.definition.bond_group is not None
        )
    )
    effective_strength = 0
    non_hero_effective_strength = 0
    non_hero_unit_count = 0
    scorchable_unit_strengths: list[int] = []
    for card in cards:
        definition = card.definition
        if definition.card_type != CardType.UNIT:
            continue
        strength = definition.base_strength
        if weathered and not definition.is_hero:
            strength = 1
        if AbilityKind.TIGHT_BOND in definition.ability_kinds and definition.bond_group is not None:
            strength *= max(1, bond_counts[definition.bond_group])
        morale_bonus = morale_count - (
            1 if AbilityKind.MORALE_BOOST in definition.ability_kinds else 0
        )
        strength += max(0, morale_bonus)
        if horn_active and not definition.is_hero:
            strength *= 2
        effective_strength += strength
        if not definition.is_hero:
            non_hero_effective_strength += strength
            non_hero_unit_count += 1
            scorchable_unit_strengths.append(strength)
    return ProjectedRowState(
        row=row,
        effective_strength=effective_strength,
        non_hero_effective_strength=non_hero_effective_strength,
        non_hero_unit_count=non_hero_unit_count,
        horn_active=horn_active,
        scorchable_unit_strengths=tuple(scorchable_unit_strengths),
    )


def effective_card_strength(
    cards: list[ProjectedBattlefieldCard],
    index: int,
    *,
    weather_rows: set[Row],
    horn_rows: set[tuple[PlayerId, Row]],
) -> int:
    card = cards[index]
    definition = card.definition
    if definition.card_type != CardType.UNIT:
        return 0
    same_row_cards = [
        candidate
        for candidate in cards
        if candidate.battlefield_side == card.battlefield_side and candidate.row == card.row
    ]
    morale_count = sum(
        AbilityKind.MORALE_BOOST in candidate.definition.ability_kinds
        for candidate in same_row_cards
        if candidate.definition.card_type == CardType.UNIT
    )
    bond_count = sum(
        candidate.definition.bond_group == definition.bond_group
        for candidate in same_row_cards
        if (
            candidate.definition.card_type == CardType.UNIT
            and AbilityKind.TIGHT_BOND in candidate.definition.ability_kinds
            and definition.bond_group is not None
        )
    )
    strength = definition.base_strength
    if card.row in weather_rows and not definition.is_hero:
        strength = 1
    if AbilityKind.TIGHT_BOND in definition.ability_kinds and definition.bond_group is not None:
        strength *= max(1, bond_count)
    morale_bonus = morale_count - (1 if AbilityKind.MORALE_BOOST in definition.ability_kinds else 0)
    strength += max(0, morale_bonus)
    if (card.battlefield_side, card.row) in horn_rows and not definition.is_hero:
        strength *= 2
    return strength


def horn_rows(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None = None,
) -> set[tuple[PlayerId, Row]]:
    return set(
        BoardProjectionContext(
            observation=observation,
            card_registry=card_registry,
            projected_cards=projected_cards,
            replacement_cards=replacement_cards,
        ).horn_rows
    )
