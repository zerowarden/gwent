from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from typing import cast

from gwent_shared.extract import (
    expect_constructor_sequence,
    expect_enum,
    expect_mapping,
    expect_optional_constructor,
    expect_optional_enum,
    expect_optional_int,
    expect_sequence,
    expect_str,
    require_bool_field,
    require_int_field,
    require_str_field,
)

from gwent_engine.cards import CardRegistry
from gwent_engine.core import (
    ChoiceKind,
    ChoiceSourceKind,
    FactionId,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.errors import SerializationError
from gwent_engine.core.ids import (
    CardDefinitionId,
    CardInstanceId,
    ChoiceId,
    GameId,
    LeaderId,
    PlayerId,
    card_instance_id,
    leader_id,
    player_id,
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


def game_state_from_dict(
    data: Mapping[str, object],
    *,
    card_registry: CardRegistry | None = None,
) -> GameState:
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
    check_game_state_invariants(state, card_registry=card_registry)
    return state


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


def _parse_card_instance_ids(raw_value: object, *, context: str) -> tuple[CardInstanceId, ...]:
    return expect_constructor_sequence(
        raw_value, card_instance_id, context=context, error_factory=SerializationError
    )


def _parse_optional_player_id(raw_value: object, *, context: str) -> PlayerId | None:
    return expect_optional_constructor(
        raw_value, player_id, context=context, error_factory=SerializationError
    )


def _parse_optional_card_instance_id(
    raw_value: object,
    *,
    context: str,
) -> CardInstanceId | None:
    return expect_optional_constructor(
        raw_value, card_instance_id, context=context, error_factory=SerializationError
    )


def _parse_optional_leader_id(raw_value: object, *, context: str) -> LeaderId | None:
    return expect_optional_constructor(
        raw_value, leader_id, context=context, error_factory=SerializationError
    )


def _parse_optional_enum[EnumT: StrEnum](
    enum_type: type[EnumT],
    raw_value: object,
    *,
    context: str,
) -> EnumT | None:
    return expect_optional_enum(
        raw_value, enum_type, context=context, error_factory=SerializationError
    )


def _parse_optional_int(raw_value: object, *, context: str) -> int | None:
    return expect_optional_int(raw_value, context=context, error_factory=SerializationError)


def _parse_enum[EnumT: StrEnum](enum_type: type[EnumT], raw_value: str, *, context: str) -> EnumT:
    return expect_enum(raw_value, enum_type, context=context, error_factory=SerializationError)


@contextmanager
def _translate_value_error(context: str) -> Generator[None, None, None]:
    try:
        yield
    except ValueError as exc:
        raise SerializationError(f"Invalid serialized {context}: {exc}") from exc


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
