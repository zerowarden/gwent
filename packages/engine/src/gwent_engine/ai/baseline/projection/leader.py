from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.baseline.projection.battlefield import merged_projected_battlefield_cards
from gwent_engine.ai.baseline.projection.board import (
    ProjectedBattlefieldCard,
    board_projection,
    effective_card_strength,
    horn_rows,
)
from gwent_engine.ai.baseline.projection.future_value import projected_future_card_value
from gwent_engine.ai.baseline.projection.models import (
    LeaderActionProjection,
)
from gwent_engine.ai.baseline.projection.resolver_context import (
    ProjectionResolverContext,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, LeaderAbilityKind, Row
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.battlefield_effects import is_weather_ability, weather_rows_for
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True)
class LeaderProjectionResolver(ProjectionResolverContext):
    """Project one leader activation into a deterministic public result.

    This keeps leader-specific branching contained in one place and gives the
    heavier leader projections a shared view of:
    - current board state
    - current weather rows
    - viewer/opponent public state
    - the current leader definition

    The resolver intentionally stays small. It is not a general projection
    engine; it only owns leader-action projection.
    """

    action: UseLeaderAbilityAction
    leader_registry: LeaderRegistry | None

    @cached_property
    def leader_definition(self) -> LeaderDefinition | None:
        if self.leader_registry is None:
            return None
        return self.leader_registry.get(self.viewer.leader.leader_id)

    @cached_property
    def base_cards(self) -> tuple[ProjectedBattlefieldCard, ...]:
        return merged_projected_battlefield_cards(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
        )

    def resolve(self) -> LeaderActionProjection | None:
        if self.leader_definition is None:
            return None

        projection: LeaderActionProjection | None
        match self.leader_definition.ability_kind:
            case LeaderAbilityKind.CLEAR_WEATHER:
                projection = self._project_clear_weather()
            case LeaderAbilityKind.PLAY_WEATHER_FROM_DECK:
                projection = self._project_play_weather_from_deck()
            case LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK:
                projection = self._project_discard_and_choose_from_deck()
            case LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND:
                projection = self._project_return_card_from_own_discard_to_hand()
            case LeaderAbilityKind.HORN_OWN_ROW:
                projection = self._project_horn_own_row()
            case LeaderAbilityKind.SCORCH_OPPONENT_ROW:
                projection = self._project_scorch_opponent_row()
            case LeaderAbilityKind.OPTIMIZE_AGILE_ROWS:
                projection = self._project_optimize_agile_rows()
            case LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND:
                projection = self._project_take_card_from_opponent_discard_to_hand()
            case _:
                projection = None
        return projection

    def _noop(
        self,
        *,
        ability_kind: LeaderAbilityKind,
        minimum_row_total: int | None = None,
        opponent_row_total: int | None = None,
        live_targets: int = 0,
        affected_row: Row | None = None,
        weather_rows_changed: tuple[Row, ...] = (),
        moved_units: int = 0,
    ) -> LeaderActionProjection:
        return LeaderActionProjection(
            ability_kind=ability_kind,
            projected_net_board_swing=0,
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=True,
            minimum_row_total=minimum_row_total,
            opponent_row_total=opponent_row_total,
            live_targets=live_targets,
            affected_row=affected_row,
            weather_rows_changed=weather_rows_changed,
            moved_units=moved_units,
        )

    def _project_clear_weather(self) -> LeaderActionProjection:
        board_after = board_projection(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            active_weather_rows=(),
        )
        projected_swing = board_after.score_gap - self.current_board.score_gap
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.CLEAR_WEATHER,
            projected_net_board_swing=projected_swing,
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=projected_swing == 0,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=0,
            weather_rows_changed=self.current_weather_rows,
        )

    def _project_play_weather_from_deck(self) -> LeaderActionProjection:
        assert self.leader_definition is not None
        weather_kind = self._weather_ability_from_action()
        if weather_kind is None:
            return self._noop(ability_kind=LeaderAbilityKind.PLAY_WEATHER_FROM_DECK)

        weather_rows = weather_rows_for(weather_kind)
        board_after = board_projection(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            active_weather_rows=tuple(
                sorted(
                    set(self.current_weather_rows) | set(weather_rows),
                    key=lambda row: row.value,
                )
            ),
        )
        projected_swing = board_after.score_gap - self.current_board.score_gap
        changed_rows = tuple(row for row in weather_rows if row not in self.current_weather_rows)
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.PLAY_WEATHER_FROM_DECK,
            projected_net_board_swing=projected_swing,
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=projected_swing == 0,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=0,
            affected_row=weather_rows[0] if len(weather_rows) == 1 else None,
            weather_rows_changed=changed_rows,
        )

    def _project_discard_and_choose_from_deck(self) -> LeaderActionProjection:
        assert self.leader_definition is not None
        hand_cards = self.observation.viewer_hand
        deck_cards = self.observation.viewer_deck
        if (
            len(hand_cards) < self.leader_definition.hand_discard_count
            or len(deck_cards) < self.leader_definition.deck_pick_count
        ):
            return self._noop(ability_kind=LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK)

        discard_values = sorted(
            projected_future_card_value(
                self.card_registry.get(card.definition_id),
                observation=self.observation,
                card_registry=self.card_registry,
            )
            for card in hand_cards
        )
        pick_values = sorted(
            (
                projected_future_card_value(
                    self.card_registry.get(card.definition_id),
                    observation=self.observation,
                    card_registry=self.card_registry,
                )
                for card in deck_cards
            ),
            reverse=True,
        )
        discarded_value = sum(discard_values[: self.leader_definition.hand_discard_count])
        picked_value = sum(pick_values[: self.leader_definition.deck_pick_count])
        hand_count_delta = (
            self.leader_definition.deck_pick_count - self.leader_definition.hand_discard_count
        )
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK,
            projected_net_board_swing=0,
            projected_hand_value_delta=picked_value - discarded_value,
            viewer_hand_count_delta=hand_count_delta,
            is_noop=False,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=len(hand_cards) + len(deck_cards),
        )

    def _project_return_card_from_own_discard_to_hand(self) -> LeaderActionProjection:
        discard_cards = tuple(
            card
            for card in self.viewer.discard
            if _is_leader_discard_retrieval_target(self.card_registry.get(card.definition_id))
        )
        if not discard_cards:
            return self._noop(ability_kind=LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND)

        best_value = max(
            projected_future_card_value(
                self.card_registry.get(card.definition_id),
                observation=self.observation,
                card_registry=self.card_registry,
            )
            for card in discard_cards
        )
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND,
            projected_net_board_swing=0,
            projected_hand_value_delta=best_value,
            viewer_hand_count_delta=1,
            is_noop=False,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=len(discard_cards),
        )

    def _project_horn_own_row(self) -> LeaderActionProjection:
        affected_row = self.leader_definition.affected_row if self.leader_definition else None
        if affected_row is None:
            return self._noop(ability_kind=LeaderAbilityKind.HORN_OWN_ROW)

        viewer_row = next(row for row in self.current_board.viewer_rows if row.row == affected_row)
        projected_swing = 0 if viewer_row.horn_active else viewer_row.non_hero_effective_strength
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.HORN_OWN_ROW,
            projected_net_board_swing=projected_swing,
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=projected_swing == 0,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=viewer_row.non_hero_unit_count,
            affected_row=affected_row,
        )

    def _project_scorch_opponent_row(self) -> LeaderActionProjection:
        affected_row = self.leader_definition.affected_row if self.leader_definition else None
        minimum_row_total = (
            self.leader_definition.minimum_opponent_row_total if self.leader_definition else 0
        )
        if affected_row is None:
            return self._scorch_opponent_row_noop(
                minimum_row_total=minimum_row_total,
                affected_row=affected_row,
            )

        cards = list(self.base_cards)
        row_indexes = [
            index
            for index, card in enumerate(cards)
            if card.battlefield_side == self.opponent.player_id and card.row == affected_row
        ]
        if not row_indexes:
            return self._scorch_opponent_row_noop(
                minimum_row_total=minimum_row_total,
                opponent_row_total=0,
                affected_row=affected_row,
            )

        row_total = sum(self._effective_strength(cards, index) for index in row_indexes)
        if row_total < minimum_row_total:
            return self._scorch_opponent_row_noop(
                minimum_row_total=minimum_row_total,
                opponent_row_total=row_total,
                affected_row=affected_row,
            )

        strengths = {
            index: self._effective_strength(cards, index)
            for index in row_indexes
            if cards[index].definition.card_type == CardType.UNIT
            and not cards[index].definition.is_hero
        }
        if not strengths:
            return self._scorch_opponent_row_noop(
                minimum_row_total=minimum_row_total,
                opponent_row_total=row_total,
                affected_row=affected_row,
            )

        highest = max(strengths.values())
        destroyed_strengths = [strength for strength in strengths.values() if strength == highest]
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.SCORCH_OPPONENT_ROW,
            projected_net_board_swing=sum(destroyed_strengths),
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=False,
            minimum_row_total=minimum_row_total,
            opponent_row_total=row_total,
            live_targets=len(destroyed_strengths),
            affected_row=affected_row,
        )

    def _scorch_opponent_row_noop(
        self,
        *,
        minimum_row_total: int,
        opponent_row_total: int | None = None,
        affected_row: Row | None,
    ) -> LeaderActionProjection:
        return self._noop(
            ability_kind=LeaderAbilityKind.SCORCH_OPPONENT_ROW,
            minimum_row_total=minimum_row_total,
            opponent_row_total=opponent_row_total,
            affected_row=affected_row,
        )

    def _project_optimize_agile_rows(self) -> LeaderActionProjection:
        cards = list(self.base_cards)
        moved_units = 0
        for index, card in enumerate(tuple(cards)):
            definition = card.definition
            if (
                definition.card_type != CardType.UNIT
                or AbilityKind.AGILE not in definition.ability_kinds
                or len(definition.allowed_rows) < 2
            ):
                continue
            best_row = card.row
            best_strength = self._effective_strength(cards, index)
            for candidate_row in definition.allowed_rows:
                if candidate_row == card.row:
                    continue
                simulated = list(cards)
                simulated[index] = ProjectedBattlefieldCard(
                    definition=definition,
                    owner=card.owner,
                    battlefield_side=card.battlefield_side,
                    row=candidate_row,
                )
                candidate_strength = self._effective_strength(simulated, index)
                if candidate_strength > best_strength:
                    best_strength = candidate_strength
                    best_row = candidate_row
            if best_row != card.row:
                cards[index] = ProjectedBattlefieldCard(
                    definition=definition,
                    owner=card.owner,
                    battlefield_side=card.battlefield_side,
                    row=best_row,
                )
                moved_units += 1

        board_after = board_projection(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            replacement_cards=tuple(cards),
            active_weather_rows=self.current_weather_rows,
        )
        projected_swing = board_after.score_gap - self.current_board.score_gap
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.OPTIMIZE_AGILE_ROWS,
            projected_net_board_swing=projected_swing,
            projected_hand_value_delta=0,
            viewer_hand_count_delta=0,
            is_noop=projected_swing == 0,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=moved_units,
            moved_units=moved_units,
        )

    def _project_take_card_from_opponent_discard_to_hand(self) -> LeaderActionProjection:
        opponent_discard = tuple(
            card
            for card in self.opponent.discard
            if _is_leader_discard_retrieval_target(self.card_registry.get(card.definition_id))
        )
        if not opponent_discard:
            return self._noop(
                ability_kind=LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND
            )

        best_value = max(
            projected_future_card_value(
                self.card_registry.get(card.definition_id),
                observation=self.observation,
                card_registry=self.card_registry,
            )
            for card in opponent_discard
        )
        return LeaderActionProjection(
            ability_kind=LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND,
            projected_net_board_swing=0,
            projected_hand_value_delta=best_value,
            viewer_hand_count_delta=1,
            is_noop=False,
            minimum_row_total=None,
            opponent_row_total=None,
            live_targets=len(opponent_discard),
        )

    def _effective_strength(
        self,
        cards: list[ProjectedBattlefieldCard],
        index: int,
    ) -> int:
        return effective_card_strength(
            cards,
            index,
            weather_rows=set(self.current_weather_rows),
            horn_rows=horn_rows(
                self.observation,
                card_registry=self.card_registry,
                projected_cards=(),
                replacement_cards=tuple(cards),
            ),
        )

    def _weather_ability_from_action(self) -> AbilityKind | None:
        if self.leader_definition is None:
            return None
        if self.action.target_card_instance_id is not None:
            chosen_card = next(
                (
                    card
                    for card in self.observation.viewer_deck
                    if card.instance_id == self.action.target_card_instance_id
                ),
                None,
            )
            if chosen_card is not None:
                definition = self.card_registry.get(chosen_card.definition_id)
                if definition.card_type == CardType.SPECIAL:
                    return special_ability_kind(definition)
        weather_ability_kind = self.leader_definition.weather_ability_kind
        if weather_ability_kind is None or not is_weather_ability(weather_ability_kind):
            return None
        return weather_ability_kind


def project_leader_action(
    action: UseLeaderAbilityAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> LeaderActionProjection | None:
    return LeaderProjectionResolver(
        action=action,
        observation=observation,
        card_registry=card_registry,
        leader_registry=leader_registry,
    ).resolve()


def _is_leader_discard_retrieval_target(definition: CardDefinition) -> bool:
    return definition.card_type == CardType.UNIT and not definition.is_hero
