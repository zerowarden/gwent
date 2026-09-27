from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from gwent_shared.digests import canonical_hexdigest
from gwent_shared.extract import expect_mapping, expect_str
from gwent_shared.json_payloads import parse_json_document, to_canonical

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION

CONFIGURATION_CONTRACT_VERSION = 1


class PolicyArtifactError(ValueError):
    """An artifact is malformed, incompatible, or has a mismatched digest."""


class PolicyStatus(StrEnum):
    UNPROMOTED = "unpromoted"
    PROMOTED = "promoted"


@dataclass(frozen=True, slots=True)
class PolicyArtifact:
    configuration: HeuristicConfiguration
    status: PolicyStatus
    study_digest: str
    selection_digest: str
    evidence_digest: str
    source_commit: str
    implementation_digest: str

    def __post_init__(self) -> None:
        if type(self.configuration) is not HeuristicConfiguration:
            raise PolicyArtifactError("Expected an immutable heuristic configuration.")
        if type(self.status) is not PolicyStatus:
            raise PolicyArtifactError("Unsupported policy status.")
        for name in (
            "study_digest",
            "selection_digest",
            "evidence_digest",
            "source_commit",
            "implementation_digest",
        ):
            value = expect_str(
                cast(object, getattr(self, name)), context=name, error_factory=PolicyArtifactError
            )
            if not value.strip():
                raise PolicyArtifactError(f"{name} must not be empty.")

    @property
    def configuration_digest(self) -> str:
        return self.configuration.digest()

    def to_dict(self) -> dict[str, object]:
        payload = cast(dict[str, object], to_canonical(self))
        payload.update(
            schema_version=1,
            family="heuristic",
            configuration_digest=self.configuration_digest,
            observation_contract_version=OBSERVATION_CONTRACT_VERSION,
            configuration_contract_version=CONFIGURATION_CONTRACT_VERSION,
        )
        return {**payload, "artifact_digest": "sha256:" + canonical_hexdigest(payload)}

    @classmethod
    def from_dict(cls, value: object) -> PolicyArtifact:
        payload = dict(
            expect_mapping(value, context="policy artifact", error_factory=PolicyArtifactError)
        )
        expected = {
            "configuration",
            "status",
            "study_digest",
            "selection_digest",
            "evidence_digest",
            "source_commit",
            "implementation_digest",
            "schema_version",
            "family",
            "configuration_digest",
            "observation_contract_version",
            "configuration_contract_version",
            "artifact_digest",
        }
        if set(payload) != expected:
            raise PolicyArtifactError("Policy artifact fields are missing or unknown.")
        for name, supported in (
            ("schema_version", 1),
            ("observation_contract_version", OBSERVATION_CONTRACT_VERSION),
            ("configuration_contract_version", CONFIGURATION_CONTRACT_VERSION),
        ):
            if type(payload[name]) is not int or payload[name] != supported:
                raise PolicyArtifactError(f"Unsupported {name}.")
        if payload["family"] != "heuristic":
            raise PolicyArtifactError("Only heuristic policy artifacts are supported.")
        digest = payload.pop("artifact_digest")
        if digest != "sha256:" + canonical_hexdigest(payload):
            raise PolicyArtifactError("Policy artifact digest mismatch.")

        def string(name: str) -> str:
            return expect_str(payload[name], context=name, error_factory=PolicyArtifactError)

        try:
            configuration = HeuristicConfiguration.from_dict(payload["configuration"])
            status = PolicyStatus(string("status"))
        except ValueError as error:
            raise PolicyArtifactError(str(error)) from error
        if configuration.digest() != payload["configuration_digest"]:
            raise PolicyArtifactError("Policy configuration digest mismatch.")
        return cls(
            configuration,
            status,
            string("study_digest"),
            string("selection_digest"),
            string("evidence_digest"),
            string("source_commit"),
            string("implementation_digest"),
        )

    @classmethod
    def load(cls, path: Path) -> PolicyArtifact:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise PolicyArtifactError(f"Cannot read policy artifact: {path}") from error
        return cls.from_dict(
            parse_json_document(text, context="policy artifact", error_factory=PolicyArtifactError)
        )
