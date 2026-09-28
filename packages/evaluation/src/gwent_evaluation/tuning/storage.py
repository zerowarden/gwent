"""Single-writer study storage with immutable, chained journal entries."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast, final

from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.provenance import canonical_digest, canonical_json
from gwent_evaluation.records import CorruptRecordError, parse_record_mapping
from gwent_evaluation.storage import RunConflictError, atomic_write_text, read_record_mapping


class StudyLockedError(RunConflictError):
    """An active writer or an unrecovered abandoned writer owns the study."""


@dataclass(frozen=True, slots=True)
class JournalEntry:
    kind: str
    payload: Mapping[str, object]
    digest: str


def read_checked_document(path: Path) -> Mapping[str, object]:
    document = dict(read_record_mapping(path))
    digest = document.pop("record_digest", None)
    if canonical_digest(document) != digest:
        raise CorruptRecordError(f"Study record checksum mismatch: {path}")
    return document


def write_checked_document(path: Path, payload: Mapping[str, object]) -> str:
    digest = canonical_digest(payload)
    atomic_write_text(path, dump_pretty_json({**payload, "record_digest": digest}))
    return digest


@contextmanager
def exclusive_writer(root: Path, *, recover_lock: bool = False) -> Generator[None]:
    """Lock a persistent inode; process death requires explicit marker recovery.

    Recovery never displaces an active kernel lock. Keep this lock file in place
    even while idle, since another process may already hold its open descriptor.
    """
    root.mkdir(parents=True, exist_ok=True)
    with (root / "writer.lock").open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise StudyLockedError("A writer already owns this study.") from error
        try:
            _ = handle.seek(0)
            marker = handle.read()
            if marker and not recover_lock:
                try:
                    owner = parse_record_mapping(marker, context="study writer marker")
                except ValueError as error:
                    raise StudyLockedError(
                        "Interrupted writer marker; recover_lock is required."
                    ) from error
                if owner.get("active") is not False:
                    raise StudyLockedError("Abandoned writer; recover_lock is required.")

            def mark(active: bool) -> None:
                _ = handle.seek(0)
                _ = handle.truncate()
                _ = handle.write(dump_pretty_json({"active": active, "pid": os.getpid()}))
                handle.flush()
                os.fsync(handle.fileno())

            mark(True)
            try:
                yield
            finally:
                mark(False)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@final
class StudyStore:
    def __init__(self, root: Path, *, verification_only: bool = False) -> None:
        self.root = root
        self.verification_only = verification_only
        self._locked = False
        self._entries: list[JournalEntry] = []
        self._cursor = 0
        self._previous: str | None = None

    @contextmanager
    def writer(self, *, recover_lock: bool = False) -> Generator[None]:
        with exclusive_writer(self.root, recover_lock=recover_lock):
            self._locked = True
            try:
                yield
            finally:
                self._locked = False

    def _require_writer(self) -> None:
        if not self._locked:
            raise StudyLockedError("Study mutation requires the writer lock.")

    def prepare(self, snapshot: Mapping[str, object]) -> None:
        self._require_writer()
        path = self.root / "snapshot.json"
        payload = {"schema_version": 1, "snapshot": snapshot}
        if path.exists():
            if canonical_json(read_checked_document(path)) != canonical_json(payload):
                raise RunConflictError("Study snapshot differs from its frozen inputs.")
        else:
            if self.verification_only:
                raise RunConflictError("A completed study snapshot is required.")
            runs = self.root / "runs"
            if any((self.root / "journal").glob("*.json")) or (
                runs.exists() and any(runs.iterdir())
            ):
                raise CorruptRecordError("Study data exists without a committed snapshot.")
            _ = write_checked_document(path, payload)
        self._previous = canonical_digest(payload)
        self._entries = []
        self._cursor = 0
        for index, entry_path in enumerate(sorted((self.root / "journal").glob("*.json"))):
            if entry_path.name != f"{index:08d}.json":
                raise CorruptRecordError("Study journal has missing or unexpected entries.")
            document = read_checked_document(entry_path)
            if (
                set(document) != {"schema_version", "index", "previous", "kind", "payload"}
                or type(document["schema_version"]) is not int
                or document["schema_version"] != 1
                or type(document["index"]) is not int
                or document["index"] != index
                or document["previous"] != self._previous
                or not isinstance(document["kind"], str)
                or not isinstance(document["payload"], dict)
            ):
                raise CorruptRecordError(f"Invalid study journal entry: {entry_path}")
            body = parse_record_mapping(
                canonical_json(cast(dict[str, object], document["payload"])),
                context=str(entry_path),
            )
            digest = canonical_digest(document)
            self._entries.append(JournalEntry(document["kind"], body, digest))
            self._previous = digest

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        """Checksum-verified entries from the prepared snapshot."""
        return tuple(self._entries)

    @property
    def next_entry(self) -> JournalEntry | None:
        return self._entries[self._cursor] if self._cursor < len(self._entries) else None

    def record(self, kind: str, payload: Mapping[str, object]) -> str:
        """Verify the next committed event or append it once at the journal tail."""
        self._require_writer()
        existing = self.next_entry
        if existing is not None:
            if existing.kind != kind or canonical_json(existing.payload) != canonical_json(payload):
                raise RunConflictError(f"Study replay conflicts at entry {self._cursor} ({kind}).")
            self._cursor += 1
            return existing.digest
        if self._previous is None:
            raise RunConflictError("Prepare the study before journaling.")
        if self.verification_only:
            raise RunConflictError("The study is incomplete; verification cannot append events.")
        document = {
            "schema_version": 1,
            "index": self._cursor,
            "previous": self._previous,
            "kind": kind,
            "payload": payload,
        }
        path = self.root / "journal" / f"{self._cursor:08d}.json"
        if path.exists():
            raise RunConflictError(f"Refusing to replace a committed study entry: {path}")
        digest = write_checked_document(path, document)
        self._entries.append(JournalEntry(kind, payload, digest))
        self._cursor += 1
        self._previous = digest
        return digest

    def finish(self) -> None:
        if self.next_entry is not None:
            raise RunConflictError("Study journal contains events after stage completion.")

    def write_report(self, report: Mapping[str, object]) -> None:
        self._require_writer()
        atomic_write_text(self.root / "report.json", dump_pretty_json(report))
