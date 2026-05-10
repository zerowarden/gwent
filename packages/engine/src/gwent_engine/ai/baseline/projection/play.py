from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

from gwent_engine.ai.baseline.features import dead_card_penalty
from gwent_engine.ai.baseline.projection.battlefield import resolve_projected_battlefield
from gwent_engine.ai.baseline.projection.board import (
    ProjectedBattlefieldCard,
    board_projection,
)
from gwent_engine.ai.baseline.projection.context import (
    viewer_public,
)
from gwent_engine.ai.baseline.projection.future_value import (
    projected_avenger_value,
    projected_future_hand_value,
    projected_scorch_loss,
    projected_synergy_value,
    projected_weather_loss,
    reachable_horn_option_value,
)
from gwent_engine.ai.baseline.projection.models import (
    PlayActionProjection,
    ScorchImpact,
)
from gwent_engine.ai.baseline.projection.resolver_context import (
    ProjectionResolverContext,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import DEFAULT_FEATURE_POLICY, DEFAULT_PROJECTION_POLICY
from gwent_engine.ai.utils import viewer_hand_definition
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.rules.battlefield_effects import is_weather_ability, weather_rows_for
from gwent_engine.rules.row_effects import special_ability_kind


@dataclass(frozen=True)
class PlayProjectionResolver(ProjectionResolverContext):
    """Resolve one play action into a deterministic public play projection.

    This class keeps the play-specific flow together:
    - identify the played definition
    - build projected battlefield additions
    - resolve deterministic battlefield mutations
    - compare before/after board and future-value surfaces

    The future-value terms still live in the legacy module for now, so this
    resolver imports them lazily when needed. That keeps this extraction
    bounded to the play slice rather than coupling it to the later
    `future_value.py` split.
    """

    action: PlayCardAction
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None

    @cached_property
    def current_hand_definitions(self) -> list[CardDefinition]:
        return [self.card_registry.get(card.definition_id) for card in self.observation.viewer_hand]

    @cached_property
    def definition(self) -> CardDefinition | None:
        return viewer_hand_definition(
            self.action.card_instance_id,
            observation=self.observation,
            card_registry=self.card_registry,
            viewer_hand_definitions=self.viewer_hand_definitions,
        )

    @cached_property
    def remaining_hand(self) -> list[CardDefinition]:
        return list(
            remaining_hand_definitions(
                self.observation,
                self.card_registry,
                self.action.card_instance_id,
            )
        )

    def resolve(self) -> PlayActionProjection:
        current_horn_option_value = reachable_horn_option_value(
            self.current_board.viewer_rows,
            observation=self.observation,
            card_registry=self.card_registry,
            hand_definitions=self.current_hand_definitions,
            draw_count=0,
        )
        current_weather_loss = projected_weather_loss(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            replacement_cards=None,
            active_weather_rows=self.current_weather_rows,
        )
        current_scorch_loss = projected_scorch_loss(
            self.current_board.viewer_rows,
            threshold=DEFAULT_FEATURE_POLICY.scorch_threshold,
        )
        current_synergy_value = projected_synergy_value(
            self.current_hand_definitions,
            observation=self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            replacement_cards=None,
        )
        current_dead_card_penalty = dead_card_penalty(
            self.current_hand_definitions,
            active_weather_rows=self.current_weather_rows,
        )
        current_avenger_value = projected_avenger_value(
            observation=self.observation,
            card_registry=self.card_registry,
            projected_cards=(),
            replacement_cards=None,
        )

        if self.definition is None:
            return PlayActionProjection(
                current_score_gap=self.current_board.score_gap,
                viewer_score_after=self.current_board.viewer_score,
                opponent_score_after=self.current_board.opponent_score,
                projected_score_gap_after=self.current_board.score_gap,
                projected_net_board_swing=0,
                viewer_hand_count_after=self.viewer.hand_count,
                opponent_hand_count_after=self.opponent.hand_count,
                post_action_hand_value=0,
                horn_option_value_before=current_horn_option_value,
                horn_option_value_after=current_horn_option_value,
                horn_future_option_delta=0,
                projected_weather_loss=0,
                projected_scorch_loss=0,
                viewer_scorch_damage=0,
                opponent_scorch_damage=0,
                net_scorch_swing=0,
                projected_synergy_value=0,
                projected_dead_card_penalty=0,
                projected_avenger_value=0,
            )

        projected_cards: list[ProjectedBattlefieldCard] = []
        projected_weather_row_set = set(self.current_weather_rows)
        replacement_cards: tuple[ProjectedBattlefieldCard, ...] | None = None
        scorch_impact = ScorchImpact(viewer_strength_lost=0, opponent_strength_lost=0)
        viewer_hand_count_after = self.viewer.hand_count - 1
        opponent_hand_count_after = self.opponent.hand_count
        immediate_draw_count = 0

        if self.definition.card_type == CardType.UNIT:
            immediate_draw_count, viewer_hand_count_after = self._project_unit_play(
                self.definition,
                projected_cards,
                viewer_hand_count_after,
            )
        elif self.definition.card_type == CardType.SPECIAL:
            self._project_special_play(
                self.definition,
                projected_cards,
                projected_weather_row_set,
            )

        replacement_cards, scorch_impact = resolve_projected_battlefield(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=tuple(projected_cards),
            played_definition=self.definition,
            played_row=self.action.target_row,
        )

        resolved_weather_rows = tuple(sorted(projected_weather_row_set, key=lambda row: row.value))
        board_after = board_projection(
            self.observation,
            card_registry=self.card_registry,
            projected_cards=tuple(projected_cards),
            replacement_cards=replacement_cards,
            active_weather_rows=resolved_weather_rows,
        )
        horn_option_value_after = reachable_horn_option_value(
            board_after.viewer_rows,
            observation=self.observation,
            card_registry=self.card_registry,
            hand_definitions=self.remaining_hand,
            draw_count=immediate_draw_count,
        )

        return PlayActionProjection(
            current_score_gap=self.current_board.score_gap,
            viewer_score_after=board_after.viewer_score,
            opponent_score_after=board_after.opponent_score,
            projected_score_gap_after=board_after.score_gap,
            projected_net_board_swing=board_after.score_gap - self.current_board.score_gap,
            viewer_hand_count_after=viewer_hand_count_after,
            opponent_hand_count_after=opponent_hand_count_after,
            post_action_hand_value=projected_future_hand_value(
                self.remaining_hand,
                observation=self.observation,
                card_registry=self.card_registry,
                board=board_after,
            ),
            horn_option_value_before=current_horn_option_value,
            horn_option_value_after=horn_option_value_after,
            horn_future_option_delta=(horn_option_value_after - current_horn_option_value),
            projected_weather_loss=(
                projected_weather_loss(
                    self.observation,
                    card_registry=self.card_registry,
                    projected_cards=tuple(projected_cards),
                    replacement_cards=replacement_cards,
                    active_weather_rows=resolved_weather_rows,
                )
                - current_weather_loss
            ),
            projected_scorch_loss=(
                projected_scorch_loss(
                    board_after.viewer_rows,
                    threshold=DEFAULT_FEATURE_POLICY.scorch_threshold,
                )
                - current_scorch_loss
            ),
            viewer_scorch_damage=scorch_impact.viewer_strength_lost,
            opponent_scorch_damage=scorch_impact.opponent_strength_lost,
            net_scorch_swing=scorch_impact.net_swing,
            projected_synergy_value=(
                projected_synergy_value(
                    self.remaining_hand,
                    observation=self.observation,
                    card_registry=self.card_registry,
                    projected_cards=tuple(projected_cards),
                    replacement_cards=replacement_cards,
                )
                - current_synergy_value
            ),
            projected_dead_card_penalty=(
                dead_card_penalty(
                    self.remaining_hand,
                    active_weather_rows=resolved_weather_rows,
                )
                - current_dead_card_penalty
            ),
            projected_avenger_value=(
                projected_avenger_value(
                    observation=self.observation,
                    card_registry=self.card_registry,
                    projected_cards=tuple(projected_cards),
                    replacement_cards=replacement_cards,
                )
                - current_avenger_value
            ),
        )

    def _project_unit_play(
        self,
        definition: CardDefinition,
        projected_cards: list[ProjectedBattlefieldCard],
        viewer_hand_count_after: int,
    ) -> tuple[int, int]:
        row = self.action.target_row or definition.allowed_rows[0]
        battlefield_side = (
            self.opponent.player_id
            if AbilityKind.SPY in definition.ability_kinds
            else self.observation.viewer_player_id
        )
        projected_cards.append(
            ProjectedBattlefieldCard(
                definition=definition,
                owner=self.observation.viewer_player_id,
                battlefield_side=battlefield_side,
                row=row,
            )
        )
        immediate_draw_count = 0
        if AbilityKind.SPY in definition.ability_kinds:
            immediate_draw_count = reachable_spy_draw_count(self.observation)
            viewer_hand_count_after += immediate_draw_count
        muster_group = definition.resolved_musters_group
        if AbilityKind.MUSTER in definition.ability_kinds and muster_group is not None:
            projected_cards.extend(
                projected_muster_cards_from_viewer_deck(
                    self.observation,
                    card_registry=self.card_registry,
                    muster_group=muster_group,
                    owner=self.observation.viewer_player_id,
                    battlefield_side=battlefield_side,
                    row=row,
                )
            )
        if AbilityKind.MEDIC in definition.ability_kinds:
            revived_card = best_medic_revive(
                self.observation,
                card_registry=self.card_registry,
                battlefield_side=self.observation.viewer_player_id,
            )
            if revived_card is not None:
                projected_cards.append(revived_card)
                if AbilityKind.SPY in revived_card.definition.ability_kinds:
                    spy_draw_count = reachable_spy_draw_count(self.observation)
                    viewer_hand_count_after += spy_draw_count
                    immediate_draw_count = max(immediate_draw_count, spy_draw_count)
        return immediate_draw_count, viewer_hand_count_after

    def _project_special_play(
        self,
        definition: CardDefinition,
        projected_cards: list[ProjectedBattlefieldCard],
        projected_weather_row_set: set[Row],
    ) -> None:
        ability_kind = special_ability_kind(definition)
        match ability_kind:
            case AbilityKind.COMMANDERS_HORN | AbilityKind.MARDROEME:
                if self.action.target_row is not None:
                    projected_cards.append(
                        ProjectedBattlefieldCard(
                            definition=definition,
                            owner=self.observation.viewer_player_id,
                            battlefield_side=self.observation.viewer_player_id,
                            row=self.action.target_row,
                        )
                    )
            case kind if is_weather_ability(kind):
                projected_weather_row_set.update(weather_rows_for(kind))
            case AbilityKind.CLEAR_WEATHER:
                projected_weather_row_set.clear()
            case _:
                pass


def project_play_action(
    action: PlayCardAction,
    *,
    observation: PlayerObservation,
    card_registry: CardRegistry,
    viewer_hand_definitions: Mapping[CardInstanceId, CardDefinition] | None = None,
) -> PlayActionProjection:
    return PlayProjectionResolver(
        action=action,
        observation=observation,
        card_registry=card_registry,
        viewer_hand_definitions=viewer_hand_definitions,
    ).resolve()


def remaining_hand_definitions(
    observation: PlayerObservation,
    card_registry: CardRegistry,
    played_card_id: CardInstanceId,
) -> tuple[CardDefinition, ...]:
    """Return the viewer hand after spending one known card instance."""

    remaining: list[CardDefinition] = []
    for card in observation.viewer_hand:
        if card.instance_id == played_card_id:
            continue
        remaining.append(card_registry.get(card.definition_id))
    return tuple(remaining)


def projected_muster_cards_from_viewer_deck(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    muster_group: str,
    owner: PlayerId,
    battlefield_side: PlayerId,
    row: Row,
) -> tuple[ProjectedBattlefieldCard, ...]:
    """Project the extra board bodies summoned by a live Muster play."""

    return tuple(
        ProjectedBattlefieldCard(
            definition=card_registry.get(card.definition_id),
            owner=owner,
            battlefield_side=battlefield_side,
            row=row,
        )
        for card in observation.viewer_deck
        if card_registry.get(card.definition_id).muster_group == muster_group
    )


def best_medic_revive(
    observation: PlayerObservation,
    *,
    card_registry: CardRegistry,
    battlefield_side: PlayerId,
) -> ProjectedBattlefieldCard | None:
    """Pick the highest-value public Medic revive target for one-step projection."""

    viewer = viewer_public(observation)
    candidates = [
        card_registry.get(card.definition_id)
        for card in viewer.discard
        if (
            card_registry.get(card.definition_id).card_type == CardType.UNIT
            and not card_registry.get(card.definition_id).is_hero
        )
    ]
    if not candidates:
        return None
    revived = max(
        candidates,
        key=lambda definition: (
            medic_revive_priority(
                definition,
                observation=observation,
            ),
            definition.base_strength,
        ),
    )
    row = revived.allowed_rows[0]
    return ProjectedBattlefieldCard(
        definition=revived,
        owner=viewer.player_id,
        battlefield_side=battlefield_side,
        row=row,
    )


def reachable_spy_draw_count(observation: PlayerObservation) -> int:
    """Return the exact public draw count a Spy can still realize immediately."""

    return min(2, len(observation.viewer_deck))


def medic_revive_priority(
    definition: CardDefinition,
    *,
    observation: PlayerObservation,
) -> int:
    """Score Medic revive targets for deterministic one-step projection.

    This is intentionally narrow. It captures only public, immediate value:
    base body, live Spy draws, and chaining another Medic.
    """

    priority = definition.base_strength
    if AbilityKind.SPY in definition.ability_kinds:
        priority += (
            DEFAULT_PROJECTION_POLICY.medic_revive_spy_draw_bonus
            * reachable_spy_draw_count(observation)
        )
    if AbilityKind.MEDIC in definition.ability_kinds:
        priority += DEFAULT_PROJECTION_POLICY.medic_revive_medic_bonus
    return priority
