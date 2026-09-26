"""Canonical JSON and SHA-256 helpers shared across packages.

`sha256_hexdigest` yields bare hex content fingerprints; `canonical_hexdigest`
hashes the canonical JSON form of a JSON-compatible payload. Record and
identity digests add a `sha256:` prefix at their owning boundary.
"""

from __future__ import annotations

import hashlib

from gwent_shared.json_payloads import canonical_json


def sha256_bytes(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_bytes_hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hexdigest(text: str) -> str:
    return sha256_bytes_hexdigest(text.encode("utf-8"))


def canonical_hexdigest(payload: object) -> str:
    return sha256_hexdigest(canonical_json(payload))


def seed_from_text(text: str) -> int:
    """Deterministic seed from text: first 8 SHA-256 bytes, big-endian."""

    return int.from_bytes(sha256_bytes(text.encode("utf-8"))[:8], "big")
