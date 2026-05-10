from __future__ import annotations

from collections.abc import Mapping

from gwent_shared.extract import (
    expect_mapping,
    expect_optional_int,
    require_int_field,
    require_sequence_field,
    require_str_field,
)


def state_phase(state_payload: Mapping[str, object]) -> str:
    return require_str_field(state_payload, "phase", context="game_state")


def state_rng_seed(state_payload: Mapping[str, object]) -> int | None:
    return expect_optional_int(
        state_payload.get("rng_seed"),
        context="game_state",
        label="rng_seed",
    )


def state_event_counter(state_payload: Mapping[str, object]) -> int:
    return require_int_field(state_payload, "event_counter", context="game_state")


def state_player_order(state_payload: Mapping[str, object]) -> tuple[str, str]:
    players = require_sequence_field(state_payload, "players", context="game_state")
    if len(players) != 2:
        raise TypeError("Expected serialized state to contain exactly two player payloads.")
    player_ids = tuple(
        require_str_field(
            expect_mapping(player_payload, context="player"),
            "player_id",
            context="player",
        )
        for player_payload in players
    )
    return (player_ids[0], player_ids[1])


def state_players_by_engine_id(
    state_payload: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    return _state_payloads_by_key(
        state_payload,
        field_name="players",
        item_context="player",
        key_field="player_id",
        key_context="player",
    )


def state_card_instances_by_id(
    state_payload: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    return _state_payloads_by_key(
        state_payload,
        field_name="card_instances",
        item_context="card_instance",
        key_field="instance_id",
        key_context="card",
    )


def _state_payloads_by_key(
    state_payload: Mapping[str, object],
    *,
    field_name: str,
    item_context: str,
    key_field: str,
    key_context: str,
) -> dict[str, Mapping[str, object]]:
    payloads = require_sequence_field(state_payload, field_name, context="game_state")
    indexed: dict[str, Mapping[str, object]] = {}
    for payload in payloads:
        payload_mapping = expect_mapping(payload, context=item_context)
        indexed[require_str_field(payload_mapping, key_field, context=key_context)] = (
            payload_mapping
        )
    return indexed
