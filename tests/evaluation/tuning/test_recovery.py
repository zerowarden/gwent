"""Interrupted studies must preserve proposals, results, and semantic accounting."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest
from gwent_evaluation import execution
from gwent_evaluation import storage as run_storage
from gwent_evaluation.execution import execute_case
from gwent_evaluation.models import MatchResult
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import CorruptRecordError
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.storage import StudyLockedError, StudyStore

from tests.evaluation.tuning.test_study import evidence as evidence
from tests.evaluation.tuning.test_study import execute
from tests.evaluation.tuning.test_study import experiment as experiment
from tests.evaluation.tuning.test_study import played as played
from tests.evaluation.tuning.test_study import preflight as preflight
from tests.evaluation.tuning.test_study import scientific as scientific


@pytest.mark.parametrize(
    ("kind", "after"), [("ask", True), ("tell", False), ("tell", True), ("trial", False)]
)
def test_journal_boundaries_recover_identically(
    kind: str,
    after: bool,
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = execute(experiment, evidence, tmp_path / "baseline")
    played.clear()
    original = StudyStore.record
    interrupted = False

    def record(store: StudyStore, event: str, payload: Mapping[str, object]) -> str:
        nonlocal interrupted
        trigger = event == kind and payload.get("method") == "cma_es" and not interrupted
        if trigger and not after:
            interrupted = True
            raise KeyboardInterrupt
        digest = original(store, event, payload)
        if trigger:
            interrupted = True
            raise KeyboardInterrupt
        return digest

    monkeypatch.setattr(StudyStore, "record", record)
    with pytest.raises(KeyboardInterrupt):
        _ = execute(experiment, evidence, tmp_path / "resumed")
    assert interrupted
    recovered = execute(experiment, evidence, tmp_path / "resumed")
    assert recovered == baseline
    assert len(played) == len(set(played)) == 108


def test_partial_candidate_recovers_only_missing_matches(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = execute(experiment, evidence, tmp_path / "baseline")
    played.clear()
    original = RunStore.write_result
    committed: list[tuple[str, str]] = []
    interrupted = False

    def write(store: RunStore, result: MatchResult) -> None:
        nonlocal interrupted
        original(store, result)
        committed.append((store.run_id, result.case_id))
        if len(committed) == 17 and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", write)
    with pytest.raises(KeyboardInterrupt):
        _ = execute(experiment, evidence, tmp_path / "resumed")
    recovered = execute(experiment, evidence, tmp_path / "resumed")
    assert recovered == baseline
    assert len(committed) == len(set(committed)) == 108


def test_interrupted_run_initialization_does_not_publish_partial_metadata(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = run_storage.atomic_write_text
    interrupted = False

    def write(path: Path, content: str) -> None:
        nonlocal interrupted
        original(path, content)
        if path.name == "manifest.json" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(run_storage, "atomic_write_text", write)
    with pytest.raises(KeyboardInterrupt):
        _ = execute(experiment, evidence, tmp_path)
    assert list((tmp_path / "runs").iterdir()) == []
    _ = execute(experiment, evidence, tmp_path)
    assert len(played) == 108


@pytest.mark.parametrize(
    "tamper", ["weight", "fitness", "reference", "snapshot", "missing_result", "gap", "checksum"]
)
def test_corruption_is_a_conflict_and_never_causes_reevaluation(
    tamper: str,
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = execute(experiment, evidence, tmp_path)
    paths = sorted((tmp_path / "journal").glob("*.json"))
    if tamper == "missing_result":
        next((tmp_path / "runs").glob("*/matches/*.json")).unlink()
    elif tamper == "checksum":
        _ = paths[0].write_text(paths[0].read_text().replace("incumbent", "changed", 1))
    elif tamper == "gap":
        paths[2].unlink()
    else:
        target = (
            tmp_path / "snapshot.json"
            if tamper == "snapshot"
            else next(
                path
                for path in paths
                if json.loads(path.read_text())["kind"]
                == {
                    "weight": "ask",
                    "fitness": "tell",
                    "reference": "trial",
                }[tamper]
            )
        )
        document = cast(dict[str, object], json.loads(target.read_text()))
        if tamper == "snapshot":
            snapshot = cast(dict[str, object], document["snapshot"])
            frozen = cast(dict[str, object], snapshot["study"])
            optimizers = cast(list[dict[str, object]], frozen["optimizers"])
            cast(dict[str, object], optimizers[1]["cma"])["backend_version"] = "changed"
        else:
            payload = cast(dict[str, object], document["payload"])
            if tamper == "weight":
                candidates = cast(list[dict[str, object]], payload["candidates"])
                proposal = cast(dict[str, object], candidates[0]["proposal"])
                cast(list[float], proposal["coordinates"])[0] = 0.0
            elif tamper == "fitness":
                cast(list[dict[str, object]], payload["results"])[0]["fitness"] = -1.0
            else:
                trial = cast(dict[str, object], payload["trial"])
                cast(list[dict[str, object]], trial["results"])[0]["record_digest"] = "changed"
        # Recompute checksums and the whole chain to exercise semantic replay too.
        document["record_digest"] = canonical_digest(
            {key: value for key, value in document.items() if key != "record_digest"}
        )
        _ = target.write_text(json.dumps(document))
        if tamper != "snapshot":
            snapshot_document = cast(
                dict[str, object], json.loads((tmp_path / "snapshot.json").read_text())
            )
            previous = snapshot_document["record_digest"]
            for path in paths:
                entry = cast(dict[str, object], json.loads(path.read_text()))
                entry["previous"] = previous
                entry["record_digest"] = canonical_digest(
                    {key: value for key, value in entry.items() if key != "record_digest"}
                )
                previous = entry["record_digest"]
                _ = path.write_text(json.dumps(entry))

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Corrupt committed evidence must never be reevaluated")

    from gwent_evaluation.tuning import study as study_module

    monkeypatch.setattr(study_module, "evaluate_candidate", forbidden)
    with pytest.raises((RunConflictError, CorruptRecordError)):
        _ = execute(experiment, evidence, tmp_path)
    assert len(played) == 108


def test_changed_study_is_rejected_before_any_trial(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
) -> None:
    _ = execute(experiment, evidence, tmp_path)
    changed = replace(
        experiment, optimizers=(replace(experiment.optimizers[0], seed=9), experiment.optimizers[1])
    )
    with pytest.raises(RunConflictError, match="snapshot differs"):
        _ = execute(changed, replace(evidence, study_digest=changed.digest()), tmp_path)
    assert len(played) == 108


def test_second_writer_cannot_mutate_the_study(tmp_path: Path) -> None:
    first, second = StudyStore(tmp_path), StudyStore(tmp_path)
    with first.writer():
        first.prepare({"study": "synthetic"})
        before = (tmp_path / "snapshot.json").read_bytes()
        with pytest.raises(StudyLockedError, match="already owns"):
            with second.writer(recover_lock=True):
                pytest.fail("Concurrent writer acquired the study")
        assert (tmp_path / "snapshot.json").read_bytes() == before
    with pytest.raises(StudyLockedError, match="writer lock"):
        _ = first.record("invalid", {})


def test_process_death_requires_explicit_lock_recovery(tmp_path: Path) -> None:
    code = """
