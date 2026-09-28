"""Range experiments preserve pairing, stop on bad evidence, and never use test games."""

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_evaluation.models import (
    MatchResult,
    RunManifest,
    SpecError,
    SuitePurpose,
    TerminationReason,
)
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning import ranges
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.objective import RecordedEvaluation, evaluate_recorded_candidate
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.specs import load_study_spec
from gwent_evaluation.tuning.storage import StudyStore, read_checked_document

from tests.evaluation.support import REPOSITORY_ROOT
from tests.evaluation.tuning.test_selection import Experiment
from tests.evaluation.tuning.test_selection import experiment as experiment
from tests.evaluation.tuning.test_selection import preflight as preflight
from tests.evaluation.tuning.test_selection import scientific as scientific


def test_broader_benchmark_and_sweep_change_one_weight_at_a_time() -> None:
    study = load_study_spec(
        REPOSITORY_ROOT / "experiments/tuning/benchmark-v2.json", repository_root=REPOSITORY_ROOT
    )
    pairs = study.optimization.suite.deck_pairs
    assert len(pairs) == 10
    assert sum(a == b for a, b in pairs) == 4
    assert len(study.optimization.planned_case_ids) == 1024
    assert len(study.validation.planned_case_ids) == 2048
    assert set(study.optimization.suite.seeds).isdisjoint(study.validation.suite.seeds)
    points = ranges.sweep_points(study, (0, 0.5, 1, 2, 4))
    assert len(points) == len({p.configuration_digest for p in points}) == 44
    for point in points:
        weights = study.bind(point.coordinates).baseline.weights
        changed = [
            p.name
            for p in study.parameter_space.parameters
            if getattr(weights, p.name) != getattr(study.incumbent.baseline.weights, p.name)
        ]
        assert changed == [point.parameter]


