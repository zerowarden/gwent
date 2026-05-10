from collections.abc import Sequence
from functools import singledispatch

from gwent_shared.extract import stringify, stringify_list, stringify_optional

from gwent_engine.core import events as event_models
from gwent_engine.core.errors import SerializationError
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PendingAvengerSummon,
    PendingChoice,
    PlayerState,
    RowState,
)

SCHEMA_VERSION = 1


def game_state_to_dict(state: GameState) -> dict[str, object]:
    return {
        "type": "game_state",
        "schema_version": SCHEMA_VERSION,
        "game_id": stringify(state.game_id),
        "players": [player_state_to_dict(player) for player in state.players],
        "card_instances": [card_instance_to_dict(card) for card in state.card_instances],
        "weather": row_state_to_dict(state.weather),
        "pending_avenger_summons": [
            pending_avenger_summon_to_dict(summon) for summon in state.pending_avenger_summons
        ],
        "pending_choice": pending_choice_to_dict(state.pending_choice),
        "current_player": stringify_optional(state.current_player),
        "starting_player": stringify_optional(state.starting_player),
        "round_starter": stringify_optional(state.round_starter),
        "round_number": state.round_number,
        "phase": state.phase.value,
        "status": state.status.value,
        "match_winner": stringify_optional(state.match_winner),
        "event_counter": state.event_counter,
        "generated_card_counter": state.generated_card_counter,
        "rng_seed": state.rng_seed,
    }


def player_state_to_dict(player: PlayerState) -> dict[str, object]:
    return {
        "player_id": stringify(player.player_id),
        "faction": player.faction.value,
        "leader": leader_state_to_dict(player.leader),
        "deck": stringify_list(player.deck),
        "hand": stringify_list(player.hand),
        "discard": stringify_list(player.discard),
        "rows": row_state_to_dict(player.rows),
        "gems_remaining": player.gems_remaining,
        "round_wins": player.round_wins,
        "has_passed": player.has_passed,
    }


def leader_state_to_dict(leader: LeaderState) -> dict[str, object]:
    return {
        "leader_id": stringify(leader.leader_id),
        "used": leader.used,
        "disabled": leader.disabled,
        "horn_row": leader.horn_row.value if leader.horn_row is not None else None,
    }


def row_state_to_dict(rows: RowState) -> dict[str, object]:
    return {
        "close": stringify_list(rows.close),
        "ranged": stringify_list(rows.ranged),
        "siege": stringify_list(rows.siege),
    }


def card_instance_to_dict(card: CardInstance) -> dict[str, object]:
    return {
        "instance_id": stringify(card.instance_id),
        "definition_id": stringify(card.definition_id),
        "owner": stringify(card.owner),
        "zone": card.zone.value,
        "row": card.row.value if card.row is not None else None,
        "battlefield_side": stringify_optional(card.battlefield_side),
    }


def pending_avenger_summon_to_dict(summon: PendingAvengerSummon) -> dict[str, object]:
    return {
        "source_card_instance_id": stringify(summon.source_card_instance_id),
        "summoned_definition_id": stringify(summon.summoned_definition_id),
        "owner": stringify(summon.owner),
        "battlefield_side": stringify(summon.battlefield_side),
        "row": summon.row.value,
    }


def pending_choice_to_dict(choice: PendingChoice | None) -> dict[str, object] | None:
    if choice is None:
        return None
    return {
        "choice_id": stringify(choice.choice_id),
        "player_id": stringify(choice.player_id),
        "kind": choice.kind.value,
        "source_kind": choice.source_kind.value,
        "source_card_instance_id": stringify_optional(choice.source_card_instance_id),
        "source_leader_id": stringify_optional(choice.source_leader_id),
        "legal_target_card_instance_ids": stringify_list(choice.legal_target_card_instance_ids),
        "legal_rows": [row.value for row in choice.legal_rows],
        "min_selections": choice.min_selections,
        "max_selections": choice.max_selections,
        "source_row": choice.source_row.value if choice.source_row is not None else None,
    }


def events_to_dict(events: Sequence[event_models.GameEvent]) -> list[dict[str, object]]:
    return [event_to_dict(event) for event in events]


def event_to_dict(event: event_models.GameEvent) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event.event_id,
        **_event_payload(event),
    }


@singledispatch
def _event_payload(event: event_models.GameEvent) -> dict[str, object]:
    raise SerializationError(f"Unsupported event type: {type(event)!r}")


@_event_payload.register
def _(event: event_models.StartingPlayerChosenEvent) -> dict[str, object]:
    return {
        "type": "starting_player_chosen",
        "player_id": stringify(event.player_id),
    }


@_event_payload.register
def _(event: event_models.GameStartedEvent) -> dict[str, object]:
    return {
        "type": "game_started",
        "phase": event.phase.value,
        "round_number": event.round_number,
    }


