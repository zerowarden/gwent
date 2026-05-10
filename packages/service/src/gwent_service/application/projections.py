from __future__ import annotations

from collections.abc import Mapping

from gwent_shared.error_translation import translate_exception
from gwent_shared.extract import (
    expect_mapping,
    expect_optional_str,
    optional_str_field,
    require_bool_field,
    require_int_field,
    require_mapping_field,
    require_str_field,
    require_str_sequence_field,
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
from gwent_service.application.state_payload import (
    state_card_instances_by_id,
    state_players_by_engine_id,
)
from gwent_service.domain.models import StoredMatch
from gwent_service.engine.contracts import EngineAdapter


def project_match_for_player(
    stored_match: StoredMatch,
    viewer_service_player_id: str,
    *,
    adapter: EngineAdapter,
) -> MatchView:
    viewer_slot = translate_exception(
        lambda: stored_match.slot_for_service_player(viewer_service_player_id),
        KeyError,
        lambda _exc: UnknownMatchPlayerError(viewer_service_player_id, stored_match.match_id),
    )
    opponent_slot = stored_match.opponent_slot_for_service_player(viewer_service_player_id)

    card_instances = state_card_instances_by_id(stored_match.state_payload)
    players = state_players_by_engine_id(stored_match.state_payload)

    viewer_player = players[viewer_slot.engine_player_id]
    opponent_player = players[opponent_slot.engine_player_id]

    return MatchView(
        match_id=stored_match.match_id,
        viewer_player_id=viewer_slot.service_player_id,
        viewer_engine_player_id=viewer_slot.engine_player_id,
        opponent_player_id=opponent_slot.service_player_id,
        phase=require_str_field(stored_match.state_payload, "phase", context="game_state"),
        status=require_str_field(stored_match.state_payload, "status", context="game_state"),
        round_number=require_int_field(
            stored_match.state_payload,
            "round_number",
            context="game_state",
        ),
        current_player=expect_optional_str(
            stored_match.state_payload.get("current_player"),
            context="game_state",
            label="current_player",
        ),
        starting_player=expect_optional_str(
            stored_match.state_payload.get("starting_player"),
            context="game_state",
            label="starting_player",
        ),
        round_starter=expect_optional_str(
            stored_match.state_payload.get("round_starter"),
            context="game_state",
            label="round_starter",
        ),
        match_winner=expect_optional_str(
            stored_match.state_payload.get("match_winner"),
            context="game_state",
            label="match_winner",
        ),
        viewer=_build_public_player_view(
            viewer_slot.service_player_id,
            viewer_player,
            card_instances,
            adapter=adapter,
        ),
        opponent=_build_public_player_view(
            opponent_slot.service_player_id,
            opponent_player,
            card_instances,
            adapter=adapter,
        ),
        viewer_hand=_cards_from_ids(
            require_str_sequence_field(viewer_player, "hand", context="player"),
            card_instances,
            adapter=adapter,
        ),
        battlefield_weather=_build_row_cards_view(
            require_mapping_field(stored_match.state_payload, "weather", context="game_state"),
            card_instances,
            adapter=adapter,
        ),
        pending_choice=_build_pending_choice_view(
            stored_match.state_payload.get("pending_choice"),
            viewer_engine_player_id=viewer_slot.engine_player_id,
            card_instances=card_instances,
            adapter=adapter,
        ),
        mulligan_submissions=tuple(
            MulliganSubmissionStatusView(
                service_player_id=slot.service_player_id,
                submitted=any(
                    staged.engine_player_id == slot.engine_player_id
                    for staged in stored_match.staged_mulligans
                ),
            )
            for slot in stored_match.player_slots
        ),
    )


def _build_public_player_view(
    service_player_id: str,
    player_payload: Mapping[str, object],
    card_instances: Mapping[str, Mapping[str, object]],
    *,
    adapter: EngineAdapter,
) -> PublicPlayerView:
    return PublicPlayerView(
        service_player_id=service_player_id,
        engine_player_id=require_str_field(player_payload, "player_id", context="player"),
        faction=require_str_field(player_payload, "faction", context="player"),
        leader=_build_leader_view(
            require_mapping_field(player_payload, "leader", context="player"),
            adapter=adapter,
        ),
        deck_count=len(require_str_sequence_field(player_payload, "deck", context="player")),
        hand_count=len(require_str_sequence_field(player_payload, "hand", context="player")),
        discard=_cards_from_ids(
            require_str_sequence_field(player_payload, "discard", context="player"),
            card_instances,
            adapter=adapter,
        ),
        rows=_build_row_cards_view(
            require_mapping_field(player_payload, "rows", context="player"),
            card_instances,
            adapter=adapter,
        ),
        gems_remaining=require_int_field(player_payload, "gems_remaining", context="player"),
        round_wins=require_int_field(player_payload, "round_wins", context="player"),
        has_passed=require_bool_field(player_payload, "has_passed", context="player"),
    )


def _build_leader_view(
    leader_payload: Mapping[str, object],
    *,
    adapter: EngineAdapter,
) -> LeaderView:
    leader_id = require_str_field(leader_payload, "leader_id", context="leader")
    leader_entry = adapter.get_leader_entry(leader_id)
    return LeaderView(
        leader_id=leader_id,
        name=leader_entry.name,
        faction=leader_entry.faction,
        used=require_bool_field(leader_payload, "used", context="leader"),
        disabled=require_bool_field(leader_payload, "disabled", context="leader"),
        horn_row=optional_str_field(leader_payload, "horn_row", context="leader"),
    )


def _build_pending_choice_view(
    pending_choice_payload: object,
    *,
    viewer_engine_player_id: str,
    card_instances: Mapping[str, Mapping[str, object]],
    adapter: EngineAdapter,
) -> PendingChoiceView | None:
    if pending_choice_payload is None:
        return None
    choice_payload = expect_mapping(pending_choice_payload, context="pending_choice")
    chooser_engine_player_id = require_str_field(choice_payload, "player_id", context="choice")
    if chooser_engine_player_id != viewer_engine_player_id:
        return None

    source_card_id = expect_optional_str(
        choice_payload.get("source_card_instance_id"),
        context="choice",
        label="source_card_instance_id",
    )
    source_card = None
    if source_card_id is not None:
        source_card = _card_view_from_instance(
            card_instances[source_card_id],
            adapter=adapter,
        )

    legal_target_cards = _cards_from_ids(
        require_str_sequence_field(
            choice_payload,
            "legal_target_card_instance_ids",
            context="choice",
        ),
        card_instances,
        adapter=adapter,
    )
    return PendingChoiceView(
        choice_id=require_str_field(choice_payload, "choice_id", context="choice"),
        chooser_engine_player_id=chooser_engine_player_id,
        kind=require_str_field(choice_payload, "kind", context="choice"),
        source_kind=require_str_field(choice_payload, "source_kind", context="choice"),
        source_card=source_card,
        source_leader_id=expect_optional_str(
            choice_payload.get("source_leader_id"),
            context="choice",
            label="source_leader_id",
        ),
        legal_target_cards=legal_target_cards,
        legal_rows=require_str_sequence_field(choice_payload, "legal_rows", context="choice"),
        min_selections=require_int_field(choice_payload, "min_selections", context="choice"),
        max_selections=require_int_field(choice_payload, "max_selections", context="choice"),
        source_row=expect_optional_str(
            choice_payload.get("source_row"),
            context="choice",
            label="source_row",
        ),
    )


def _build_row_cards_view(
    rows_payload: Mapping[str, object],
    card_instances: Mapping[str, Mapping[str, object]],
    *,
    adapter: EngineAdapter,
) -> RowCardsView:
    return RowCardsView(
        close=_cards_from_ids(
            require_str_sequence_field(rows_payload, "close", context="rows"),
            card_instances,
            adapter=adapter,
        ),
        ranged=_cards_from_ids(
            require_str_sequence_field(rows_payload, "ranged", context="rows"),
            card_instances,
            adapter=adapter,
        ),
        siege=_cards_from_ids(
            require_str_sequence_field(rows_payload, "siege", context="rows"),
            card_instances,
            adapter=adapter,
        ),
    )


def _cards_from_ids(
    card_ids: tuple[str, ...],
    card_instances: Mapping[str, Mapping[str, object]],
    *,
    adapter: EngineAdapter,
) -> tuple[CardView, ...]:
    return tuple(
        _card_view_from_instance(card_instances[card_instance_id], adapter=adapter)
        for card_instance_id in card_ids
    )


def _card_view_from_instance(
    card_payload: Mapping[str, object],
    *,
    adapter: EngineAdapter,
) -> CardView:
    definition_id = require_str_field(card_payload, "definition_id", context="card")
    card_entry = adapter.get_card_entry(definition_id)
    return CardView(
        instance_id=require_str_field(card_payload, "instance_id", context="card"),
        definition_id=definition_id,
        name=card_entry.name,
        faction=card_entry.faction,
        card_type=card_entry.card_type,
        owner_id=require_str_field(card_payload, "owner", context="card"),
        zone=require_str_field(card_payload, "zone", context="card"),
        row=expect_optional_str(card_payload.get("row"), context="card", label="row"),
        battlefield_side=expect_optional_str(
            card_payload.get("battlefield_side"),
            context="card",
            label="battlefield_side",
        ),
        is_hero=card_entry.is_hero,
    )
