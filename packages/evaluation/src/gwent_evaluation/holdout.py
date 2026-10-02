"""Protected execution capability for held-out suites.

Held-out evidence is only meaningful if it is consumed exactly once, by the
frozen selection, after validation and correctness checks have passed.
`execute_run` therefore refuses `SuitePurpose.TEST` unless the caller presents a
`HoldoutAuthorization`. The finalization controller issues one for the frozen
selection; manual consumption through the generic run command requires an
explicit acknowledgement and is recorded beside the consumed run.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from enum import StrEnum

from gwent_shared.json_payloads import canonical_digest, dump_pretty_json, is_digest

from gwent_evaluation.models import SpecError, SuiteSpec
from gwent_evaluation.storage import (
    RunConflictError,
    RunStore,
    atomic_write_text,
    read_record_mapping,
)

ACKNOWLEDGEMENT_PHRASE = "CONSUME-HELDOUT-PARTITION"

HELDOUT_EXECUTION_ERROR = (
    "Held-out suites may only be executed through `tune finalize`; "
    "manual consumption requires an explicit acknowledgement."
)


class HoldoutOrigin(StrEnum):
    """The authority that issued the one-time capability to consume a partition."""

    FINALIZATION = "finalization"
    MANUAL = "manual"


_CREATION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class HoldoutAuthorization:
    """Capability covering exactly one held-out partition and its issuing authority."""

    suite_id: str
    partition_digest: str
    origin: HoldoutOrigin
    selection_digest: str | None = None
    acknowledgement: str | None = None
    _token: InitVar[object] = None

    def __post_init__(self, _token: object) -> None:
        if _token is not _CREATION_TOKEN:
            raise SpecError("Hold-out authorization must be issued by the evaluation workflow.")
        if type(self.origin) is not HoldoutOrigin:
            raise SpecError("Unsupported hold-out authorization origin.")
        if type(self.suite_id) is not str or not self.suite_id.strip():
            raise SpecError("Hold-out authorization requires a suite id.")
        if not is_digest(self.partition_digest):
            raise SpecError("Hold-out authorization requires a partition digest.")
        if self.origin is HoldoutOrigin.FINALIZATION:
            if not self.selection_digest or self.acknowledgement is not None:
                raise SpecError("Finalization authorization requires a frozen selection digest.")
        elif self.acknowledgement != ACKNOWLEDGEMENT_PHRASE:
            raise SpecError("Manual held-out consumption requires the acknowledgement phrase.")

    def covers(self, suite: SuiteSpec) -> bool:
        return suite.suite_id == self.suite_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "suite_id": self.suite_id,
            "partition_digest": self.partition_digest,
            "origin": self.origin.value,
            "selection_digest": self.selection_digest,
            "acknowledgement": self.acknowledgement,
        }


def _require_heldout_partition(suite: SuiteSpec) -> str:
    if not suite.purpose.is_heldout:
        raise SpecError("Only held-out suites can issue or accept a hold-out authorization.")
    return canonical_digest(suite)


def authorize_finalization(suite: SuiteSpec, *, selection_digest: str) -> HoldoutAuthorization:
    """Issue the capability that the finalization controller alone may pass onward."""
    return HoldoutAuthorization(
        suite_id=suite.suite_id,
        partition_digest=_require_heldout_partition(suite),
        origin=HoldoutOrigin.FINALIZATION,
        selection_digest=selection_digest,
        _token=_CREATION_TOKEN,
    )


def authorize_manual_consumption(suite: SuiteSpec, *, acknowledgement: str) -> HoldoutAuthorization:
    """Issue the deliberately explicit escape-hatch capability for one suite."""
    return HoldoutAuthorization(
        suite_id=suite.suite_id,
        partition_digest=_require_heldout_partition(suite),
        origin=HoldoutOrigin.MANUAL,
        acknowledgement=acknowledgement,
        _token=_CREATION_TOKEN,
    )


def require_holdout_authorization(
    suite: SuiteSpec, authorization: HoldoutAuthorization | None
) -> None:
    """Reject held-out execution without a capability covering exactly this suite."""
    if authorization is None:
        if suite.purpose.is_heldout:
            raise SpecError(HELDOUT_EXECUTION_ERROR)
        return
    if not suite.purpose.is_heldout:
        raise SpecError("Hold-out authorization only applies to held-out suites.")
    if not authorization.covers(suite):
        raise SpecError(f"Hold-out authorization does not cover suite {suite.suite_id!r}.")


def require_partition_authorization(
    suite: SuiteSpec, authorization: HoldoutAuthorization | None
) -> HoldoutAuthorization | None:
    """Check both the suite and the frozen partition digest it was issued against."""
    require_holdout_authorization(suite, authorization)
    if authorization is None:
        return None
    if authorization.partition_digest != canonical_digest(suite):
        raise SpecError("Hold-out authorization does not match the frozen test partition.")
    return authorization


def record_holdout_consumption(store: RunStore, *, authorization: HoldoutAuthorization) -> None:
    """Persist the consumed partition beside its run, idempotently on resume."""
    body = authorization.to_dict()
    payload = {**body, "record_digest": canonical_digest(body)}
    path = store.heldout_path
    if path.exists():
        if read_record_mapping(path) != payload:
            raise RunConflictError("Recorded held-out consumption differs from this run.")
        return
    atomic_write_text(path, dump_pretty_json(payload))
