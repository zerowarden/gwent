"""The pilot recipe owns output organization, stage gates, and whole-run reuse."""

import csv
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest
from gwent_evaluation import cli, execution
from gwent_evaluation.execution import execute_case
from gwent_evaluation.models import RunManifest, SpecError, SuitePurpose
from gwent_evaluation.storage import RunConflictError
from gwent_evaluation.tuning import workflow
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.storage import StudyLockedError, exclusive_writer
from gwent_evaluation.tuning.workflow import run_pilot

from tests.evaluation.support import REPOSITORY_ROOT, read_json_object
from tests.evaluation.tuning.test_objective import preflight as preflight
from tests.evaluation.tuning.test_objective import scientific as scientific

pytestmark = pytest.mark.allow_match_execution


@pytest.fixture
def smoke(scientific: StudySpec) -> RunManifest:
    return replace(
        scientific.optimization,
        run_id="smoke",
        suite=replace(
            scientific.optimization.suite,
            purpose=SuitePurpose.SMOKE,
        ),
    )


@pytest.fixture
def measured(preflight: SensitivityReport, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic gate evidence; games in the smoke and optimization stages are real."""
    monkeypatch.setattr(execution, "execute_case", execute_case)

    def sensitivity(
        study: StudySpec, *, output_root: Path, repository_root: Path
    ) -> SensitivityReport:
        assert study.digest() == preflight.study_digest
        assert repository_root == REPOSITORY_ROOT
        output_root.mkdir(parents=True, exist_ok=True)
        _ = (output_root / "report.json").write_text(json.dumps(preflight.to_dict()))
        _ = (output_root / "snapshot.json").write_text("{}")
        return preflight

    monkeypatch.setattr(workflow, "run_sensitivity", sensitivity)


def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
    pytest.fail("This operation must not execute new matches")


@pytest.mark.usefixtures("measured")
def test_complete_workflow_rebuilds_guides_and_reuses_games(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pilot"
    _ = (tmp_path / "README.md").write_text("Existing project documentation.\n")
    result = run_pilot(scientific, smoke, output_root=root, repository_root=REPOSITORY_ROOT)
    assert (tmp_path / "README.md").read_text() == "Existing project documentation.\n"
    status = read_json_object(root / "workflow.json")
    assert set(cast(dict[str, str], status["stages"]).values()) == {"complete"}
    assert status["executed_this_invocation"] == 72  # 12 smoke + 60 optimization.
    assert set(cast(dict[str, int], status["matches"])) == {"smoke", "sensitivity", "optimization"}
    assert {item.name for item in root.iterdir()} == {
        "README.md",
        "writer.lock",
        "workflow.json",
        "inputs",
        "reports",
        "data",
        "logs",
    }
    for readme in tmp_path.rglob("README.md"):
        for target in cast(list[str], re.findall(r"\]\(([^)]+)\)", readme.read_text())):
            assert (readme.parent / target).exists(), (readme, target)
    assert not list(root.rglob("*.py"))
    assert not list(root.rglob(".venv"))
    with (root / "reports/trials.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert rows[0]["method"] == "incumbent"
    assert (
        float(rows[0]["immediate_points"]) == scientific.incumbent.baseline.weights.immediate_points
    )
    assert float(rows[0]["score"]) == result.incumbent.evaluation.trial.require_eligible_score()
    for path in (root / "reports").iterdir():
        path.unlink()
    (root / "README.md").unlink()
    monkeypatch.setattr(execution, "execute_case", forbidden)
    replay = run_pilot(scientific, smoke, output_root=root, repository_root=REPOSITORY_ROOT)
    assert replay == result
    assert read_json_object(root / "workflow.json")["executed_this_invocation"] == 0
    assert (root / "reports/trials.csv").exists()


@pytest.mark.usefixtures("measured")
def test_failed_sensitivity_leaves_explanation_and_never_starts_optimization(
    scientific: StudySpec,
    smoke: RunManifest,
    preflight: SensitivityReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def insufficient(*_args: object, **_kwargs: object) -> SensitivityReport:
        return replace(preflight, reasons=("synthetic-insufficient",))

    monkeypatch.setattr(workflow, "run_sensitivity", insufficient)
    monkeypatch.setattr(workflow, "run_study", forbidden)
    with pytest.raises(SpecError):
        _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    status = read_json_object(tmp_path / "workflow.json")
    assert cast(dict[str, str], status["stages"])["sensitivity"] == "failed"
    assert cast(dict[str, str], status["stages"])["optimization"] == "pending"
    assert "synthetic-insufficient" in (tmp_path / "README.md").read_text()
    assert not (tmp_path / "data/optimization").exists()


@pytest.mark.usefixtures("measured")
def test_interruption_resumes_from_frozen_inputs_and_changed_inputs_fail(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as interrupted:

        def stop(*_args: object, **_kwargs: object) -> NoReturn:
            raise KeyboardInterrupt

        interrupted.setattr(workflow, "run_sensitivity", stop)
        with pytest.raises(KeyboardInterrupt):
            _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert read_json_object(tmp_path / "workflow.json")["status"] == "interrupted"
    changed = replace(
        scientific, optimizers=(replace(scientific.optimizers[0], seed=1), scientific.optimizers[1])
    )
    before = (tmp_path / "workflow.json").read_bytes()
    with pytest.raises(RunConflictError, match="inputs differ"):
        _ = run_pilot(changed, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert (tmp_path / "workflow.json").read_bytes() == before
    _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert read_json_object(tmp_path / "workflow.json")["executed_this_invocation"] == 60


def test_dirty_inputs_and_second_writer_fail_before_games(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(execution, "execute_case", forbidden)
    repository = replace(scientific.optimization.repository, dirty=True)
    dirty = replace(
        scientific,
        optimization=replace(scientific.optimization, repository=repository),
        validation=replace(scientific.validation, repository=repository),
        test=replace(scientific.test, repository=repository),
    )
    with pytest.raises(SpecError, match="clean committed"):
        _ = run_pilot(dirty, smoke, output_root=tmp_path / "dirty", repository_root=REPOSITORY_ROOT)
    assert not (tmp_path / "dirty").exists()
    with exclusive_writer(tmp_path / "locked"):
        with pytest.raises(StudyLockedError, match="already owns"):
            _ = run_pilot(
                scientific,
                smoke,
                output_root=tmp_path / "locked",
                repository_root=REPOSITORY_ROOT,
                recover_lock=True,
            )
    assert not (tmp_path / "locked/inputs").exists()


@pytest.mark.usefixtures("measured")
def test_cli_passes_output_and_explicit_recovery(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inputs(_root: Path) -> tuple[StudySpec, RunManifest]:
        return scientific, smoke

    monkeypatch.setattr(workflow, "load_pilot_inputs", inputs)
    monkeypatch.setattr(cli, "_repository_root", lambda: REPOSITORY_ROOT)
    assert cli.main(["tune", "pilot", "--output", str(tmp_path), "--recover-lock"]) == 0
    assert (tmp_path / "README.md").exists()


@pytest.mark.usefixtures("measured")
def test_mid_optimization_interruption_counts_saved_work_and_resumes_once(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gwent_evaluation.models import MatchResult
    from gwent_evaluation.storage import RunStore

    original = RunStore.write_result
    written: list[tuple[str, str]] = []

    def write(store: RunStore, result: MatchResult) -> None:
        original(store, result)
        written.append((store.run_id, result.case_id))
        if len(written) == 17:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", write)
    with pytest.raises(KeyboardInterrupt):
        _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    state = read_json_object(tmp_path / "workflow.json")
    assert state["stage"] == "optimization"
    assert state["status"] == "interrupted"
    assert state["executed_this_invocation"] == 17
    _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert len(written) == len(set(written)) == 72
    assert read_json_object(tmp_path / "workflow.json")["executed_this_invocation"] == 55


@pytest.mark.usefixtures("measured")
def test_missing_committed_input_is_not_reconstructed(
    scientific: StudySpec,
    smoke: RunManifest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gwent_evaluation.records import CorruptRecordError

    _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    (tmp_path / "inputs/smoke.json").unlink()
    monkeypatch.setattr(execution, "execute_case", forbidden)
    with pytest.raises(CorruptRecordError):
        _ = run_pilot(scientific, smoke, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert not (tmp_path / "inputs/smoke.json").exists()
