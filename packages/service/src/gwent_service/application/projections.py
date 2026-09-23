from __future__ import annotations

from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PlayerState,
    RowState,
)

from gwent_service.application.dto import (
    CardView,
    LeaderView,
    MatchView,
    MulliganSubmissionStatusView,
    PendingChoiceView,
    PublicPlayerView,
    RowCardsView,
)
from gwent_service.application.errors import UnknownMatchPlayerError
from gwent_service.application.snapshot import MatchSnapshot
from gwent_service.engine.contracts import EngineAdapter


def project_match_for_player(
    snapshot: MatchSnapshot,
    viewer_service_player_id: str,
    *,
    adapter: EngineAdapter,
) -> MatchView:
    try:
        viewer_slot = snapshot.slot_for_service_player(viewer_service_player_id)
    except KeyError as exc:
        raise UnknownMatchPlayerError(viewer_service_player_id, snapshot.match_id) from exc
    opponent_slot = snapshot.opponent_slot_for_service_player(viewer_service_player_id)

    state = snapshot.state
    viewer_player = state.player(PlayerId(viewer_slot.engine_player_id))
    opponent_player = state.player(PlayerId(opponent_slot.engine_player_id))

    return MatchView(
        match_id=snapshot.match_id,
        viewer_player_id=viewer_slot.service_player_id,
        viewer_engine_player_id=viewer_slot.engine_player_id,
        opponent_player_id=opponent_slot.service_player_id,
        phase=state.phase.value,
        status=state.status.value,
        round_number=state.round_number,
        current_player=_optional_player_id(state.current_player),
        starting_player=_optional_player_id(state.starting_player),
        round_starter=_optional_player_id(state.round_starter),
        match_winner=_optional_player_id(state.match_winner),
        viewer=_build_public_player_view(
            viewer_slot.service_player_id,
            viewer_player,
            state=state,
            adapter=adapter,
        ),
        opponent=_build_public_player_view(
            opponent_slot.service_player_id,
            opponent_player,
            state=state,
            adapter=adapter,
        ),
        viewer_hand=_cards_from_ids(state, viewer_player.hand, adapter=adapter),
        battlefield_weather=_build_row_cards_view(state, state.weather, adapter=adapter),
        pending_choice=_build_pending_choice_view(
            state,
            viewer_engine_player_id=viewer_slot.engine_player_id,
            adapter=adapter,
        ),
        mulligan_submissions=tuple(
            MulliganSubmissionStatusView(
                service_player_id=slot.service_player_id,
                submitted=any(
                    staged.engine_player_id == slot.engine_player_id
                    for staged in snapshot.staged_mulligans
                ),
            )
            for slot in snapshot.player_slots
        ),
    )


def _build_public_player_view(
    service_player_id: str,
    player: PlayerState,
    *,
    state: GameState,
    adapter: EngineAdapter,
) -> PublicPlayerView:
    return PublicPlayerView(
        service_player_id=service_player_id,
        engine_player_id=str(player.player_id),
        faction=player.faction.value,
        leader=_build_leader_view(player.leader, adapter=adapter),
        deck_count=len(player.deck),
        hand_count=len(player.hand),
        discard=_cards_from_ids(state, player.discard, adapter=adapter),
        rows=_build_row_cards_view(state, player.rows, adapter=adapter),
        gems_remaining=player.gems_remaining,
        round_wins=player.round_wins,
        has_passed=player.has_passed,
    )


def _build_leader_view(
    leader: LeaderState,
    *,
    adapter: EngineAdapter,
) -> LeaderView:
    leader_id = str(leader.leader_id)
    leader_entry = adapter.get_leader_entry(leader_id)
    return LeaderView(
        leader_id=leader_id,
        name=leader_entry.name,
        faction=leader_entry.faction,
        used=leader.used,
        disabled=leader.disabled,
        horn_row=None if leader.horn_row is None else leader.horn_row.value,
    )


def _build_pending_choice_view(
    state: GameState,
    *,
    viewer_engine_player_id: str,
    adapter: EngineAdapter,
) -> PendingChoiceView | None:
    pending_choice = state.pending_choice
    if pending_choice is None:
        return None
    chooser_engine_player_id = str(pending_choice.player_id)
    if chooser_engine_player_id != viewer_engine_player_id:
        return None

    source_card = None
    if pending_choice.source_card_instance_id is not None:
        source_card = _card_view_from_instance(
            state.card(pending_choice.source_card_instance_id),
            adapter=adapter,
        )

    return PendingChoiceView(
        choice_id=str(pending_choice.choice_id),
        chooser_engine_player_id=chooser_engine_player_id,
        kind=pending_choice.kind.value,
        source_kind=pending_choice.source_kind.value,
        source_card=source_card,
        source_leader_id=(
            None
            if pending_choice.source_leader_id is None
            else str(pending_choice.source_leader_id)
        ),
        legal_target_cards=_cards_from_ids(
            state,
            pending_choice.legal_target_card_instance_ids,
            adapter=adapter,
        ),
        legal_rows=tuple(row.value for row in pending_choice.legal_rows),
        min_selections=pending_choice.min_selections,
        max_selections=pending_choice.max_selections,
        source_row=None if pending_choice.source_row is None else pending_choice.source_row.value,
    )


def _build_row_cards_view(
    state: GameState,
    rows: RowState,
    *,
    adapter: EngineAdapter,
) -> RowCardsView:
    return RowCardsView(
        close=_cards_from_ids(state, rows.close, adapter=adapter),
        ranged=_cards_from_ids(state, rows.ranged, adapter=adapter),
        siege=_cards_from_ids(state, rows.siege, adapter=adapter),
    )


def _cards_from_ids(
    state: GameState,
    card_ids: tuple[CardInstanceId, ...],
    *,
    adapter: EngineAdapter,
) -> tuple[CardView, ...]:
    return tuple(
        _card_view_from_instance(state.card(card_id), adapter=adapter) for card_id in card_ids
    )


def _card_view_from_instance(
    card_instance: CardInstance,
    *,
    adapter: EngineAdapter,
) -> CardView:
    definition_id = str(card_instance.definition_id)
    card_entry = adapter.get_card_entry(definition_id)
    return CardView(
        instance_id=str(card_instance.instance_id),
        definition_id=definition_id,
        name=card_entry.name,
        faction=card_entry.faction,
        card_type=card_entry.card_type,
        owner_id=str(card_instance.owner),
        zone=card_instance.zone.value,
        row=None if card_instance.row is None else card_instance.row.value,
        battlefield_side=(
            None if card_instance.battlefield_side is None else str(card_instance.battlefield_side)
        ),
        is_hero=card_entry.is_hero,
    )


def _optional_player_id(player_id: PlayerId | None) -> str | None:
    return None if player_id is None else str(player_id)
