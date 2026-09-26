from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from gwent_shared.digests import (
    canonical_hexdigest as canonical_hexdigest,
)
from gwent_shared.digests import (
    seed_from_text,
    sha256_bytes_hexdigest,
)
from gwent_shared.json_payloads import canonical_json as canonical_json

DIGEST_PREFIX = "sha256:"
SEED_DERIVATION_VERSION = 1

_RELEVANT_DISTRIBUTIONS = ("gwent-engine", "gwent-evaluation")
_LOCKFILE_NAME = "uv.lock"


@dataclass(frozen=True, slots=True)
class RepositoryProvenance:
    commit: str | None
    dirty: bool | None
    lockfile_digest: str | None


@dataclass(frozen=True, slots=True)
class RuntimeProvenance:
    python_implementation: str
    python_version: str
    packages: tuple[tuple[str, str | None], ...]


def canonical_digest(payload: object) -> str:
    return DIGEST_PREFIX + canonical_hexdigest(payload)


def derive_seed(*, namespace: str, identity: str, root_seed: int) -> int:
    """Derive an independent seed stream from a case identity and root seed.

    The namespace and derivation version are part of the hashed input, so new
    stochastic streams can be added without changing existing ones.
    """

    payload = f"{SEED_DERIVATION_VERSION}:{namespace}:{root_seed}:{identity}"
    return seed_from_text(payload)


def read_repository_provenance(repository_root: Path) -> RepositoryProvenance:
    status = _run_git(repository_root, "status", "--porcelain")
    return RepositoryProvenance(
        commit=_git_stdout(repository_root, "rev-parse", "HEAD"),
        dirty=None if status is None else bool(status.stdout.strip()),
        lockfile_digest=file_digest(repository_root / _LOCKFILE_NAME),
    )


def read_runtime_provenance() -> RuntimeProvenance:
    return RuntimeProvenance(
        python_implementation=sys.implementation.name,
        python_version=platform.python_version(),
        packages=tuple(
            (distribution, _distribution_version(distribution))
            for distribution in _RELEVANT_DISTRIBUTIONS
        ),
    )


def file_digest(path: Path) -> str | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    return DIGEST_PREFIX + sha256_bytes_hexdigest(content)


def _distribution_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def _git_stdout(repository_root: Path, *args: str) -> str | None:
    result = _run_git(repository_root, *args)
    if result is None:
        return None
    return result.stdout.strip() or None


def _run_git(repository_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result if result.returncode == 0 else None
