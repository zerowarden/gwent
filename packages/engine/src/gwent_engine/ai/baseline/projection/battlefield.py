from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.baseline.projection.board import (
    BoardProjectionContext,
    ProjectedBattlefieldCard,
    board_projection,
    effective_card_strength,
    scorch_impact_from_board,
)
from gwent_engine.ai.baseline.projection.context import (
    active_weather_rows,
    opponent_public,
    visible_battlefield_cards,
)
from gwent_engine.ai.baseline.projection.models import PublicBoardProjection, ScorchImpact
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.ids import PlayerId
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True)
class BattlefieldProjectionResolver:
    """Resolve deterministic public battlefield mutations for one projected play.

    This is intentionally a small projection-time sub-engine. It owns only the
    visible battlefield mutations that can be derived without hidden
    information:

    - global Scorch
    - row Scorch
    - Berserker/Mardroeme transformations
    - Avenger replacement summons from immediate destruction
    """

    observation: PlayerObservation
    card_registry: CardRegistry
    projected_cards: tuple[ProjectedBattlefieldCard, ...] = ()

    @cached_property
    def weather_rows(self) -> tuple[Row, ...]:
        return active_weather_rows(self.observation)

    @cached_property
    def opponent_side(self) -> PlayerId:
        return opponent_public(self.observation).player_id

    def resolve(
        self,
        *,
        played_definition: CardDefinition,
        played_row: Row | None,
    ) -> tuple[tuple[ProjectedBattlefieldCard, ...], ScorchImpact]:
        cards = list(self.merged_cards())
        scorch_impact = ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=0)
        match played_definition.card_type:
            case CardType.UNIT:
                if (
                    AbilityKind.UNIT_SCORCH_ROW in played_definition.ability_kinds
                    and played_row is not None
                ):
                    cards = self.apply_row_scorch(cards, played_row=played_row)
                if (
                    AbilityKind.BERSERKER in played_definition.ability_kinds
                    and played_row is not None
                    and projected_row_has_active_mardroeme(
                        cards,
                        battlefield_side=self.observation.viewer_player_id,
                        row=played_row,
                    )
                ):
                    cards = self.apply_berserker_transformations(
                        cards,
                        battlefield_side=self.observation.viewer_player_id,
                        row=played_row,
                    )
                if (
                    AbilityKind.MARDROEME in played_definition.ability_kinds
                    and played_row is not None
                ):
                    cards = self.apply_berserker_transformations(
                        cards,
                        battlefield_side=self.observation.viewer_player_id,
                        row=played_row,
                    )
            case CardType.SPECIAL:
                match special_ability_kind(played_definition):
                    case AbilityKind.SCORCH:
                        scorch_impact = scorch_impact_from_board(self.current_board())
                        cards = self.apply_global_scorch(cards)
                    case AbilityKind.MARDROEME if played_row is not None:
                        cards = self.apply_berserker_transformations(
                            cards,
                            battlefield_side=self.observation.viewer_player_id,
                            row=played_row,
                        )
                    case _:
                        pass
            case _:
                pass
        return tuple(cards), scorch_impact

    def merged_cards(self) -> tuple[ProjectedBattlefieldCard, ...]:
        current_cards = [
            ProjectedBattlefieldCard(
                definition=self.card_registry.get(card.definition_id),
                owner=card.owner,
                battlefield_side=card.battlefield_side or self.observation.viewer_player_id,
                row=card.row or Row.CLOSE,
            )
            for card in visible_battlefield_cards(self.observation)
            if card.row is not None and card.battlefield_side is not None
        ]
        current_cards.extend(self.projected_cards)
        return tuple(current_cards)

    def current_board(self) -> PublicBoardProjection:
        return board_projection(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=self.projected_cards,
            replacement_cards=None,
            active_weather_rows=self.weather_rows,
        )

    def effect_context(
        self,
        cards: list[ProjectedBattlefieldCard],
    ) -> BoardProjectionContext:
        return BoardProjectionContext(
            observation=self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            replacement_cards=tuple(cards),
            active_weather_rows=self.weather_rows,
        )

    def apply_global_scorch(
        self,
        cards: list[ProjectedBattlefieldCard],
    ) -> list[ProjectedBattlefieldCard]:
        context = self.effect_context(cards)
        strengths = {
            index: effective_card_strength(
                cards,
                index,
                weather_rows=set(context.active_weather_row_set),
                horn_rows=set(context.horn_rows),
            )
            for index in range(len(cards))
            if (
                cards[index].definition.card_type == CardType.UNIT
                and not cards[index].definition.is_hero
            )
        }
        if not strengths:
            return cards
        highest = max(strengths.values())
        if highest < DEFAULT_FEATURE_POLICY.scorch_threshold:
            return cards
        destroyed_indexes = {index for index, strength in strengths.items() if strength == highest}
        return self.resolve_destruction(cards, destroyed_indexes=destroyed_indexes)

    def apply_row_scorch(
        self,
        cards: list[ProjectedBattlefieldCard],
        *,
        played_row: Row,
    ) -> list[ProjectedBattlefieldCard]:
        row_indexes = [
            index
            for index, card in enumerate(cards)
            if card.battlefield_side == self.opponent_side and card.row == played_row
        ]
        if not row_indexes:
            return cards
        context = self.effect_context(cards)
        row_total = sum(
            effective_card_strength(
                cards,
                index,
                weather_rows=set(context.active_weather_row_set),
                horn_rows=set(context.horn_rows),
            )
            for index in row_indexes
        )
        if row_total < DEFAULT_FEATURE_POLICY.scorch_threshold:
            return cards
        strengths = {
            index: effective_card_strength(
                cards,
                index,
                weather_rows=set(context.active_weather_row_set),
                horn_rows=set(context.horn_rows),
            )
            for index in row_indexes
            if (
                cards[index].definition.card_type == CardType.UNIT
                and not cards[index].definition.is_hero
            )
        }
        if not strengths:
            return cards
        highest = max(strengths.values())
        destroyed_indexes = {index for index, strength in strengths.items() if strength == highest}
        return self.resolve_destruction(cards, destroyed_indexes=destroyed_indexes)

    def resolve_destruction(
        self,
        cards: list[ProjectedBattlefieldCard],
        *,
        destroyed_indexes: set[int],
    ) -> list[ProjectedBattlefieldCard]:
        remaining: list[ProjectedBattlefieldCard] = []
        summoned: list[ProjectedBattlefieldCard] = []
        for index, card in enumerate(cards):
            if index not in destroyed_indexes:
                remaining.append(card)
                continue
            definition = card.definition
            if (
                definition.card_type == CardType.UNIT
                and AbilityKind.AVENGER in definition.ability_kinds
                and definition.avenger_summon_definition_id is not None
            ):
                summoned.append(
                    ProjectedBattlefieldCard(
                        definition=self.card_registry.get(definition.avenger_summon_definition_id),
                        owner=card.owner,
                        battlefield_side=card.battlefield_side,
                        row=card.row,
                    )
                )
        remaining.extend(summoned)
        return remaining

    def apply_berserker_transformations(
        self,
        cards: list[ProjectedBattlefieldCard],
        *,
        battlefield_side: PlayerId,
        row: Row,
    ) -> list[ProjectedBattlefieldCard]:
        transformed: list[ProjectedBattlefieldCard] = []
        for card in cards:
            definition = card.definition
            if (
                card.battlefield_side == battlefield_side
                and card.row == row
                and definition.card_type == CardType.UNIT
                and AbilityKind.BERSERKER in definition.ability_kinds
                and definition.transforms_into_definition_id is not None
            ):
                transformed.append(
                    ProjectedBattlefieldCard(
                        definition=self.card_registry.get(definition.transforms_into_definition_id),
                        owner=card.owner,
                        battlefield_side=card.battlefield_side,
                        row=card.row,
                    )
                )
                continue
            transformed.append(card)
        return transformed


def resolve_projected_battlefield(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
    played_definition: CardDefinition,
    played_row: Row | None,
) -> tuple[tuple[ProjectedBattlefieldCard, ...], ScorchImpact]:
    return BattlefieldProjectionResolver(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
    ).resolve(
        played_definition=played_definition,
        played_row=played_row,
    )


def merged_projected_battlefield_cards(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    projected_cards: tuple[ProjectedBattlefieldCard, ...],
) -> tuple[ProjectedBattlefieldCard, ...]:
    return BattlefieldProjectionResolver(
        observation=observation,
        card_registry=card_registry,
        projected_cards=projected_cards,
    ).merged_cards()


def projected_row_has_active_mardroeme(
    cards: list[ProjectedBattlefieldCard],
    *,
    battlefield_side: PlayerId,
    row: Row,
) -> bool:
    return any(
        card.battlefield_side == battlefield_side
        and card.row == row
        and (
            AbilityKind.MARDROEME in card.definition.ability_kinds
            or (
                card.definition.card_type == CardType.SPECIAL
                and special_ability_kind(card.definition) == AbilityKind.MARDROEME
            )
        )
        for card in cards
    )
