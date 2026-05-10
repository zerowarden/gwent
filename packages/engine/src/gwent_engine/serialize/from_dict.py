from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import cast

from gwent_shared.error_translation import (
    TranslatedExceptionContext,
    translate_exception_context,
)
from gwent_shared.extract import (
    expect_mapping,
    expect_optional_int,
    expect_sequence,
    expect_str,
    require_bool_field,
    require_int_field,
    require_str_field,
)

from gwent_engine.core import (
    AbilityKind,
    ChoiceKind,
    ChoiceSourceKind,
    EffectSourceCategory,
    FactionId,
    GameStatus,
    LeaderAbilityKind,
    LeaderAbilityMode,
    PassiveKind,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.errors import SerializationError
from gwent_engine.core.events import (
    AvengerSummonedEvent,
    AvengerSummonQueuedEvent,
    CardPlayedEvent,
    CardsDrawnEvent,
    CardsMovedToDiscardEvent,
    CardTransformedEvent,
    FactionPassiveTriggeredEvent,
    GameEvent,
    GameStartedEvent,
    LeaderAbilityResolvedEvent,
    MatchEndedEvent,
    MedicResolvedEvent,
    MulliganPerformedEvent,
    MusterResolvedEvent,
    NextRoundStartedEvent,
    PlayerLeftEvent,
    PlayerPassedEvent,
    RoundEndedEvent,
    SpecialCardResolvedEvent,
    SpyResolvedEvent,
    StartingPlayerChosenEvent,
    UnitHornActivatedEvent,
    UnitHornSuppressedEvent,
    UnitScorchResolvedEvent,
)
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
)
from gwent_engine.core.invariants import check_game_state_invariants
from gwent_engine.core.state import (
    CardInstance,
    GameState,
    LeaderState,
    PendingAvengerSummon,
    PendingChoice,
    PlayerState,
    RowState,
)
from gwent_engine.serialize.to_dict import SCHEMA_VERSION


def game_state_from_dict(data: Mapping[str, object]) -> GameState:
    _validate_root(data, expected_type="game_state", context="game_state")
    with _translate_value_error("game_state"):
        state = GameState(
            game_id=GameId(_require_str(data, "game_id", context="game_state")),
            players=_parse_players(data.get("players")),
            card_instances=_parse_card_instances(data.get("card_instances")),
            weather=_parse_optional_row_state(
                data.get("weather"),
                context="game_state.weather",
            ),
            pending_avenger_summons=_parse_pending_avenger_summons(
                data.get("pending_avenger_summons"),
                context="game_state.pending_avenger_summons",
            ),
            pending_choice=_parse_pending_choice(
                data.get("pending_choice"),
                context="game_state.pending_choice",
            ),
            current_player=_parse_optional_player_id(
                data.get("current_player"),
                context="game_state.current_player",
            ),
            starting_player=_parse_optional_player_id(
                data.get("starting_player"),
                context="game_state.starting_player",
            ),
            round_starter=_parse_optional_player_id(
                data.get("round_starter"),
                context="game_state.round_starter",
            ),
            round_number=_require_int(data, "round_number", context="game_state"),
            phase=_parse_enum(
                Phase,
                _require_str(data, "phase", context="game_state"),
                context="game_state.phase",
            ),
            status=_parse_enum(
                GameStatus,
                _require_str(data, "status", context="game_state"),
                context="game_state.status",
            ),
            match_winner=_parse_optional_player_id(
                data.get("match_winner"),
                context="game_state.match_winner",
            ),
            event_counter=_require_int(data, "event_counter", context="game_state"),
            generated_card_counter=_require_int(
                data,
                "generated_card_counter",
                context="game_state",
            ),
            rng_seed=_parse_optional_int(data.get("rng_seed"), context="game_state.rng_seed"),
        )
    check_game_state_invariants(state)
    return state


def events_from_dict(entries: Sequence[object]) -> tuple[GameEvent, ...]:
    return tuple(event_from_dict(_require_mapping(entry, context="event")) for entry in entries)


