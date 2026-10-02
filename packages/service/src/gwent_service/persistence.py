"""Match repository implementations: in-memory and SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import NoReturn, cast

from gwent_shared import (
    dump_json,
    expect_int,
    expect_mapping,
    expect_sequence,
    expect_str,
    require_str_field,
)
from gwent_shared.json_payloads import load_json_list, load_json_mapping, load_json_object_list

from gwent_service.domain import (
    MatchAlreadyExistsError,
    MatchNotFoundError,
    MatchVersionConflictError,
    StagedMulliganSubmission,
    StoredMatch,
    StoredPlayerSlot,
)


class InMemoryMatchRepository:
    def __init__(self) -> None:
        self._matches: dict[str, StoredMatch] = {}
        self._lock: Lock = Lock()

    def create(self, stored_match: StoredMatch) -> None:
        with self._lock:
            if stored_match.match_id in self._matches:
                raise MatchAlreadyExistsError(stored_match.match_id)
            self._matches[stored_match.match_id] = deepcopy(stored_match)

    def get(self, match_id: str) -> StoredMatch | None:
        with self._lock:
            stored_match = self._matches.get(match_id)
            if stored_match is None:
                return None
            return deepcopy(stored_match)

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None:
        with self._lock:
            current_match = self._matches.get(stored_match.match_id)
            if current_match is None:
                raise MatchNotFoundError(stored_match.match_id)
            if current_match.version != expected_version:
                raise MatchVersionConflictError(
                    stored_match.match_id,
                    expected_version=expected_version,
                    actual_version=current_match.version,
                )
            self._matches[stored_match.match_id] = deepcopy(stored_match)


MATCH_COLUMNS: tuple[str, ...] = (
    "match_id",
    "state_payload",
    "event_log_payloads",
    "player_slots",
    "staged_mulligans",
    "version",
    "created_at",
    "updated_at",
)


def serialize_stored_match(stored_match: StoredMatch) -> dict[str, object]:
    return {
        "match_id": stored_match.match_id,
        "state_payload": dump_json(stored_match.state_payload),
        "event_log_payloads": dump_json(stored_match.event_log_payloads),
        "player_slots": dump_json(
            [
                {
                    "service_player_id": slot.service_player_id,
                    "engine_player_id": slot.engine_player_id,
                    "deck_id": slot.deck_id,
                }
                for slot in stored_match.player_slots
            ]
        ),
        "staged_mulligans": dump_json(
            [
                {
                    "engine_player_id": submission.engine_player_id,
                    "card_instance_ids": list(submission.card_instance_ids),
                }
                for submission in stored_match.staged_mulligans
            ]
        ),
        "version": stored_match.version,
        "created_at": stored_match.created_at.isoformat(),
        "updated_at": stored_match.updated_at.isoformat(),
    }


def row_field(row: sqlite3.Row, column: str) -> object:
    return cast(object, row[column])


def deserialize_stored_match(row: sqlite3.Row) -> StoredMatch:
    player_slots_payload = load_json_list(
        row_field(row, "player_slots"),
        context="sqlite.player_slots",
    )
    staged_mulligans_payload = load_json_list(
        row_field(row, "staged_mulligans"),
        context="sqlite.staged_mulligans",
    )
    player_slots = tuple(
        deserialize_player_slot(slot_payload) for slot_payload in player_slots_payload
    )
    if len(player_slots) != 2:
        raise TypeError("Expected exactly two serialized player slots.")
    return StoredMatch(
        match_id=expect_str(row_field(row, "match_id"), context="sqlite.match_id"),
        state_payload=load_json_mapping(
            row_field(row, "state_payload"),
            context="sqlite.state_payload",
        ),
        event_log_payloads=tuple(
            load_json_object_list(
                row_field(row, "event_log_payloads"),
                context="sqlite.event_log_payloads",
            )
        ),
        player_slots=(player_slots[0], player_slots[1]),
        staged_mulligans=tuple(
            deserialize_staged_mulligan(submission_payload)
            for submission_payload in staged_mulligans_payload
        ),
        version=expect_int(row_field(row, "version"), context="sqlite.version"),
        created_at=datetime.fromisoformat(
            expect_str(row_field(row, "created_at"), context="sqlite.created_at")
        ),
        updated_at=datetime.fromisoformat(
            expect_str(row_field(row, "updated_at"), context="sqlite.updated_at")
        ),
    )


def deserialize_player_slot(payload: object) -> StoredPlayerSlot:
    context = "sqlite.player_slot"
    player_slot_payload = expect_mapping(payload, context=context)
    return StoredPlayerSlot(
        service_player_id=require_str_field(
            player_slot_payload, "service_player_id", context=context
        ),
        engine_player_id=require_str_field(
            player_slot_payload, "engine_player_id", context=context
        ),
        deck_id=require_str_field(player_slot_payload, "deck_id", context=context),
    )


def deserialize_staged_mulligan(payload: object) -> StagedMulliganSubmission:
    context = "sqlite.staged_mulligan"
    staged_mulligan_payload = expect_mapping(payload, context=context)
    card_instance_ids = expect_sequence(
        staged_mulligan_payload.get("card_instance_ids", []),
        context=f"{context}.card_instance_ids",
    )
    return StagedMulliganSubmission(
        engine_player_id=require_str_field(
            staged_mulligan_payload, "engine_player_id", context=context
        ),
        card_instance_ids=tuple(
            expect_str(card_instance_id, context=f"{context}.card_instance_ids")
            for card_instance_id in card_instance_ids
        ),
    )


_NAMED_COLUMNS = ", ".join(MATCH_COLUMNS)
_PLACEHOLDERS = ", ".join(f":{column}" for column in MATCH_COLUMNS)
_UPDATED_COLUMNS = ",\n                    ".join(
    f"{column} = :{column}" for column in MATCH_COLUMNS if column != "match_id"
)


class SQLiteMatchRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path: Path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def create(self, stored_match: StoredMatch) -> None:
        payload = serialize_stored_match(stored_match)
        with closing(self._connect()) as connection, connection:
            try:
                _ = connection.execute(
                    f"INSERT INTO matches ({_NAMED_COLUMNS}) VALUES ({_PLACEHOLDERS})",
                    payload,
                )
            except sqlite3.IntegrityError as exc:
                raise MatchAlreadyExistsError(stored_match.match_id) from exc

    def get(self, match_id: str) -> StoredMatch | None:
        with closing(self._connect()) as connection:
            row = cast(
                sqlite3.Row | None,
                connection.execute(
                    f"SELECT {_NAMED_COLUMNS} FROM matches WHERE match_id = ?",
                    (match_id,),
                ).fetchone(),
            )
        if row is None:
            return None
        return deserialize_stored_match(row)

    def update(self, stored_match: StoredMatch, *, expected_version: int) -> None:
        payload = serialize_stored_match(stored_match)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                f"""
                UPDATE matches
                SET
                    {_UPDATED_COLUMNS}
                WHERE match_id = :match_id AND version = :expected_version
                """,
                {**payload, "expected_version": expected_version},
            )
            if cursor.rowcount == 0:
                self._raise_update_failure(connection, stored_match.match_id, expected_version)

    @staticmethod
    def _raise_update_failure(
        connection: sqlite3.Connection,
        match_id: str,
        expected_version: int,
    ) -> NoReturn:
        existing = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT version FROM matches WHERE match_id = ?",
                (match_id,),
            ).fetchone(),
        )
        if existing is None:
            raise MatchNotFoundError(match_id)
        raise MatchVersionConflictError(
            match_id,
            expected_version=expected_version,
            actual_version=expect_int(row_field(existing, "version"), context="sqlite.version"),
        )

    def _initialize_schema(self) -> None:
        with closing(self._connect()) as connection, connection:
            _ = connection.execute(
                """
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY,
                    state_payload TEXT NOT NULL,
                    event_log_payloads TEXT NOT NULL,
                    player_slots TEXT NOT NULL,
                    staged_mulligans TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
