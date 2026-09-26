from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import distributions
from importlib.util import find_spec
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

_LOCKFILE_NAME = "uv.lock"


@dataclass(frozen=True, slots=True)
class RepositoryProvenance:
    commit: str | None
    dirty: bool | None
    lockfile_digest: str | None
    implementation_digest: str | None = None

    @property
    def is_clean_checkout(self) -> bool:
        return (
            self.dirty is False
            and self.commit is not None
            and self.lockfile_digest is not None
            and self.implementation_digest is not None
        )


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
        implementation_digest=implementation_digest(),
    )


def default_repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def read_runtime_provenance() -> RuntimeProvenance:
    return RuntimeProvenance(
        python_implementation=sys.implementation.name,
        python_version=platform.python_version(),
        packages=tuple(
            sorted(
                (distribution.metadata["Name"].lower(), distribution.version)
                for distribution in distributions()
            )
        ),
    )


def file_digest(path: Path) -> str | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    return DIGEST_PREFIX + sha256_bytes_hexdigest(content)


def implementation_digest() -> str:
    """Fingerprint installed first-party source, including diagnostic local edits.

    Resolve the code actually imported, rather than assuming repository_root is
    the checkout used by the interpreter. No hidden game state enters this hash.
    """
    files: list[tuple[str, str | None]] = []
    for package in ("gwent_engine", "gwent_evaluation", "gwent_shared"):
        spec = find_spec(package)
        if spec is None or spec.origin is None:
            raise ValueError(f"Cannot identify implementation for {package}.")
        root = Path(spec.origin).parent
        files.extend(
            (f"{package}/{path.relative_to(root)}", file_digest(path))
            for path in sorted(root.rglob("*.py"))
        )
    return canonical_digest(files)


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