def event_from_dict(data: Mapping[str, object]) -> GameEvent:
    _validate_root(data, expected_type=None, context="event")
    event_type = _require_str(data, "type", context="event")
    parser = EVENT_PARSERS.get(event_type)
    if parser is None:
        raise SerializationError(f"Unknown event type: {event_type!r}")
    return parser(data, event_type)


type EventParser = Callable[[Mapping[str, object], str], GameEvent]


def _parse_starting_player_chosen_event(
    data: Mapping[str, object], event_type: str
) -> StartingPlayerChosenEvent:
    return StartingPlayerChosenEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
    )


def _parse_game_started_event(data: Mapping[str, object], event_type: str) -> GameStartedEvent:
    return GameStartedEvent(
        event_id=_event_id(data, event_type),
        phase=_parse_required_enum_field(Phase, data, "phase", event_type),
        round_number=_require_int(data, "round_number", context=event_type),
    )


def _parse_cards_drawn_event(data: Mapping[str, object], event_type: str) -> CardsDrawnEvent:
    return CardsDrawnEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_ids=_parse_card_instance_ids_field(data, "card_instance_ids", event_type),
    )


def _parse_mulligan_performed_event(
    data: Mapping[str, object], event_type: str
) -> MulliganPerformedEvent:
    return MulliganPerformedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        replaced_card_instance_ids=_parse_card_instance_ids_field(
            data, "replaced_card_instance_ids", event_type
        ),
        drawn_card_instance_ids=_parse_card_instance_ids_field(
            data, "drawn_card_instance_ids", event_type
        ),
    )


def _parse_card_played_event(data: Mapping[str, object], event_type: str) -> CardPlayedEvent:
    return CardPlayedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        target_row=_parse_optional_enum_field(Row, data, "target_row", event_type),
    )


def _parse_spy_resolved_event(data: Mapping[str, object], event_type: str) -> SpyResolvedEvent:
    return SpyResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        drawn_card_instance_ids=_parse_card_instance_ids_field(
            data, "drawn_card_instance_ids", event_type
        ),
    )


def _parse_medic_resolved_event(data: Mapping[str, object], event_type: str) -> MedicResolvedEvent:
    return MedicResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        resurrected_card_instance_id=_parse_optional_card_instance_id_field(
            data, "resurrected_card_instance_id", event_type
        ),
    )


def _parse_muster_resolved_event(
    data: Mapping[str, object], event_type: str
) -> MusterResolvedEvent:
    return MusterResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        mustered_card_instance_ids=_parse_card_instance_ids_field(
            data, "mustered_card_instance_ids", event_type
        ),
    )


def _parse_card_transformed_event(
    data: Mapping[str, object], event_type: str
) -> CardTransformedEvent:
    return CardTransformedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        previous_definition_id=_parse_required_card_definition_id(
            data, "previous_definition_id", event_type
        ),
        new_definition_id=_parse_required_card_definition_id(data, "new_definition_id", event_type),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
    )


def _parse_unit_horn_activated_event(
    data: Mapping[str, object], event_type: str
) -> UnitHornActivatedEvent:
    return UnitHornActivatedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
    )


def _parse_unit_horn_suppressed_event(
    data: Mapping[str, object], event_type: str
) -> UnitHornSuppressedEvent:
    return UnitHornSuppressedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
        active_source_category=_parse_required_enum_field(
            EffectSourceCategory,
            data,
            "active_source_category",
            event_type,
        ),
        active_source_card_instance_id=_parse_optional_card_instance_id_field(
            data, "active_source_card_instance_id", event_type
        ),
        active_source_leader_id=_parse_optional_leader_id_field(
            data, "active_source_leader_id", event_type
        ),
    )


def _parse_unit_scorch_resolved_event(
    data: Mapping[str, object], event_type: str
) -> UnitScorchResolvedEvent:
    return UnitScorchResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
        destroyed_card_instance_ids=_parse_card_instance_ids_field(
            data, "destroyed_card_instance_ids", event_type
        ),
    )


