"""Reports reflect checked partial evidence and never consume held-out games."""

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_evaluation.models import MatchResult, SuitePurpose
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning import workflow
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.storage import write_checked_document
from gwent_evaluation.tuning.study_report import build_study_report, write_study_report

from tests.evaluation.support import REPOSITORY_ROOT
from tests.evaluation.tuning.test_selection import Experiment
from tests.evaluation.tuning.test_selection import experiment as experiment
from tests.evaluation.tuning.test_selection import preflight as preflight
from tests.evaluation.tuning.test_selection import scientific as scientific


def test_reports_rebuild_without_games_and_distinguish_validation_and_test(
    experiment: Experiment,
) -> None:
    experiment.optimize()
    selected = experiment.select()
    report = write_study_report(experiment.root)
    assert report.stage == "validation_complete"
    assert report.verdict == "awaiting_confirmation"
    assert report.confirmation is None
    assert report.validation == selected.to_dict()
    before = len(experiment.played)
    assert build_study_report(experiment.root) == report
    assert len(experiment.played) == before
    random, cma = report.methods
    assert random["fresh_matches"] == 24
    assert cma["fresh_matches"] == 0
    assert cma["cache_hits"] == 2
    assert len(cast(list[object], random["best_score_curve"])) == 2
    assert all(p["candidate"] == p["upper"] for p in report.parameters)
    output = experiment.root / "reports/study"
    machine = cast(dict[str, object], json.loads((output / "report.json").read_text()))
    assert machine["stage"] == report.stage
    markdown = (output / "report.md").read_text()
    html = (output / "report.html").read_text()
    assert "CMA-ES evaluated populations" in html
    assert "<svg" in html
    assert "https://" not in html
    for value in (report.stage, report.verdict, report.measurement):
        assert value in markdown
    _ = (output / "report.json").write_text('{"verdict":"promoted"}')
    assert write_study_report(experiment.root) == report
    assert (output / "report.md").read_text() == markdown
    experiment.verify()
    result = experiment.finalize()
    final = write_study_report(experiment.root)
    assert final.confirmation == result.to_dict()
    assert final.verdict == "promoted"
    assert final.verification is not None


def test_rejected_confirmation_retains_incumbent_with_paired_reasons(
    experiment: Experiment,
) -> None:
    experiment.scores[(SuitePurpose.TEST, experiment.challenger)] = 0.0
    experiment.optimize()
    _ = experiment.select()
    experiment.verify()
    _ = experiment.finalize()
    report = write_study_report(experiment.root)
    assert report.verdict == "incumbent_retained"
    assert "no_positive_improvement" in report.reasons
    assert report.engineering == "complete"


def test_partial_results_show_missing_games_and_do_not_resume(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = RunStore.write_result
    count = 0

    def interrupt(store: RunStore, result: MatchResult) -> None:
        nonlocal count
        original(store, result)
        count += 1
        if count == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", interrupt)
    with pytest.raises(KeyboardInterrupt):
        experiment.optimize()
    report = write_study_report(experiment.root)
    assert report.stage == "optimization_partial"
    assert report.engineering == "incomplete"
    assert report.verdict == "not_assessed"
    run = cast(dict[str, object], report.runs[0]["report"])
    assert run["completed_matches"] == 3
    assert run["missing_matches"] == 9
    assert count == 3


def test_committed_missing_result_is_report_error(experiment: Experiment) -> None:
    experiment.optimize()
    next((experiment.root / "runs").glob("*/matches/*.json")).unlink()
    with pytest.raises(RunConflictError, match="missing"):
        _ = write_study_report(experiment.root)


def test_insensitive_preflight_and_no_evidence_are_explicit(
    experiment: Experiment, tmp_path: Path
) -> None:
    root = tmp_path / "workflow"
    _ = write_checked_document(root / "study.json", record_to_dict(experiment.study))
    report = write_study_report(root)
    assert report.measurement == "not_assessed"
    assert report.verdict == "not_assessed"
    sensitivity = root / "sensitivity"
    sensitivity.mkdir()
    failed = replace(experiment.evidence, reasons=("insufficient_outcome_variation",))
    _ = (sensitivity / "report.json").write_text(json.dumps(failed.to_dict()))
    report = write_study_report(root)
    assert report.measurement == "insufficient_sensitivity"
    assert report.engineering == "stopped"
    assert report.verdict == "not_assessed"
    assert report.reasons == failed.reasons


def test_workflow_stops_after_selection_and_resumes_without_test_feedback(
    experiment: Experiment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    root = tmp_path / "workflow"

    def sensitivity(
        study: StudySpec, *, output_root: Path, repository_root: Path
    ) -> SensitivityReport:
        assert study == experiment.study and repository_root == REPOSITORY_ROOT
        output_root.mkdir(parents=True, exist_ok=True)
        _ = (output_root / "report.json").write_text(json.dumps(experiment.evidence.to_dict()))
        return experiment.evidence

    # Timing is independently exercised on real recorded player observations.
    def timing(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(workflow, "run_sensitivity", sensitivity)
    monkeypatch.setattr(workflow, "measure_selected_latency", timing)
    for _ in range(2):
        workflow.run_tuning(experiment.study, output_root=root, repository_root=REPOSITORY_ROOT)
    report = build_study_report(root)
    assert report.verdict == "awaiting_confirmation"
    assert not any(purpose is SuitePurpose.TEST for purpose, _, _ in experiment.played)
    assert len(experiment.played) == len(set(experiment.played))
    changed = replace(experiment.study, study_id="changed")
    with pytest.raises(RunConflictError, match="inputs changed"):
        workflow.run_tuning(changed, output_root=root, repository_root=REPOSITORY_ROOT)


def test_workflow_preserves_interruption_and_reports_it(
    experiment: Experiment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*_args: object, **_kwargs: object) -> SensitivityReport:
        raise KeyboardInterrupt

    monkeypatch.setattr(workflow, "run_sensitivity", interrupt)
    with pytest.raises(KeyboardInterrupt):
        workflow.run_tuning(experiment.study, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    report = build_study_report(tmp_path)
    assert report.engineering == "interrupted"
    assert report.verdict == "not_assessed"
    assert report.reasons


def test_failed_optimization_reports_failure_without_a_score(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gwent_evaluation.models import TerminationReason
    from gwent_evaluation.tuning.study import StudyStoppedError

    original = RunStore.write_result

    def fail(store: RunStore, result: MatchResult) -> None:
        original(
            store,
            replace(
                result,
                termination=TerminationReason.ACTION_LIMIT,
                candidate_score=None,
                winner=None,
                accepted_transitions=experiment.study.optimization.suite.action_budget,
            ),
        )

    monkeypatch.setattr(RunStore, "write_result", fail)
    with pytest.raises(StudyStoppedError):
        experiment.optimize()
    report = write_study_report(experiment.root)
    assert report.stage == "optimization_stopped"
    assert report.engineering == "failed"
    assert report.verdict == "not_assessed"
    assert report.reasons
    assert cast(dict[str, object], report.runs[0]["report"])["balanced_score"] is None


def test_report_uses_controller_choice_when_scores_tie(experiment: Experiment) -> None:
    for digest in (
        experiment.study.incumbent.digest(),
        experiment.challenger,
        experiment.alternative,
    ):
        experiment.scores[SuitePurpose.OPTIMIZE, digest] = 0.5
    experiment.optimize()
    report = build_study_report(experiment.root)
    assert report.inputs["displayed_candidate_digest"] == experiment.study.incumbent.digest()
    assert all(parameter["candidate"] == parameter["incumbent"] for parameter in report.parameters)
