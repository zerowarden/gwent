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

from gwent_evaluation.models import (
    EvidenceRefs,
    MatchEvidence,
    MatchResult,
    RunManifest,
    ScheduledMatch,
    TrajectoryStep,
)
from gwent_evaluation.provenance import canonical_digest, canonical_json
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

    def evidence_refs(self, case_id: str, *, include_trajectory: bool) -> EvidenceRefs:
        return EvidenceRefs(
            samples_path=self._relative(self.samples_path(case_id)),
            trajectory_path=(
                self._relative(self.trajectory_path(case_id)) if include_trajectory else None
            ),
        )

    def prepare(self, manifest: RunManifest, *, matches: tuple[ScheduledMatch, ...]) -> None:
        identity = run_manifest_identity(manifest)
        if self.root.exists():
            if self._read_manifest_identity() != identity:
                raise RunConflictError(
                    f"Run {self.run_id!r} already exists with a different manifest."
                )
            return
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
        manifest = run_manifest_from_dict(payload)
        if run_manifest_identity(manifest) != identity:
            raise CorruptRecordError(f"Manifest identity mismatch for {self.manifest_path}.")
        return manifest

    def read_result(self, case_id: str) -> MatchResult | None:
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
        result = match_result_from_dict(payload)
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
        path = self.trajectory_path(case_id)
        if not path.exists():
            return None
        document = _read_record_mapping(path)
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
        return tuple(trajectory_step_from_dict(step, card_registry=card_registry) for step in steps)

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
    ) -> EvidenceRefs:
        samples_text = "".join(
            canonical_json(decision_sample_to_dict(sample)) + "\n" for sample in evidence.samples
        )
        _atomic_write_text(self.samples_path(case_id), samples_text)
        trajectory_path = self.trajectory_path(case_id)
        if include_trajectory:
            trajectory_payload = {
                "case_id": case_id,
                "steps": [trajectory_step_to_dict(step) for step in evidence.trajectory],
            }
            _atomic_write_text(trajectory_path, canonical_json(trajectory_payload))
        elif trajectory_path.exists():
            trajectory_path.unlink()
        return self.evidence_refs(case_id, include_trajectory=include_trajectory)

    def _read_manifest_identity(self) -> str:
        if not self.manifest_path.exists():
            raise RunConflictError(f"Run directory {self.root} exists without a manifest.")
        document = _read_record_mapping(self.manifest_path)
        return require_str_field(
            document,
            "manifest_identity",
            context=str(self.manifest_path),
            error_factory=StorageError,
        )

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def run_manifest_identity(manifest: RunManifest) -> str:
    """Stable identity of a run's immutable inputs, excluding machine provenance."""

    return canonical_digest(
        {
            "run_id": manifest.run_id,
            "suite": manifest.suite,
            "planned_case_ids": manifest.planned_case_ids,
            "seed_derivation_version": manifest.seed_derivation_version,
            "case_id_version": manifest.case_id_version,
            "candidate": manifest.candidate,
            "opponents": manifest.opponents,
            "assets": manifest.assets,
        }
    )


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