def _parse_special_card_resolved_event(
    data: Mapping[str, object], event_type: str
) -> SpecialCardResolvedEvent:
    return SpecialCardResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        card_instance_id=_parse_required_card_instance_id(data, "card_instance_id", event_type),
        ability_kind=_parse_required_enum_field(AbilityKind, data, "ability_kind", event_type),
        affected_row=_parse_optional_enum_field(Row, data, "affected_row", event_type),
        target_card_instance_id=_parse_optional_card_instance_id_field(
            data, "target_card_instance_id", event_type
        ),
        discarded_card_instance_ids=_parse_card_instance_ids_field(
            data, "discarded_card_instance_ids", event_type
        ),
    )


def _parse_avenger_summon_queued_event(
    data: Mapping[str, object], event_type: str
) -> AvengerSummonQueuedEvent:
    return AvengerSummonQueuedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        source_card_instance_id=_parse_required_card_instance_id(
            data, "source_card_instance_id", event_type
        ),
        summoned_definition_id=_parse_required_card_definition_id(
            data, "summoned_definition_id", event_type
        ),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
    )


def _parse_avenger_summoned_event(
    data: Mapping[str, object], event_type: str
) -> AvengerSummonedEvent:
    return AvengerSummonedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        source_card_instance_id=_parse_required_card_instance_id(
            data, "source_card_instance_id", event_type
        ),
        summoned_card_instance_id=_parse_required_card_instance_id(
            data, "summoned_card_instance_id", event_type
        ),
        summoned_definition_id=_parse_required_card_definition_id(
            data, "summoned_definition_id", event_type
        ),
        affected_row=_parse_required_enum_field(Row, data, "affected_row", event_type),
    )


def _parse_leader_ability_resolved_event(
    data: Mapping[str, object], event_type: str
) -> LeaderAbilityResolvedEvent:
    return LeaderAbilityResolvedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        leader_id=_parse_required_leader_id(data, "leader_id", event_type),
        ability_kind=_parse_required_enum_field(
            LeaderAbilityKind, data, "ability_kind", event_type
        ),
        ability_mode=_parse_required_enum_field(
            LeaderAbilityMode, data, "ability_mode", event_type
        ),
        affected_row=_parse_optional_enum_field(Row, data, "affected_row", event_type),
        played_card_instance_id=_parse_optional_card_instance_id_field(
            data, "played_card_instance_id", event_type
        ),
        target_card_instance_id=_parse_optional_card_instance_id_field(
            data, "target_card_instance_id", event_type
        ),
        discarded_card_instance_ids=_parse_card_instance_ids_field(
            data, "discarded_card_instance_ids", event_type
        ),
        drawn_card_instance_ids=_parse_card_instance_ids_field(
            data, "drawn_card_instance_ids", event_type
        ),
        returned_card_instance_ids=_parse_card_instance_ids_field(
            data, "returned_card_instance_ids", event_type
        ),
        revealed_card_instance_ids=_parse_card_instance_ids_field(
            data, "revealed_card_instance_ids", event_type
        ),
        shuffled_card_instance_ids=_parse_card_instance_ids_field(
            data, "shuffled_card_instance_ids", event_type
        ),
        moved_card_instance_ids=_parse_card_instance_ids_field(
            data, "moved_card_instance_ids", event_type
        ),
        disabled_player_id=_parse_optional_player_id_field(data, "disabled_player_id", event_type),
    )


def _parse_player_passed_event(data: Mapping[str, object], event_type: str) -> PlayerPassedEvent:
    return PlayerPassedEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
    )


def _parse_player_left_event(data: Mapping[str, object], event_type: str) -> PlayerLeftEvent:
    return PlayerLeftEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
    )


def _parse_faction_passive_triggered_event(
    data: Mapping[str, object], event_type: str
) -> FactionPassiveTriggeredEvent:
    return FactionPassiveTriggeredEvent(
        event_id=_event_id(data, event_type),
        player_id=_parse_required_player_id(data, "player_id", event_type),
        passive_kind=_parse_required_enum_field(PassiveKind, data, "passive_kind", event_type),
        chosen_player_id=_parse_optional_player_id_field(data, "chosen_player_id", event_type),
        card_instance_id=_parse_optional_card_instance_id_field(
            data, "card_instance_id", event_type
        ),
    )