@pytest.fixture
def investigation(
    experiment: Experiment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    # Match outcomes are synthetic; this fixture only verifies experiment control.
    protocol = tmp_path / "protocol.json"
    _ = protocol.write_text('{"fixture": true}')
    multipliers = (0.0, 1.0, 2.0)
    for point in ranges.sweep_points(experiment.study, multipliers):
        experiment.scores[SuitePurpose.OPTIMIZE, point.configuration_digest] = 1.0
        experiment.scores[SuitePurpose.VALIDATION, point.configuration_digest] = 0.0

    def load(_path: Path, _repository: Path) -> tuple[StudySpec, tuple[float, ...]]:
        return experiment.study, multipliers

    def sensitivity(
        _study: StudySpec, *, output_root: Path, repository_root: Path
    ) -> SensitivityReport:
        assert output_root.name == "sensitivity" and repository_root == REPOSITORY_ROOT
        return experiment.evidence

    monkeypatch.setattr(ranges, "load_protocol", load)
    monkeypatch.setattr(ranges, "run_sensitivity", sensitivity)
    monkeypatch.setattr(ranges, "default_repository_root", lambda: REPOSITORY_ROOT)
    return protocol, tmp_path / "ranges"


def test_sweeps_resume_and_recheck_without_promoting_or_using_holdout(
    experiment: Experiment,
    investigation: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol, root = investigation
    original = RunStore.write_result
    writes = 0

    def interrupt(store: RunStore, result: MatchResult) -> None:
        nonlocal writes
        original(store, result)
        writes += 1
        if writes == 17:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", interrupt)
    with pytest.raises(KeyboardInterrupt):
        ranges.run_ranges(protocol, root, workers=2)
    assert json.loads((root / "screening/report.json").read_text())["status"] == "interrupted"
    played = list(experiment.played)
    journal = {p: p.read_bytes() for p in (root / "screening/journal").glob("*.json")}
    ranges.rebuild_range_reports(root)
    assert experiment.played == played
    assert all(p.read_bytes() == data for p, data in journal.items())
    ranges.run_ranges(protocol, root, workers=3)
    first = (root / "report.json").read_bytes()
    before = writes
    ranges.run_ranges(protocol, root)
    assert writes == before
    assert (root / "report.json").read_bytes() == first
    ranges.rebuild_range_reports(root)
    assert writes == before
    assert (root / "report.json").read_bytes() == first
    report = cast(dict[str, object], json.loads(first))
    rechecks = cast(list[dict[str, object]], report["rechecks"])
    assert len(cast(list[object], report["screening"])) == 22 and len(rechecks) == 11
    assert all(row["difference"] == 0 for row in rechecks)
    assert report["held_out_games"] == 0
    assert all(purpose is not SuitePurpose.TEST for purpose, _, _ in experiment.played)
    assert (root / "benchmark/report.html").exists()
    assert "<svg" in (root / "screening/report.html").read_text()
    # A changed protocol cannot continue the frozen experiment.
    _ = protocol.write_text('{"fixture": false}')
    with pytest.raises(RunConflictError, match="snapshot"):
        ranges.run_ranges(protocol, root, workers=2)


def test_failed_range_candidate_is_terminal(
    experiment: Experiment,
    investigation: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RunStore.write_result
    writes = 0

    def fail(store: RunStore, result: MatchResult) -> None:
        nonlocal writes
        writes += 1
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
    protocol, root = investigation
    with pytest.raises(SpecError, match="invalid"):
        ranges.run_ranges(protocol, root, workers=3)
    before = writes
    with pytest.raises(SpecError, match="invalid"):
        ranges.run_ranges(protocol, root)
    assert writes == before
    assert not (root / "recheck/snapshot.json").exists()


def test_nomination_prefers_nearby_value_on_tie_and_keeps_incumbent_on_equal_scores(
    scientific: StudySpec,
) -> None:
    rows = [
        {
            "parameter": "immediate_points",
            "value": 4.0,
            "difference": 0.1,
            "configuration_digest": "far",
        },
        {
            "parameter": "immediate_points",
            "value": 0.5,
            "difference": 0.1,
            "configuration_digest": "near",
        },
        {
            "parameter": "card_advantage",
            "value": 4.0,
            "difference": 0.0,
            "configuration_digest": "equal",
        },
    ]
    assert ranges.nominate_ranges(scientific, rows) == ("near",)


@pytest.mark.parametrize(
    ("flag", "environment", "expected"),
    [(None, None, 8), (None, "", 8), (None, "3", 3), ("2", "4", 2), ("2", "bad", 2)],
)
def test_worker_cli_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str | None,
    environment: str | None,
    expected: int,
) -> None:
    monkeypatch.setattr(ranges, "default_range_workers", lambda: 8)
    monkeypatch.delenv("GWENT_RANGE_WORKERS", raising=False)
    if environment is not None:
        monkeypatch.setenv("GWENT_RANGE_WORKERS", environment)
    called: list[int] = []

    def run(_protocol: Path, _root: Path, *, recover_lock: bool, workers: int) -> None:
        assert not recover_lock
        called.append(workers)

    monkeypatch.setattr(ranges, "run_ranges", run)
    argv = ["run", "--output", str(tmp_path / "output")]
    if flag is not None:
        argv.extend(["-j", flag])
    assert ranges.range_command(ranges.ranges_parser().parse_args(argv)) == 0
    assert called == [expected]
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.5"])
@pytest.mark.parametrize("source", ["flag", "environment"])
def test_invalid_worker_controls_fail_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    source: str,
) -> None:
    monkeypatch.setenv("GWENT_RANGE_WORKERS", value if source == "environment" else "1")
    argv = ["run", "--output", str(tmp_path / "output")]
    if source == "flag":
        argv.extend(["--workers", value])
    with pytest.raises(SpecError, match="positive integer"):
        _ = ranges.range_command(ranges.ranges_parser().parse_args(argv))
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("action", ["plan", "report"])
def test_workers_are_run_only_and_environment_is_ignored_elsewhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from gwent_evaluation import execution

    monkeypatch.setenv("GWENT_RANGE_WORKERS", "invalid")
    calls: list[Path] = []

    def report(root: Path) -> None:
        calls.append(root)

    def no_pool(*_args: object, **_kwargs: object) -> None:
        pytest.fail("plan/report must never create workers")

    monkeypatch.setattr(execution, "ProcessPoolExecutor", no_pool)
    monkeypatch.setattr(ranges, "rebuild_range_reports", report)
    argv = [action, "--output", str(tmp_path / "output")]
    with pytest.raises(SpecError, match="only supported for ranges run"):
        _ = ranges.range_command(ranges.ranges_parser().parse_args([*argv, "--workers", "2"]))
    assert not (tmp_path / "output").exists()
    assert ranges.range_command(ranges.ranges_parser().parse_args(argv)) == 0
    if action == "report":
        assert calls == [tmp_path / "output"]
    else:
        assert (tmp_path / "output/plan/report.html").is_file()


@pytest.mark.parametrize("workers", [True, 0, -1])
def test_range_api_rejects_invalid_workers_before_protocol_or_lock(
    tmp_path: Path,
    workers: int,
) -> None:
    with pytest.raises(SpecError, match="positive integer"):
        ranges.run_ranges(tmp_path / "missing-protocol", tmp_path / "output", workers=workers)
    assert not (tmp_path / "output").exists()


def test_workers_forward_to_both_stages_only_after_frozen_screening(
    experiment: Experiment,
    investigation: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol, root = investigation
    points = ranges.sweep_points(experiment.study, (0.0, 1.0, 2.0))

    def evaluate(
        store: StudyStore,
        study: StudySpec,
        template: RunManifest,
        configuration: HeuristicConfiguration,
        *,
        repository_root: Path,
        workers: int = 1,
    ) -> RecordedEvaluation:
        if template.suite.purpose is SuitePurpose.VALIDATION:
            entries = [
                read_checked_document(p)
                for p in sorted((root / "screening/journal").glob("*.json"))
            ]
            assert len(entries) == 1 + len(points)
            assert all(entry["kind"] == "evaluation" for entry in entries)
            nomination = read_checked_document(root / "journal/00000000.json")
            assert nomination["kind"] == "nomination"
            nominated = cast(dict[str, object], nomination["payload"])
            assert len(cast(list[str], nominated["configurations"])) == 11
        return evaluate_recorded_candidate(
            store, study, template, configuration, repository_root=repository_root, workers=workers
        )

    monkeypatch.setattr(ranges, "evaluate_recorded_candidate", evaluate)
    ranges.run_ranges(protocol, root, workers=4)
    assert {purpose for purpose, _ in experiment.worker_requests} == {
        SuitePurpose.OPTIMIZE,
        SuitePurpose.VALIDATION,
    }
    assert all(workers == 4 for _, workers in experiment.worker_requests)
    before = list(experiment.worker_requests)
    ranges.run_ranges(protocol, root, workers=2)
    ranges.rebuild_range_reports(root)
    assert experiment.worker_requests == before


def test_no_screening_improvement_starts_no_recheck(
    experiment: Experiment,
    investigation: tuple[Path, Path],
) -> None:
    for key in experiment.scores:
        experiment.scores[key] = 0.0
    protocol, root = investigation
    ranges.run_ranges(protocol, root, workers=3)
    assert {p for p, _ in experiment.worker_requests} == {SuitePurpose.OPTIMIZE}
    assert not (root / "recheck/snapshot.json").exists()
    report = cast(dict[str, object], json.loads((root / "report.json").read_text()))
    assert report["status"] == "complete" and report["rechecks"] == []


@pytest.mark.parametrize(
    ("available", "expected"), [(1, 1), (2, 1), (8, 4), (16, 8), (32, 16), (64, 16)]
)
def test_automatic_workers_respect_cpu_affinity(
    monkeypatch: pytest.MonkeyPatch,
    available: int,
    expected: int,
) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 64)

    def affinity(_pid: int) -> set[int]:
        return set(range(available))

    monkeypatch.setattr(os, "sched_getaffinity", affinity)
    assert ranges.default_range_workers() == expected


def test_automatic_workers_fall_back_when_affinity_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_pid: int) -> set[int]:
        raise OSError("affinity unavailable")

    monkeypatch.setattr(os, "sched_getaffinity", unavailable)
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert ranges.default_range_workers() == 1
