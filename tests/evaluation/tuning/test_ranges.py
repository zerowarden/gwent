"""Range experiments preserve pairing, stop on bad evidence, and never use test games."""

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_evaluation.models import MatchResult, SpecError, SuitePurpose, TerminationReason
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning import ranges
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.specs import load_study_spec

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
        ranges.run_ranges(protocol, root)
    assert json.loads((root / "screening/report.json").read_text())["status"] == "interrupted"
    ranges.run_ranges(protocol, root)
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
        ranges.run_ranges(protocol, root)


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
        ranges.run_ranges(protocol, root)
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