import os
import sys
from pathlib import Path
from gwent_evaluation.tuning.storage import StudyStore
store = StudyStore(Path(sys.argv[1]))
with store.writer():
    store.prepare({'study': 'synthetic'})
    os._exit(0)
"""
    _ = subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True)
    store = StudyStore(tmp_path)
    with pytest.raises(StudyLockedError, match="recover_lock"):
        with store.writer():
            pytest.fail("Abandoned writer marker was silently recovered")
    with store.writer(recover_lock=True):
        store.prepare({"study": "synthetic"})
        _ = store.record("recovered", {})
    with store.writer():
        store.prepare({"study": "synthetic"})
        _ = store.record("recovered", {})
        store.finish()


@pytest.mark.allow_match_execution
def test_actual_games_recover_with_identical_semantics(
    scientific: StudySpec,
    preflight: SensitivityReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "execute_case", execute_case)
    baseline = execute(scientific, preflight, tmp_path / "baseline")
    original = RunStore.write_result
    committed: list[tuple[str, str]] = []

    def write(store: RunStore, result: MatchResult) -> None:
        original(store, result)
        committed.append((store.run_id, result.case_id))
        if len(committed) == 17:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", write)
    with pytest.raises(KeyboardInterrupt):
        _ = execute(scientific, preflight, tmp_path / "resumed")
    recovered = execute(scientific, preflight, tmp_path / "resumed")
    assert recovered.to_dict() == baseline.to_dict()
    for method, reference in zip(recovered.methods, baseline.methods, strict=True):
        for trial, original_trial in zip(method.trials, reference.trials, strict=True):
            assert tuple(
                (result.case_id, result.semantic_digest, result.termination)
                for result in trial.evaluation.trial.results
            ) == tuple(
                (result.case_id, result.semantic_digest, result.termination)
                for result in original_trial.evaluation.trial.results
            )
    assert execute(scientific, preflight, tmp_path / "resumed") == recovered
    assert len(committed) == len(set(committed)) == 60
