"""Record the repository's correctness gates against a frozen selected policy."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from gwent_evaluation.execution import validate_run_environment
from gwent_evaluation.models import SpecError
from gwent_evaluation.provenance import file_digest
from gwent_evaluation.storage import RunConflictError, atomic_write_text
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.storage import (
    read_checked_document,
    write_checked_document,
)

VERIFICATION_COMMAND = ("make", "check")


def run_correctness_checks(repository_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        VERIFICATION_COMMAND, cwd=repository_root, capture_output=True, text=True, check=False
    )


def _identity(study: StudySpec, selection_digest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "study_digest": study.digest(),
        "selection_digest": selection_digest,
        "command": list(VERIFICATION_COMMAND),
    }


def record_verification(
    root: Path, study: StudySpec, selection_digest: str, *, repository_root: Path
) -> Mapping[str, object]:
    """Record checks while the caller owns the selection writer lock."""
    if (root / "confirmation/snapshot.json").exists():
        raise RunConflictError("Verification is frozen once confirmation has started.")
    validate_run_environment(study.optimization, repository_root=repository_root)
    try:
        result = run_correctness_checks(repository_root)
    except OSError as error:
        raise SpecError(f"Cannot execute verification: {error}") from error
    validate_run_environment(study.optimization, repository_root=repository_root)
    log = root / "verification.log"
    atomic_write_text(log, result.stdout + result.stderr)
    payload = {
        **_identity(study, selection_digest),
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "log_digest": file_digest(log),
    }
    _ = write_checked_document(root / "verification.json", payload)
    return payload


def require_verification(
    root: Path, study: StudySpec, selection_digest: str
) -> Mapping[str, object]:
    path = root / "verification.json"
    if not path.is_file():
        raise SpecError("Run tune verify for the selected challenger before finalization.")
    evidence = read_checked_document(path)
    expected = {
        **_identity(study, selection_digest),
        "passed": True,
        "exit_code": 0,
        "log_digest": file_digest(root / "verification.log"),
    }
    if evidence != expected or expected["log_digest"] is None:
        raise RunConflictError("Correctness verification is failed, stale, or corrupt.")
    return evidence
