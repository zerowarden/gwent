"""Held-out suites need an issued capability, and consumption is recorded."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from gwent_evaluation import SuitePurpose
from gwent_evaluation import execution as execution_module
from gwent_evaluation.holdout import (
    ACKNOWLEDGEMENT_PHRASE,
    HoldoutAuthorization,
    HoldoutOrigin,
    authorize_finalization,
    authorize_manual_consumption,
    require_holdout_authorization,
    require_partition_authorization,
)
from gwent_evaluation.models import SpecError, SuiteSpec
from gwent_evaluation.provenance import RepositoryProvenance, read_repository_provenance
from gwent_evaluation.storage import RunConflictError

from tests.evaluation.support import (
    REPOSITORY_ROOT,
    execute_suite,
    read_json_object,
    suite_spec,
)


def heldout_suite(suite_id: str = "synthetic-test") -> SuiteSpec:
    return replace(suite_spec(suite_id=suite_id), purpose=SuitePurpose.TEST)


@pytest.fixture
def _clean_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    provenance = replace(read_repository_provenance(REPOSITORY_ROOT), dirty=False)

    def clean_repository(_root: Path) -> RepositoryProvenance:
        return provenance

    monkeypatch.setattr(execution_module, "read_repository_provenance", clean_repository)


def test_heldout_execution_refuses_to_start_without_authorization(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="tune finalize"):
        _ = execute_suite(tmp_path, suite=heldout_suite())
    assert not (tmp_path / "run").exists()


def test_authorization_factories_reject_non_heldout_or_unacknowledged_requests() -> None:
    heldout = heldout_suite()
    with pytest.raises(SpecError, match="held-out"):
        _ = authorize_manual_consumption(suite_spec(), acknowledgement=ACKNOWLEDGEMENT_PHRASE)
    with pytest.raises(SpecError, match="acknowledgement"):
        _ = authorize_manual_consumption(heldout, acknowledgement="please")
    with pytest.raises(SpecError, match="selection"):
        _ = authorize_finalization(heldout, selection_digest="")


def test_authorization_covers_only_its_partition_and_heldout_suites() -> None:
    heldout = heldout_suite()
    authorization = authorize_manual_consumption(heldout, acknowledgement=ACKNOWLEDGEMENT_PHRASE)
    _ = require_holdout_authorization(heldout, authorization)
    with pytest.raises(SpecError, match="does not cover"):
        _ = require_holdout_authorization(heldout_suite("another-test"), authorization)
    with pytest.raises(SpecError, match="only applies"):
        _ = require_holdout_authorization(suite_spec(), authorization)
    with pytest.raises(SpecError, match="frozen test partition"):
        _ = require_partition_authorization(replace(heldout, seeds=(4,)), authorization)


def test_manual_consumption_executes_once_and_records_its_authority(
    tmp_path: Path, _clean_checkout: None
) -> None:
    suite = heldout_suite("synthetic-heldout")
    authorization = authorize_manual_consumption(suite, acknowledgement=ACKNOWLEDGEMENT_PHRASE)
    execution = execute_suite(tmp_path, suite=suite, holdout_authorization=authorization)
    record = read_json_object(execution.root / "heldout.json")
    assert record["suite_id"] == "synthetic-heldout"
    assert record["origin"] == "manual"
    assert record["acknowledgement"] == ACKNOWLEDGEMENT_PHRASE
    resumed = execute_suite(tmp_path, suite=suite, holdout_authorization=authorization)
    assert resumed.executed_case_ids == ()
    assert read_json_object(execution.root / "heldout.json") == record


def test_reissued_authorization_cannot_rewrite_recorded_consumption(
    tmp_path: Path, _clean_checkout: None
) -> None:
    suite = heldout_suite("synthetic-heldout")
    manual = authorize_manual_consumption(suite, acknowledgement=ACKNOWLEDGEMENT_PHRASE)
    _ = execute_suite(tmp_path, suite=suite, holdout_authorization=manual)
    finalization = authorize_finalization(suite, selection_digest="sha256:frozen")
    with pytest.raises(RunConflictError, match="differs"):
        _ = execute_suite(tmp_path, suite=suite, holdout_authorization=finalization)


def test_finalization_authorization_tracks_origin_and_selection() -> None:
    suite = heldout_suite()
    authorization = authorize_finalization(suite, selection_digest="sha256:frozen")
    assert authorization.origin is HoldoutOrigin.FINALIZATION
    assert authorization.selection_digest == "sha256:frozen"
    assert authorization.acknowledgement is None
    assert isinstance(authorization, HoldoutAuthorization)
    assert authorization.to_dict()["partition_digest"] == authorization.partition_digest


def test_direct_construction_and_replace_cannot_forge_authorization() -> None:
    suite = heldout_suite()
    authorization = authorize_manual_consumption(suite, acknowledgement=ACKNOWLEDGEMENT_PHRASE)
    with pytest.raises(SpecError, match="issued"):
        _ = HoldoutAuthorization(
            suite_id=suite.suite_id,
            partition_digest=authorization.partition_digest,
            origin=authorization.origin,
            acknowledgement=ACKNOWLEDGEMENT_PHRASE,
        )
    with pytest.raises(SpecError, match="issued"):
        _ = replace(authorization, suite_id="another-test")
