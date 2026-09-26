"""Atomic on-disk storage for experiment runs.

Record ⇄ dict conversion lives in `gwent_evaluation.records`; this module owns
the run directory layout, atomic writes, digest verification, and conflict
detection.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gwent_engine.cards import CardRegistry
from gwent_shared.extract import require_sequence_field, require_str_field
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.assets import resolve_assets
from gwent_evaluation.models import (
    EvidenceRefs,
    MatchEvidence,
    MatchResult,
    RunManifest,
    ScheduledMatch,
    TrajectoryStep,
)
from gwent_evaluation.provenance import canonical_digest, canonical_json, file_digest
from gwent_evaluation.records import (
    CorruptRecordError,
    StorageError,
    decision_sample_to_dict,
    match_result_from_dict,
    parse_record_mapping,
    record_to_dict,
    run_manifest_from_dict,
    scheduled_match_from_dict,
    trajectory_step_from_dict,
    trajectory_step_to_dict,
)
from gwent_evaluation.validation import LoadedRun, validate_loaded_run, validate_trajectory


class RunConflictError(StorageError):
    """Raised when a run directory does not match the requested run."""


@dataclass(frozen=True, slots=True)
class RunStore:
    """Owns the on-disk layout of one experiment run."""

    output_root: Path
    run_id: str

    @classmethod
    def from_root(cls, root: Path) -> RunStore:
        return cls(output_root=root.parent, run_id=root.name)

    @property
    def root(self) -> Path:
        return self.output_root / self.run_id

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def schedule_path(self) -> Path:
        return self.root / "schedule.jsonl"

    @property
    def matches_dir(self) -> Path:
        return self.root / "matches"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    @property
    def report_path(self) -> Path:
        return self.root / "report.json"

    @property
    def report_markdown_path(self) -> Path:
        return self.root / "report.md"

    def result_path(self, case_id: str) -> Path:
        return self.matches_dir / f"{case_id}.json"

    def samples_path(self, case_id: str) -> Path:
        return self.evidence_dir / f"{case_id}.samples.jsonl"

    def trajectory_path(self, case_id: str) -> Path:
        return self.evidence_dir / f"{case_id}.trajectory.json"

    def prepare(self, manifest: RunManifest, *, matches: tuple[ScheduledMatch, ...]) -> LoadedRun:
        identity = run_manifest_identity(manifest)
        if self.root.exists():
            loaded = self.load()
            if run_manifest_identity(loaded.manifest) != identity or loaded.matches != matches:
                raise RunConflictError(
                    f"Run {self.run_id!r} already exists with a different manifest."
                )
            return loaded
        validate_loaded_run(LoadedRun(manifest, matches, {}))
        self.matches_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            self.manifest_path,
            dump_pretty_json({"manifest_identity": identity, **record_to_dict(manifest)}),
        )
        _atomic_write_text(
            self.schedule_path,
            "".join(canonical_json(record_to_dict(match)) + "\n" for match in matches),
        )

        return LoadedRun(manifest, matches, {})

    def read_manifest(self) -> RunManifest:
        if not self.manifest_path.exists():
            raise CorruptRecordError(f"Run directory {self.root} has no manifest.")
        document = _read_record_mapping(self.manifest_path)
        identity = require_str_field(
            document,
            "manifest_identity",
            context=str(self.manifest_path),
            error_factory=StorageError,
        )
        payload = {key: value for key, value in document.items() if key != "manifest_identity"}
        try:
            manifest = run_manifest_from_dict(payload)
        except ValueError as error:
            raise CorruptRecordError(str(error)) from error
        if run_manifest_identity(manifest) != identity:
            raise CorruptRecordError(f"Manifest identity mismatch for {self.manifest_path}.")
        return manifest

    def read_result(self, case_id: str) -> MatchResult | None:
        return self.load().results.get(case_id)

    def _read_result(self, case_id: str) -> MatchResult | None:
        path = self.result_path(case_id)
        if not path.exists():
            return None
        document = _read_record_mapping(path)
        digest = require_str_field(
            document,
            "record_digest",
            context=str(path),
            error_factory=StorageError,
        )
        payload = {key: value for key, value in document.items() if key != "record_digest"}
        if canonical_digest(payload) != digest:
            raise CorruptRecordError(f"Record digest mismatch for {path}.")
        try:
            result = match_result_from_dict(payload)
        except ValueError as error:
            raise CorruptRecordError(str(error)) from error
        if result.case_id != case_id:
            raise CorruptRecordError(f"Record case id mismatch for {path}: {result.case_id!r}.")
        return result

    def read_schedule(self) -> tuple[ScheduledMatch, ...]:
        try:
            lines = self.schedule_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise CorruptRecordError(
                f"Cannot read schedule {self.schedule_path}: {error}."
            ) from error
        matches: list[ScheduledMatch] = []
        for line in lines:
            if not line.strip():
                raise CorruptRecordError(f"Schedule {self.schedule_path} contains an empty line.")
            matches.append(
                scheduled_match_from_dict(
                    parse_record_mapping(line, context=str(self.schedule_path))
                )
            )
        return tuple(matches)

    def read_trajectory(
        self,
        case_id: str,
        *,
        card_registry: CardRegistry | None = None,
    ) -> tuple[TrajectoryStep, ...] | None:
        loaded = self.load(trajectory_cases=(case_id,), card_registry=card_registry)
        if case_id not in loaded.results:
            raise CorruptRecordError("Trajectory has no bound result.")
        return loaded.trajectories.get(case_id)

    def _read_trajectory(
        self,
        result: MatchResult,
        match: ScheduledMatch,
        *,
        card_registry: CardRegistry | None,
    ) -> tuple[TrajectoryStep, ...]:
        case_id = match.case_id
        path = self.trajectory_path(case_id)
        document = _read_record_mapping(path)
        if document.get("execution_identity") != result.execution_identity:
            raise CorruptRecordError("Trajectory belongs to another execution.")
        recorded_case_id = require_str_field(
            document,
            "case_id",
            context=str(path),
            error_factory=CorruptRecordError,
        )
        if recorded_case_id != case_id:
            raise CorruptRecordError(
                f"Trajectory case id mismatch for {path}: {recorded_case_id!r}."
            )
        steps = require_sequence_field(
            document,
            "steps",
            context=str(path),
            error_factory=CorruptRecordError,
        )
        trajectory = tuple(
            trajectory_step_from_dict(step, card_registry=card_registry) for step in steps
        )
        validate_trajectory(trajectory, result, match)
        return trajectory

    def write_result(self, result: MatchResult) -> None:
        payload = record_to_dict(result)
        document = {"record_digest": canonical_digest(payload), **payload}
        _atomic_write_text(self.result_path(result.case_id), dump_pretty_json(document))

    def write_report(self, payload: Mapping[str, object], markdown: str) -> None:
        _atomic_write_text(self.report_path, dump_pretty_json(payload))
        _atomic_write_text(self.report_markdown_path, markdown)

    def write_evidence(
        self,
        case_id: str,
        evidence: MatchEvidence,
        *,
        include_trajectory: bool,
        execution_identity: str,
    ) -> EvidenceRefs:
        samples_text = "".join(
            canonical_json(decision_sample_to_dict(sample)) + "\n" for sample in evidence.samples
        )
        _atomic_write_text(self.samples_path(case_id), samples_text)
        trajectory_path = self.trajectory_path(case_id)
        if include_trajectory:
            trajectory_payload = {
                "execution_identity": execution_identity,
                "case_id": case_id,
                "steps": [trajectory_step_to_dict(step) for step in evidence.trajectory],
            }
            _atomic_write_text(trajectory_path, canonical_json(trajectory_payload))
        elif trajectory_path.exists():
            trajectory_path.unlink()
        return EvidenceRefs(
            samples_path=self._relative(self.samples_path(case_id)),
            samples_digest=file_digest(self.samples_path(case_id)),
            trajectory_path=self._relative(trajectory_path) if include_trajectory else None,
            trajectory_digest=file_digest(trajectory_path) if include_trajectory else None,
        )

    def load(
        self, *, trajectory_cases: tuple[str, ...] = (), card_registry: CardRegistry | None = None
    ) -> LoadedRun:
        if trajectory_cases and card_registry is None:
            card_registry = resolve_assets().card_registry
        manifest = self.read_manifest()
        matches = self.read_schedule()
        results: dict[str, MatchResult] = {}
        for match in matches:
            result = self._read_result(match.case_id)
            if result is not None:
                results[match.case_id] = result
        loaded = LoadedRun(manifest, matches, results)
        validate_loaded_run(loaded)
        trajectories: dict[str, tuple[TrajectoryStep, ...]] = {}
        for match in matches:
            result = results.get(match.case_id)
            if result is None:
                continue
            self._verify_evidence(result)
            if match.case_id in trajectory_cases and result.evidence.trajectory_path is not None:
                trajectories[match.case_id] = self._read_trajectory(
                    result,
                    match,
                    card_registry=card_registry,
                )
        return LoadedRun(manifest, matches, results, trajectories)

    def _verify_evidence(self, result: MatchResult) -> None:
        for recorded_path, digest, expected_path in (
            (
                result.evidence.samples_path,
                result.evidence.samples_digest,
                self.samples_path(result.case_id),
            ),
            (
                result.evidence.trajectory_path,
                result.evidence.trajectory_digest,
                self.trajectory_path(result.case_id),
            ),
        ):
            if recorded_path is None:
                if digest is not None:
                    raise CorruptRecordError("Evidence digest without a path.")
                continue
            if recorded_path != self._relative(expected_path):
                raise CorruptRecordError("Unexpected evidence path.")
            if digest is None or file_digest(expected_path) != digest:
                raise CorruptRecordError(f"Evidence digest mismatch for {expected_path}.")

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def run_manifest_identity(manifest: RunManifest) -> str:
    """Checksum all persisted manifest inputs, including execution provenance."""
    return canonical_digest(manifest)


def _read_record_mapping(path: Path) -> Mapping[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CorruptRecordError(f"Cannot read record {path}: {error}.") from error
    return parse_record_mapping(text, context=str(path))


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    _ = temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
