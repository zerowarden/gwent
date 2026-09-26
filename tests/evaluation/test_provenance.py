from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from gwent_evaluation.provenance import (
    RepositoryProvenance,
    RuntimeProvenance,
    canonical_digest,
    canonical_json,
    read_repository_provenance,
    read_runtime_provenance,
)

from tests.evaluation.support import REPOSITORY_ROOT


def test_canonical_digest_is_deterministic_and_key_order_independent() -> None:
    first = canonical_digest({"a": [1, 2], "b": {"c": 3}})
    second = canonical_digest({"b": {"c": 3}, "a": [1, 2]})

    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert first == second
    assert first.startswith("sha256:")


def test_canonical_digest_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _ = canonical_digest({"weight": float("nan")})


def test_repository_provenance_records_commit_and_lockfile() -> None:
    provenance: RepositoryProvenance = read_repository_provenance(REPOSITORY_ROOT)
    expected_commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    expected_lockfile_digest = (
        "sha256:" + hashlib.sha256((REPOSITORY_ROOT / "uv.lock").read_bytes()).hexdigest()
    )

    assert provenance.commit == expected_commit
    assert provenance.lockfile_digest == expected_lockfile_digest
    assert provenance.dirty is not None


def test_runtime_provenance_records_python_and_packages() -> None:
    provenance: RuntimeProvenance = read_runtime_provenance()
    packages = dict(provenance.packages)

    assert provenance.python_implementation
    assert provenance.python_version
    assert packages["gwent-engine"] is not None
    assert packages["gwent-evaluation"] is not None


def test_implementation_digest_identifies_local_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib.machinery import ModuleSpec

    from gwent_evaluation import provenance

    for name in ("gwent_engine", "gwent_evaluation", "gwent_shared"):
        (tmp_path / name).mkdir()
        _ = (tmp_path / name / "__init__.py").write_text("VALUE = 1\n")

    def spec(name: str) -> ModuleSpec:
        return ModuleSpec(name, loader=None, origin=str(tmp_path / name / "__init__.py"))

    monkeypatch.setattr(provenance, "find_spec", spec)
    before = provenance.implementation_digest()
    _ = (tmp_path / "gwent_engine" / "__init__.py").write_text("VALUE = 2\n")
    assert provenance.implementation_digest() != before
