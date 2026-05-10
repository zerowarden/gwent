from __future__ import annotations

import sqlite3
from datetime import datetime

from gwent_shared import dump_json, expect_int, expect_mapping, expect_sequence, expect_str
from gwent_shared.json_payloads import load_json_list, load_json_mapping, load_json_object_list

from gwent_service.domain.models import (
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)


def serialize_stored_match(stored_match: StoredMatch) -> tuple[object, ...]:
    return (
        stored_match.match_id,
        dump_json(stored_match.state_payload),
        dump_json(stored_match.event_log_payloads),
        dump_json(
            [
                {
                    "service_player_id": slot.service_player_id,
                    "engine_player_id": slot.engine_player_id,
                    "deck_id": slot.deck_id,
                }
                for slot in stored_match.player_slots
            ]
        ),
        dump_json(
            [
                {
                    "engine_player_id": submission.engine_player_id,
                    "card_instance_ids": list(submission.card_instance_ids),
                }
                for submission in stored_match.staged_mulligans
            ]
        ),
        stored_match.version,
        stored_match.created_at.isoformat(),
        stored_match.updated_at.isoformat(),
    )


def deserialize_stored_match(row: sqlite3.Row) -> StoredMatch:
    player_slots_payload = load_json_list(row["player_slots"], context="sqlite.player_slots")
    staged_mulligans_payload = load_json_list(
        row["staged_mulligans"],
        context="sqlite.staged_mulligans",
    )
    player_slots = tuple(
        deserialize_player_slot(slot_payload) for slot_payload in player_slots_payload
    )
    if len(player_slots) != 2:
        raise TypeError("Expected exactly two serialized player slots.")
    return StoredMatch(
        match_id=expect_str(row["match_id"], context="sqlite.match_id"),
        state_payload=load_json_mapping(row["state_payload"], context="sqlite.state_payload"),
        event_log_payloads=tuple(
            load_json_object_list(row["event_log_payloads"], context="sqlite.event_log_payloads")
        ),
        player_slots=(player_slots[0], player_slots[1]),
        staged_mulligans=tuple(
            deserialize_staged_mulligan(submission_payload)
            for submission_payload in staged_mulligans_payload
        ),
        version=expect_int(row["version"], context="sqlite.version"),
        created_at=datetime.fromisoformat(
            expect_str(row["created_at"], context="sqlite.created_at")
        ),
        updated_at=datetime.fromisoformat(
            expect_str(row["updated_at"], context="sqlite.updated_at")
        ),
    )


def deserialize_player_slot(payload: object) -> StoredPlayerSlot:
    player_slot_payload = expect_mapping(payload, context="sqlite.player_slot")
    return StoredPlayerSlot(
        service_player_id=expect_str(
            player_slot_payload.get("service_player_id"),
            context="sqlite.player_slot",
            label="service_player_id",
        ),
        engine_player_id=expect_str(
            player_slot_payload.get("engine_player_id"),
            context="sqlite.player_slot",
            label="engine_player_id",
        ),
        deck_id=expect_str(
            player_slot_payload.get("deck_id"),
            context="sqlite.player_slot",
            label="deck_id",
        ),
    )


def deserialize_staged_mulligan(payload: object) -> StagedMulliganSubmission:
    staged_mulligan_payload = expect_mapping(payload, context="sqlite.staged_mulligan")
    card_instance_ids = expect_sequence(
        staged_mulligan_payload.get("card_instance_ids", []),
        context="sqlite.staged_mulligan.card_instance_ids",
    )
    return StagedMulliganSubmission(
        engine_player_id=expect_str(
            staged_mulligan_payload.get("engine_player_id"),
            context="sqlite.staged_mulligan",
            label="engine_player_id",
        ),
        card_instance_ids=tuple(
            expect_str(
                card_instance_id,
                context="sqlite.staged_mulligan.card_instance_ids",
            )
            for card_instance_id in card_instance_ids
        ),
    )
