from __future__ import annotations

from dataclasses import dataclass, field

from gwent_shared.extract import stringify_optional

from gwent_engine.core import (
    ChoiceKind,
    ChoiceSourceKind,
    FactionId,
    GameStatus,
    LeaderAbilityKind,
    Phase,
    Row,
)
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.state import GameState, PendingChoice, PlayerState, RowState
from gwent_engine.leaders import LeaderRegistry


@dataclass(frozen=True, slots=True)
class ObservedLeader:
    leader_id: LeaderId
    used: bool
    disabled: bool
    horn_row: Row | None
    available_horn_row: Row | None = None


@dataclass(frozen=True, slots=True)
class ObservedCard:
    instance_id: CardInstanceId
    definition_id: CardDefinitionId
    owner: PlayerId
    row: Row | None = None
    battlefield_side: PlayerId | None = None


@dataclass(frozen=True, slots=True)
class ObservedRows:
    close: tuple[ObservedCard, ...] = ()
    ranged: tuple[ObservedCard, ...] = ()
    siege: tuple[ObservedCard, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicPlayerStateView:
    player_id: PlayerId
    faction: FactionId
    leader: ObservedLeader
    deck_count: int
    hand_count: int
    discard: tuple[ObservedCard, ...]
    rows: ObservedRows
    gems_remaining: int
    round_wins: int
    has_passed: bool


@dataclass(frozen=True, slots=True)
class PublicPendingChoiceView:
    player_id: PlayerId
    kind: ChoiceKind
    source_kind: ChoiceSourceKind


@dataclass(frozen=True, slots=True)
class VisiblePendingChoiceView:
    choice_id: ChoiceId
    player_id: PlayerId
    kind: ChoiceKind
    source_kind: ChoiceSourceKind
    source_card_instance_id: CardInstanceId | None
    source_leader_id: LeaderId | None
    legal_target_card_instance_ids: tuple[CardInstanceId, ...]
    legal_rows: tuple[Row, ...]
    min_selections: int
    max_selections: int
    source_row: Row | None


@dataclass(frozen=True, slots=True)
class PublicGameStateView:
    game_id: GameId
    phase: Phase
    status: GameStatus
    current_player: PlayerId | None
    starting_player: PlayerId | None
    round_starter: PlayerId | None
    round_number: int
    match_winner: PlayerId | None
    players: tuple[PublicPlayerStateView, PublicPlayerStateView]
    battlefield_weather: ObservedRows
    pending_choice: PublicPendingChoiceView | None


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    viewer_player_id: PlayerId
    public_state: PublicGameStateView
    viewer_hand: tuple[ObservedCard, ...]
    viewer_deck: tuple[ObservedCard, ...]
    visible_pending_choice: VisiblePendingChoiceView | None
    engine_state: GameState | None = field(
        default=None,
        repr=False,
        compare=False,
        hash=False,
    )


def build_public_game_view(
    state: GameState,
    leader_registry: LeaderRegistry | None = None,
) -> PublicGameStateView:
    return PublicGameStateView(
        game_id=state.game_id,
        phase=state.phase,
        status=state.status,
        current_player=state.current_player,
        starting_player=state.starting_player,
        round_starter=state.round_starter,
        round_number=state.round_number,
        match_winner=state.match_winner,
        players=(
            _build_public_player_view(state, state.players[0], leader_registry=leader_registry),
            _build_public_player_view(state, state.players[1], leader_registry=leader_registry),
        ),
        battlefield_weather=_build_row_view(state, state.weather),
        pending_choice=_build_public_pending_choice_view(state.pending_choice),
    )


def build_player_observation(
    state: GameState,
    viewer_player_id: PlayerId,
    leader_registry: LeaderRegistry | None = None,
) -> PlayerObservation:
    viewer = state.player(viewer_player_id)
    return PlayerObservation(
        viewer_player_id=viewer_player_id,
        public_state=build_public_game_view(state, leader_registry),
        viewer_hand=tuple(_observe_card(state, card_id) for card_id in viewer.hand),
        viewer_deck=tuple(_observe_card(state, card_id) for card_id in viewer.deck),
        visible_pending_choice=_build_visible_pending_choice_view(state, viewer_player_id),
        # Internal hook for search-style agents. This is intentionally omitted
        # from the public dict export surface so other consumers continue to
        # treat `PlayerObservation` as an observation object rather than a
        # serialized engine state carrier.
        engine_state=state,
    )


def public_game_view_to_dict(view: PublicGameStateView) -> dict[str, object]:
    return {
        "game_id": str(view.game_id),
        "phase": view.phase.value,
        "status": view.status.value,
        "current_player": stringify_optional(view.current_player),
        "starting_player": stringify_optional(view.starting_player),
        "round_starter": stringify_optional(view.round_starter),
        "round_number": view.round_number,
        "match_winner": stringify_optional(view.match_winner),
        "players": [public_player_view_to_dict(player) for player in view.players],
        "battlefield_weather": observed_rows_to_dict(view.battlefield_weather),
        "pending_choice": (
            {
                "player_id": str(view.pending_choice.player_id),
                "kind": view.pending_choice.kind.value,
                "source_kind": view.pending_choice.source_kind.value,
            }
            if view.pending_choice is not None
            else None
        ),
    }


def player_observation_to_dict(observation: PlayerObservation) -> dict[str, object]:
    return {
        "viewer_player_id": str(observation.viewer_player_id),
        "public_state": public_game_view_to_dict(observation.public_state),
        "viewer_hand": [observed_card_to_dict(card) for card in observation.viewer_hand],
        "viewer_deck": [observed_card_to_dict(card) for card in observation.viewer_deck],
        "visible_pending_choice": _visible_pending_choice_to_dict(
            observation.visible_pending_choice
        ),
    }


def public_player_view_to_dict(player: PublicPlayerStateView) -> dict[str, object]:
    return {
        "player_id": str(player.player_id),
        "faction": player.faction.value,
        "leader": observed_leader_to_dict(player.leader),
        "deck_count": player.deck_count,
        "hand_count": player.hand_count,
        "discard": [observed_card_to_dict(card) for card in player.discard],
        "rows": observed_rows_to_dict(player.rows),
        "gems_remaining": player.gems_remaining,
        "round_wins": player.round_wins,
        "has_passed": player.has_passed,
    }


def observed_leader_to_dict(leader: ObservedLeader) -> dict[str, object]:
    return {
        "leader_id": str(leader.leader_id),
        "used": leader.used,
        "disabled": leader.disabled,
        "horn_row": leader.horn_row.value if leader.horn_row is not None else None,
        "available_horn_row": (
            leader.available_horn_row.value if leader.available_horn_row is not None else None
        ),
    }


def observed_rows_to_dict(rows: ObservedRows) -> dict[str, object]:
    return {
        "close": [observed_card_to_dict(card) for card in rows.close],
        "ranged": [observed_card_to_dict(card) for card in rows.ranged],
        "siege": [observed_card_to_dict(card) for card in rows.siege],
    }


def observed_card_to_dict(card: ObservedCard) -> dict[str, object]:
    return {
        "instance_id": str(card.instance_id),
        "definition_id": str(card.definition_id),
        "owner": str(card.owner),
        "row": card.row.value if card.row is not None else None,
        "battlefield_side": stringify_optional(card.battlefield_side),
    }


def _build_public_player_view(
    state: GameState,
    player: PlayerState,
    *,
    leader_registry: LeaderRegistry | None,
) -> PublicPlayerStateView:
    return PublicPlayerStateView(
        player_id=player.player_id,
        faction=player.faction,
        leader=_build_observed_leader(player, leader_registry=leader_registry),
        deck_count=len(player.deck),
        hand_count=len(player.hand),
        discard=_observe_cards(state, player.discard),
        rows=_build_row_view(state, player.rows),
        gems_remaining=player.gems_remaining,
        round_wins=player.round_wins,
        has_passed=player.has_passed,
    )


def _build_row_view(
    state: GameState,
    rows: RowState,
) -> ObservedRows:
    return ObservedRows(
        close=_observe_cards(state, rows.close),
        ranged=_observe_cards(state, rows.ranged),
        siege=_observe_cards(state, rows.siege),
    )


def _observe_card(state: GameState, card_id: CardInstanceId) -> ObservedCard:
    card = state.card(card_id)
    return ObservedCard(
        instance_id=card.instance_id,
        definition_id=card.definition_id,
        owner=card.owner,
        row=card.row,
        battlefield_side=card.battlefield_side,
    )


def _observe_cards(
    state: GameState,
    card_ids: tuple[CardInstanceId, ...],
) -> tuple[ObservedCard, ...]:
    return tuple(_observe_card(state, card_id) for card_id in card_ids)


def _build_observed_leader(
    player: PlayerState,
    *,
    leader_registry: LeaderRegistry | None,
) -> ObservedLeader:
    available_horn_row = None
    if leader_registry is not None and not player.leader.used and not player.leader.disabled:
        leader_definition = leader_registry.get(player.leader.leader_id)
        if leader_definition.ability_kind == LeaderAbilityKind.HORN_OWN_ROW:
            available_horn_row = leader_definition.affected_row
    return ObservedLeader(
        leader_id=player.leader.leader_id,
        used=player.leader.used,
        disabled=player.leader.disabled,
        horn_row=player.leader.horn_row,
        available_horn_row=available_horn_row,
    )


def _build_public_pending_choice_view(
    pending_choice: PendingChoice | None,
) -> PublicPendingChoiceView | None:
    if pending_choice is None:
        return None
    return PublicPendingChoiceView(
        player_id=pending_choice.player_id,
        kind=pending_choice.kind,
        source_kind=pending_choice.source_kind,
    )


def _build_visible_pending_choice_view(
    state: GameState,
    viewer_player_id: PlayerId,
) -> VisiblePendingChoiceView | None:
    pending_choice = state.pending_choice
    if pending_choice is None or pending_choice.player_id != viewer_player_id:
        return None
    return VisiblePendingChoiceView(
        choice_id=pending_choice.choice_id,
        player_id=pending_choice.player_id,
        kind=pending_choice.kind,
        source_kind=pending_choice.source_kind,
        source_card_instance_id=pending_choice.source_card_instance_id,
        source_leader_id=pending_choice.source_leader_id,
        legal_target_card_instance_ids=pending_choice.legal_target_card_instance_ids,
        legal_rows=pending_choice.legal_rows,
        min_selections=pending_choice.min_selections,
        max_selections=pending_choice.max_selections,
        source_row=pending_choice.source_row,
    )


def _visible_pending_choice_to_dict(
    pending_choice: VisiblePendingChoiceView | None,
) -> dict[str, object] | None:
    if pending_choice is None:
        return None
    return {
        "choice_id": str(pending_choice.choice_id),
        "player_id": str(pending_choice.player_id),
        "kind": pending_choice.kind.value,
        "source_kind": pending_choice.source_kind.value,
        "source_card_instance_id": stringify_optional(pending_choice.source_card_instance_id),
        "source_leader_id": stringify_optional(pending_choice.source_leader_id),
        "legal_target_card_instance_ids": [
            str(card_id) for card_id in pending_choice.legal_target_card_instance_ids
        ],
        "legal_rows": [row.value for row in pending_choice.legal_rows],
        "min_selections": pending_choice.min_selections,
        "max_selections": pending_choice.max_selections,
        "source_row": (
            pending_choice.source_row.value if pending_choice.source_row is not None else None
        ),
    }
