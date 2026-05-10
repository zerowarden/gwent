from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from gwent_shared.error_translation import translate_exception

from gwent_service.application.errors import MatchAlreadyExistsError, MatchNotFoundError
from gwent_service.domain.models import StoredMatch
from gwent_service.infrastructure.sqlite.payloads import (
    deserialize_stored_match,
    serialize_stored_match,
)


class SQLiteMatchRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path: Path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def create(self, stored_match: StoredMatch) -> None:
        payload = serialize_stored_match(stored_match)
        with closing(self._connect()) as connection, connection:
            _ = translate_exception(
                lambda: connection.execute(
                    """
                    INSERT INTO matches (
                        match_id,
                        state_payload,
                        event_log_payloads,
                        player_slots,
                        staged_mulligans,
                        version,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                ),
                sqlite3.IntegrityError,
                lambda _exc: MatchAlreadyExistsError(stored_match.match_id),
            )

    def get(self, match_id: str) -> StoredMatch | None:
        with closing(self._connect()) as connection:
            row = cast(
                sqlite3.Row | None,
                connection.execute(
                    """
                    SELECT
                        match_id,
                        state_payload,
                        event_log_payloads,
                        player_slots,
                        staged_mulligans,
                        version,
                        created_at,
                        updated_at
                    FROM matches
                    WHERE match_id = ?
                    """,
                    (match_id,),
                ).fetchone(),
            )
        if row is None:
            return None
        return deserialize_stored_match(row)

    def update(self, stored_match: StoredMatch) -> None:
        payload = serialize_stored_match(stored_match)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE matches
                SET
                    state_payload = ?,
                    event_log_payloads = ?,
                    player_slots = ?,
                    staged_mulligans = ?,
                    version = ?,
                    created_at = ?,
                    updated_at = ?
                WHERE match_id = ?
                """,
                (
                    payload[1],
                    payload[2],
                    payload[3],
                    payload[4],
                    payload[5],
                    payload[6],
                    payload[7],
                    payload[0],
                ),
            )
            if cursor.rowcount == 0:
                raise MatchNotFoundError(stored_match.match_id)

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
