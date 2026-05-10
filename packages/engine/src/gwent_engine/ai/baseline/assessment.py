from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.observations import (
    ObservedCard,
    PlayerObservation,
    PublicPlayerStateView,
)
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import CardType, ChoiceSourceKind, GameStatus, Phase, Row
from gwent_engine.core.actions import GameAction, PassAction, PlayCardAction
from gwent_engine.core.ids import PlayerId


@dataclass(frozen=True, slots=True)
class RowSummary:
    row: Row
    unit_count: int
    non_hero_unit_count: int
    non_hero_unit_base_strength: int
    base_strength: int


@dataclass(frozen=True, slots=True)
class PlayerAssessment:
    player_id: PlayerId
    hand_count: int
    hand_value: int
    unit_hand_count: int
    hand_definitions: tuple[CardDefinition, ...]
    discard_definitions: tuple[CardDefinition, ...]
    board_strength: int
    close: RowSummary
    ranged: RowSummary
    siege: RowSummary
    gems_remaining: int
    round_wins: int
    passed: bool
    leader_used: bool

    def row_summaries(self) -> tuple[RowSummary, RowSummary, RowSummary]:
        return (self.close, self.ranged, self.siege)


@dataclass(frozen=True, slots=True)
class DecisionAssessment:
    viewer_player_id: PlayerId
    phase: Phase
    status: GameStatus
    round_number: int
    viewer: PlayerAssessment
    opponent: PlayerAssessment
    active_weather_rows: tuple[Row, ...]
    score_gap: int
    card_advantage: int
    legal_action_count: int
    legal_pass_available: bool
    legal_play_count: int
    pending_choice_source_kind: ChoiceSourceKind | None
    opponent_passed: bool
    is_final_round: bool
    is_elimination_round: bool


def build_assessment(
    observation: PlayerObservation,
    card_registry: CardRegistry,
    *,
    legal_actions: tuple[GameAction, ...] = (),
) -> DecisionAssessment:
    from gwent_engine.ai.baseline.projection.board import current_public_board_projection

    public_state = observation.public_state
    viewer_public = _player_view(public_state.players, observation.viewer_player_id)
    opponent_public = _other_player_view(public_state.players, observation.viewer_player_id)
    board_projection = current_public_board_projection(
        observation,
        card_registry=card_registry,
    )
    viewer = _build_player_assessment(
        viewer_public,
        hand_cards=observation.viewer_hand,
        card_registry=card_registry,
        board_strength=board_projection.viewer_score,
    )
    opponent = _build_player_assessment(
        opponent_public,
        hand_cards=(),
        card_registry=card_registry,
        board_strength=board_projection.opponent_score,
    )
    active_weather_rows = tuple(
        row
        for row, cards in (
            (Row.CLOSE, public_state.battlefield_weather.close),
            (Row.RANGED, public_state.battlefield_weather.ranged),
            (Row.SIEGE, public_state.battlefield_weather.siege),
        )
        if cards
    )
    return DecisionAssessment(
        viewer_player_id=observation.viewer_player_id,
        phase=public_state.phase,
        status=public_state.status,
        round_number=public_state.round_number,
        viewer=viewer,
        opponent=opponent,
        active_weather_rows=active_weather_rows,
        score_gap=board_projection.score_gap,
        card_advantage=viewer.hand_count - opponent.hand_count,
        legal_action_count=len(legal_actions),
        legal_pass_available=any(isinstance(action, PassAction) for action in legal_actions),
        legal_play_count=sum(isinstance(action, PlayCardAction) for action in legal_actions),
        pending_choice_source_kind=(
            observation.visible_pending_choice.source_kind
            if observation.visible_pending_choice is not None
            else None
        ),
        opponent_passed=opponent.passed,
        is_final_round=public_state.round_number >= 3,
        is_elimination_round=(
            public_state.round_number >= 3
            or viewer.gems_remaining == 1
            or opponent.gems_remaining == 1
        ),
    )


def _build_player_assessment(
    player: PublicPlayerStateView,
    *,
    hand_cards: tuple[ObservedCard, ...],
    card_registry: CardRegistry,
    board_strength: int,
) -> PlayerAssessment:
    hand_definitions = _definitions_for_cards(hand_cards, card_registry)
    discard_definitions = _definitions_for_cards(player.discard, card_registry)
    return PlayerAssessment(
        player_id=player.player_id,
        hand_count=len(hand_cards) if hand_cards else player.hand_count,
        hand_value=sum(definition.base_strength for definition in hand_definitions),
        unit_hand_count=sum(
            definition.card_type == CardType.UNIT for definition in hand_definitions
        ),
        hand_definitions=hand_definitions,
        discard_definitions=discard_definitions,
        board_strength=board_strength,
        close=_row_summary(Row.CLOSE, player.rows.close, card_registry),
        ranged=_row_summary(Row.RANGED, player.rows.ranged, card_registry),
        siege=_row_summary(Row.SIEGE, player.rows.siege, card_registry),
        gems_remaining=player.gems_remaining,
        round_wins=player.round_wins,
        passed=player.has_passed,
        leader_used=player.leader.used,
    )


def _definitions_for_cards(
    cards: tuple[ObservedCard, ...],
    card_registry: CardRegistry,
) -> tuple[CardDefinition, ...]:
    return tuple(card_registry.get(card.definition_id) for card in cards)


def _row_summary(
    row: Row,
    cards: tuple[ObservedCard, ...],
    card_registry: CardRegistry,
) -> RowSummary:
    definitions = _definitions_for_cards(cards, card_registry)
    return RowSummary(
        row=row,
        unit_count=len(cards),
        non_hero_unit_count=sum(not definition.is_hero for definition in definitions),
        non_hero_unit_base_strength=sum(
            definition.base_strength for definition in definitions if not definition.is_hero
        ),
        base_strength=sum(definition.base_strength for definition in definitions),
    )


def _player_view(
    players: tuple[PublicPlayerStateView, PublicPlayerStateView],
    player_id: PlayerId,
) -> PublicPlayerStateView:
    if players[0].player_id == player_id:
        return players[0]
    return players[1]


def _other_player_view(
    players: tuple[PublicPlayerStateView, PublicPlayerStateView],
    player_id: PlayerId,
) -> PublicPlayerStateView:
    if players[0].player_id == player_id:
        return players[1]
    return players[0]