def _parse_round_ended_event(data: Mapping[str, object], event_type: str) -> RoundEndedEvent:
    return RoundEndedEvent(
        event_id=_event_id(data, event_type),
        round_number=_require_int(data, "round_number", context=event_type),
        player_scores=_parse_player_scores(
            data.get("player_scores"),
            context=f"{event_type}.player_scores",
        ),
        winner=_parse_optional_player_id_field(data, "winner", event_type),
    )


def _parse_cards_moved_to_discard_event(
    data: Mapping[str, object], event_type: str
) -> CardsMovedToDiscardEvent:
    return CardsMovedToDiscardEvent(
        event_id=_event_id(data, event_type),
        card_instance_ids=_parse_card_instance_ids_field(data, "card_instance_ids", event_type),
    )


def _parse_next_round_started_event(
    data: Mapping[str, object], event_type: str
) -> NextRoundStartedEvent:
    return NextRoundStartedEvent(
        event_id=_event_id(data, event_type),
        round_number=_require_int(data, "round_number", context=event_type),
        starting_player=_parse_required_player_id(data, "starting_player", event_type),
    )


def _parse_match_ended_event(data: Mapping[str, object], event_type: str) -> MatchEndedEvent:
    return MatchEndedEvent(
        event_id=_event_id(data, event_type),
        winner=_parse_optional_player_id_field(data, "winner", event_type),
    )


EVENT_PARSERS: dict[str, EventParser] = {
    "starting_player_chosen": _parse_starting_player_chosen_event,
    "game_started": _parse_game_started_event,
    "cards_drawn": _parse_cards_drawn_event,
    "mulligan_performed": _parse_mulligan_performed_event,
    "card_played": _parse_card_played_event,
    "spy_resolved": _parse_spy_resolved_event,
    "medic_resolved": _parse_medic_resolved_event,
    "muster_resolved": _parse_muster_resolved_event,
    "card_transformed": _parse_card_transformed_event,
    "unit_horn_activated": _parse_unit_horn_activated_event,
    "unit_horn_suppressed": _parse_unit_horn_suppressed_event,
    "unit_scorch_resolved": _parse_unit_scorch_resolved_event,
    "special_card_resolved": _parse_special_card_resolved_event,
    "avenger_summon_queued": _parse_avenger_summon_queued_event,
    "avenger_summoned": _parse_avenger_summoned_event,
    "leader_ability_resolved": _parse_leader_ability_resolved_event,
    "player_passed": _parse_player_passed_event,
    "player_left": _parse_player_left_event,
    "faction_passive_triggered": _parse_faction_passive_triggered_event,
    "round_ended": _parse_round_ended_event,
    "cards_moved_to_discard": _parse_cards_moved_to_discard_event,
    "next_round_started": _parse_next_round_started_event,
    "match_ended": _parse_match_ended_event,
}


def _event_id(data: Mapping[str, object], event_type: str) -> int:
    return _require_int(data, "event_id", context=f"event {event_type}")