@_event_payload.register
def _(event: event_models.CardsDrawnEvent) -> dict[str, object]:
    return {
        "type": "cards_drawn",
        "player_id": stringify(event.player_id),
        "card_instance_ids": stringify_list(event.card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.MulliganPerformedEvent) -> dict[str, object]:
    return {
        "type": "mulligan_performed",
        "player_id": stringify(event.player_id),
        "replaced_card_instance_ids": stringify_list(event.replaced_card_instance_ids),
        "drawn_card_instance_ids": stringify_list(event.drawn_card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.CardPlayedEvent) -> dict[str, object]:
    return {
        "type": "card_played",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "target_row": event.target_row.value if event.target_row is not None else None,
    }


@_event_payload.register
def _(event: event_models.SpyResolvedEvent) -> dict[str, object]:
    return {
        "type": "spy_resolved",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "drawn_card_instance_ids": stringify_list(event.drawn_card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.MedicResolvedEvent) -> dict[str, object]:
    return {
        "type": "medic_resolved",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "resurrected_card_instance_id": stringify_optional(event.resurrected_card_instance_id),
    }


@_event_payload.register
def _(event: event_models.MusterResolvedEvent) -> dict[str, object]:
    return {
        "type": "muster_resolved",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "mustered_card_instance_ids": stringify_list(event.mustered_card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.CardTransformedEvent) -> dict[str, object]:
    return {
        "type": "card_transformed",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "previous_definition_id": stringify(event.previous_definition_id),
        "new_definition_id": stringify(event.new_definition_id),
        "affected_row": event.affected_row.value,
    }


@_event_payload.register
def _(event: event_models.UnitHornActivatedEvent) -> dict[str, object]:
    return {
        "type": "unit_horn_activated",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "affected_row": event.affected_row.value,
    }


@_event_payload.register
def _(event: event_models.UnitHornSuppressedEvent) -> dict[str, object]:
    return {
        "type": "unit_horn_suppressed",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "affected_row": event.affected_row.value,
        "active_source_category": event.active_source_category.value,
        "active_source_card_instance_id": stringify_optional(event.active_source_card_instance_id),
        "active_source_leader_id": stringify_optional(event.active_source_leader_id),
    }


@_event_payload.register
def _(event: event_models.UnitScorchResolvedEvent) -> dict[str, object]:
    return {
        "type": "unit_scorch_resolved",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "affected_row": event.affected_row.value,
        "destroyed_card_instance_ids": stringify_list(event.destroyed_card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.SpecialCardResolvedEvent) -> dict[str, object]:
    return {
        "type": "special_card_resolved",
        "player_id": stringify(event.player_id),
        "card_instance_id": stringify(event.card_instance_id),
        "ability_kind": event.ability_kind.value,
        "affected_row": event.affected_row.value if event.affected_row is not None else None,
        "target_card_instance_id": stringify_optional(event.target_card_instance_id),
        "discarded_card_instance_ids": stringify_list(event.discarded_card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.AvengerSummonQueuedEvent) -> dict[str, object]:
    return {
        "type": "avenger_summon_queued",
        "player_id": stringify(event.player_id),
        "source_card_instance_id": stringify(event.source_card_instance_id),
        "summoned_definition_id": stringify(event.summoned_definition_id),
        "affected_row": event.affected_row.value,
    }


@_event_payload.register
def _(event: event_models.AvengerSummonedEvent) -> dict[str, object]:
    return {
        "type": "avenger_summoned",
        "player_id": stringify(event.player_id),
        "source_card_instance_id": stringify(event.source_card_instance_id),
        "summoned_card_instance_id": stringify(event.summoned_card_instance_id),
        "summoned_definition_id": stringify(event.summoned_definition_id),
        "affected_row": event.affected_row.value,
    }


@_event_payload.register
def _(event: event_models.LeaderAbilityResolvedEvent) -> dict[str, object]:
    return {
        "type": "leader_ability_resolved",
        "player_id": stringify(event.player_id),
        "leader_id": stringify(event.leader_id),
        "ability_kind": event.ability_kind.value,
        "ability_mode": event.ability_mode.value,
        "affected_row": event.affected_row.value if event.affected_row is not None else None,
        "played_card_instance_id": stringify_optional(event.played_card_instance_id),
        "target_card_instance_id": stringify_optional(event.target_card_instance_id),
        "discarded_card_instance_ids": stringify_list(event.discarded_card_instance_ids),
        "drawn_card_instance_ids": stringify_list(event.drawn_card_instance_ids),
        "returned_card_instance_ids": stringify_list(event.returned_card_instance_ids),
        "revealed_card_instance_ids": stringify_list(event.revealed_card_instance_ids),
        "shuffled_card_instance_ids": stringify_list(event.shuffled_card_instance_ids),
        "moved_card_instance_ids": stringify_list(event.moved_card_instance_ids),
        "disabled_player_id": stringify_optional(event.disabled_player_id),
    }


@_event_payload.register
def _(event: event_models.PlayerPassedEvent) -> dict[str, object]:
    return {
        "type": "player_passed",
        "player_id": stringify(event.player_id),
    }


@_event_payload.register
def _(event: event_models.PlayerLeftEvent) -> dict[str, object]:
    return {
        "type": "player_left",
        "player_id": stringify(event.player_id),
    }


@_event_payload.register
def _(event: event_models.FactionPassiveTriggeredEvent) -> dict[str, object]:
    return {
        "type": "faction_passive_triggered",
        "player_id": stringify(event.player_id),
        "passive_kind": event.passive_kind.value,
        "chosen_player_id": stringify_optional(event.chosen_player_id),
        "card_instance_id": stringify_optional(event.card_instance_id),
    }


@_event_payload.register
def _(event: event_models.RoundEndedEvent) -> dict[str, object]:
    return {
        "type": "round_ended",
        "round_number": event.round_number,
        "player_scores": [
            {"player_id": stringify(player_id), "score": score}
            for player_id, score in event.player_scores
        ],
        "winner": stringify_optional(event.winner),
    }


@_event_payload.register
def _(event: event_models.CardsMovedToDiscardEvent) -> dict[str, object]:
    return {
        "type": "cards_moved_to_discard",
        "card_instance_ids": stringify_list(event.card_instance_ids),
    }


@_event_payload.register
def _(event: event_models.NextRoundStartedEvent) -> dict[str, object]:
    return {
        "type": "next_round_started",
        "round_number": event.round_number,
        "starting_player": stringify(event.starting_player),
    }


@_event_payload.register
def _(event: event_models.MatchEndedEvent) -> dict[str, object]:
    return {
        "type": "match_ended",
        "winner": stringify_optional(event.winner),
    }