def _parse_required_player_id(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> PlayerId:
    return PlayerId(_require_str(data, field, context=event_type))


def _parse_required_card_instance_id(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> CardInstanceId:
    return CardInstanceId(_require_str(data, field, context=event_type))


def _parse_required_card_definition_id(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> CardDefinitionId:
    return CardDefinitionId(_require_str(data, field, context=event_type))


def _parse_required_leader_id(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> LeaderId:
    return LeaderId(_require_str(data, field, context=event_type))


def _parse_required_enum_field[EnumT: StrEnum](
    enum_type: type[EnumT],
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> EnumT:
    return _parse_enum(
        enum_type,
        _require_str(data, field, context=event_type),
        context=f"{event_type}.{field}",
    )


def _parse_optional_enum_field[EnumT: StrEnum](
    enum_type: type[EnumT],
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> EnumT | None:
    return _parse_optional_enum(
        enum_type,
        data.get(field),
        context=f"{event_type}.{field}",
    )


def _parse_optional_player_id_field(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> PlayerId | None:
    return _parse_optional_player_id(data.get(field), context=f"{event_type}.{field}")


def _parse_optional_card_instance_id_field(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> CardInstanceId | None:
    return _parse_optional_card_instance_id(data.get(field), context=f"{event_type}.{field}")


def _parse_optional_leader_id_field(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> LeaderId | None:
    return _parse_optional_leader_id(data.get(field), context=f"{event_type}.{field}")


def _parse_card_instance_ids_field(
    data: Mapping[str, object],
    field: str,
    event_type: str,
) -> tuple[CardInstanceId, ...]:
    return _parse_card_instance_ids(data.get(field), context=f"{event_type}.{field}")


def _parse_players(raw_value: object) -> tuple[PlayerState, PlayerState]:
    entries = _require_sequence(raw_value, context="game_state.players")
    players = tuple(_parse_player_state(entry, index=index) for index, entry in enumerate(entries))
    if len(players) != 2:
        raise SerializationError("game_state.players must contain exactly two entries.")
    return players


def _parse_player_state(raw_value: object, *, index: int) -> PlayerState:
    entry = _require_mapping(raw_value, context=f"player[{index}]")
    with _translate_value_error(f"player[{index}]"):
        return PlayerState(
            player_id=PlayerId(_require_str(entry, "player_id", context=f"player[{index}]")),
            faction=_parse_enum(
                FactionId,
                _require_str(entry, "faction", context=f"player[{index}]"),
                context=f"player[{index}].faction",
            ),
            leader=_parse_leader_state(entry.get("leader"), context=f"player[{index}].leader"),
            deck=_parse_card_instance_ids(entry.get("deck"), context=f"player[{index}].deck"),
            hand=_parse_card_instance_ids(entry.get("hand"), context=f"player[{index}].hand"),
            discard=_parse_card_instance_ids(
                entry.get("discard"),
                context=f"player[{index}].discard",
            ),
            rows=_parse_row_state(entry.get("rows"), context=f"player[{index}].rows"),
            gems_remaining=_require_int(entry, "gems_remaining", context=f"player[{index}]"),
            round_wins=_require_int(entry, "round_wins", context=f"player[{index}]"),
            has_passed=_require_bool(entry, "has_passed", context=f"player[{index}]"),
        )


def _parse_leader_state(raw_value: object, *, context: str) -> LeaderState:
    entry = _require_mapping(raw_value, context=context)
    with _translate_value_error(context):
        return LeaderState(
            leader_id=LeaderId(_require_str(entry, "leader_id", context=context)),
            used=_require_bool(entry, "used", context=context),
            disabled=_require_bool(entry, "disabled", context=context),
            horn_row=_parse_optional_enum(
                Row,
                entry.get("horn_row"),
                context=f"{context}.horn_row",
            ),
        )


def _parse_row_state(raw_value: object, *, context: str) -> RowState:
    entry = _require_mapping(raw_value, context=context)
    with _translate_value_error(context):
        return RowState(
            close=_parse_card_instance_ids(entry.get("close"), context=f"{context}.close"),
            ranged=_parse_card_instance_ids(entry.get("ranged"), context=f"{context}.ranged"),
            siege=_parse_card_instance_ids(entry.get("siege"), context=f"{context}.siege"),
        )


def _parse_optional_row_state(raw_value: object, *, context: str) -> RowState:
    if raw_value is None:
        return RowState()
    return _parse_row_state(raw_value, context=context)


def _parse_pending_avenger_summons(
    raw_value: object,
    *,
    context: str,
) -> tuple[PendingAvengerSummon, ...]:
    if raw_value is None:
        return ()
    entries = _require_sequence(raw_value, context=context)
    summons: list[PendingAvengerSummon] = []
    for index, raw_entry in enumerate(entries):
        entry = _require_mapping(raw_entry, context=f"{context}[{index}]")
        summons.append(
            PendingAvengerSummon(
                source_card_instance_id=CardInstanceId(
                    _require_str(entry, "source_card_instance_id", context=f"{context}[{index}]")
                ),
                summoned_definition_id=CardDefinitionId(
                    _require_str(entry, "summoned_definition_id", context=f"{context}[{index}]")
                ),
                owner=PlayerId(_require_str(entry, "owner", context=f"{context}[{index}]")),
                battlefield_side=PlayerId(
                    _require_str(entry, "battlefield_side", context=f"{context}[{index}]")
                ),
                row=_parse_enum(
                    Row,
                    _require_str(entry, "row", context=f"{context}[{index}]"),
                    context=f"{context}[{index}].row",
                ),
            )
        )
    return tuple(summons)


def _parse_pending_choice(raw_value: object, *, context: str) -> PendingChoice | None:
    if raw_value is None:
        return None
    entry = _require_mapping(raw_value, context=context)
    with _translate_value_error(context):
        return PendingChoice(
            choice_id=ChoiceId(_require_str(entry, "choice_id", context=context)),
            player_id=PlayerId(_require_str(entry, "player_id", context=context)),
            kind=_parse_enum(
                ChoiceKind,
                _require_str(entry, "kind", context=context),
                context=f"{context}.kind",
            ),
            source_kind=_parse_enum(
                ChoiceSourceKind,
                _require_str(entry, "source_kind", context=context),
                context=f"{context}.source_kind",
            ),
            source_card_instance_id=_parse_optional_card_instance_id(
                entry.get("source_card_instance_id"),
                context=f"{context}.source_card_instance_id",
            ),
            source_leader_id=_parse_optional_leader_id(
                entry.get("source_leader_id"),
                context=f"{context}.source_leader_id",
            ),
            legal_target_card_instance_ids=_parse_card_instance_ids(
                entry.get("legal_target_card_instance_ids"),
                context=f"{context}.legal_target_card_instance_ids",
            ),
            legal_rows=tuple(
                _parse_enum(
                    Row,
                    _require_str(row, context=context),
                    context=f"{context}.legal_rows",
                )
                for row in _require_sequence(
                    entry.get("legal_rows"), context=f"{context}.legal_rows"
                )
            ),
            min_selections=_require_int(entry, "min_selections", context=context),
            max_selections=_require_int(entry, "max_selections", context=context),
            source_row=_parse_optional_enum(
                Row,
                entry.get("source_row"),
                context=f"{context}.source_row",
            ),
        )


def _parse_card_instances(raw_value: object) -> tuple[CardInstance, ...]:
    entries = _require_sequence(raw_value, context="game_state.card_instances")
    return tuple(_parse_card_instance(entry, index=index) for index, entry in enumerate(entries))


def _parse_card_instance(raw_value: object, *, index: int) -> CardInstance:
    entry = _require_mapping(raw_value, context=f"card_instance[{index}]")
    with _translate_value_error(f"card_instance[{index}]"):
        return CardInstance(
            instance_id=CardInstanceId(
                _require_str(entry, "instance_id", context=f"card_instance[{index}]")
            ),
            definition_id=CardDefinitionId(
                _require_str(entry, "definition_id", context=f"card_instance[{index}]")
            ),
            owner=PlayerId(_require_str(entry, "owner", context=f"card_instance[{index}]")),
            zone=_parse_enum(
                Zone,
                _require_str(entry, "zone", context=f"card_instance[{index}]"),
                context=f"card_instance[{index}].zone",
            ),
            row=_parse_optional_enum(
                Row,
                entry.get("row"),
                context=f"card_instance[{index}].row",
            ),
            battlefield_side=_parse_optional_player_id(
                entry.get("battlefield_side"),
                context=f"card_instance[{index}].battlefield_side",
            ),
        )


def _parse_player_scores(
    raw_value: object,
    *,
    context: str,
) -> tuple[tuple[PlayerId, int], tuple[PlayerId, int]]:
    entries = _require_sequence(raw_value, context=context)
    scores = tuple(
        _parse_player_score(entry, index=index, context=context)
        for index, entry in enumerate(entries)
    )
    if len(scores) != 2:
        raise SerializationError(f"{context} must contain exactly two player scores.")
    return scores


def _parse_player_score(
    raw_value: object,
    *,
    index: int,
    context: str,
) -> tuple[PlayerId, int]:
    entry = _require_mapping(raw_value, context=f"{context}[{index}]")
    return (
        PlayerId(_require_str(entry, "player_id", context=f"{context}[{index}]")),
        _require_int(entry, "score", context=f"{context}[{index}]"),
    )


def _parse_card_instance_ids(raw_value: object, *, context: str) -> tuple[CardInstanceId, ...]:
    entries = _require_sequence(raw_value, context=context)
    return tuple(CardInstanceId(_require_str(entry, context=context)) for entry in entries)


def _parse_optional_player_id(raw_value: object, *, context: str) -> PlayerId | None:
    return _parse_optional_newtype(raw_value, constructor=PlayerId, context=context)


def _parse_optional_card_instance_id(
    raw_value: object,
    *,
    context: str,
) -> CardInstanceId | None:
    return _parse_optional_newtype(raw_value, constructor=CardInstanceId, context=context)


def _parse_optional_leader_id(raw_value: object, *, context: str) -> LeaderId | None:
    return _parse_optional_newtype(raw_value, constructor=LeaderId, context=context)


def _parse_optional_newtype[T](
    raw_value: object,
    *,
    constructor: Callable[[str], T],
    context: str,
) -> T | None:
    if raw_value is None:
        return None
    return constructor(_require_str(raw_value, context=context))


def _parse_optional_enum[EnumT: StrEnum](
    enum_type: type[EnumT],
    raw_value: object,
    *,
    context: str,
) -> EnumT | None:
    if raw_value is None:
        return None
    return _parse_enum(enum_type, _require_str(raw_value, context=context), context=context)


def _parse_optional_int(raw_value: object, *, context: str) -> int | None:
    return expect_optional_int(raw_value, context=context, error_factory=SerializationError)


def _parse_enum[EnumT: StrEnum](enum_type: type[EnumT], raw_value: str, *, context: str) -> EnumT:
    for member in enum_type:
        if member.value == raw_value:
            return member
    raise SerializationError(f"Unknown {context} value: {raw_value!r}")


def _translate_value_error(context: str) -> TranslatedExceptionContext:
    return translate_exception_context(
        ValueError,
        lambda exc: SerializationError(f"Invalid serialized {context}: {exc}"),
    )


def _validate_root(
    data: Mapping[str, object],
    *,
    expected_type: str | None,
    context: str,
) -> None:
    schema_version = _require_int(data, "schema_version", context=context)
    if schema_version != SCHEMA_VERSION:
        raise SerializationError(
            f"{context} schema_version must be {SCHEMA_VERSION}, found {schema_version}."
        )
    if expected_type is not None and _require_str(data, "type", context=context) != expected_type:
        raise SerializationError(
            f"{context} type must be {expected_type!r}, found {data.get('type')!r}."
        )


def _require_mapping(raw_value: object, *, context: str) -> Mapping[str, object]:
    return expect_mapping(raw_value, context=context, error_factory=SerializationError)


def _require_sequence(raw_value: object, *, context: str) -> Sequence[object]:
    return expect_sequence(raw_value, context=context, error_factory=SerializationError)


def _require_str(
    raw_value: object | Mapping[str, object],
    field: str | None = None,
    *,
    context: str,
) -> str:
    if field is not None and isinstance(raw_value, Mapping):
        mapping = cast(Mapping[str, object], raw_value)
        return require_str_field(
            mapping,
            field,
            context=context,
            error_factory=SerializationError,
        )
    return expect_str(raw_value, context=context, error_factory=SerializationError)


def _require_int(mapping: Mapping[str, object], field: str, *, context: str) -> int:
    return require_int_field(
        mapping,
        field,
        context=context,
        error_factory=SerializationError,
    )


def _require_bool(mapping: Mapping[str, object], field: str, *, context: str) -> bool:
    return require_bool_field(
        mapping,
        field,
        context=context,
        error_factory=SerializationError,
    )
