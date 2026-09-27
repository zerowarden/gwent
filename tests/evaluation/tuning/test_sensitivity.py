"""Sensitivity is a strategy diagnostic, not a universal heuristic preference test."""

from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest
from gwent_evaluation import execution
from gwent_evaluation.assets import resolve_assets
from gwent_evaluation.models import SpecError, SuitePurpose
from gwent_evaluation.records import (
    CorruptRecordError,
    decision_sample_from_dict,
    decision_sample_to_dict,
)
from gwent_evaluation.storage import RunConflictError, RunStore, read_record_mapping
from gwent_evaluation.tuning import sensitivity
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.sensitivity import (
    DecisionDiagnostic,
    ObservationCase,
    compare_decisions,
    measure_dimensions,
    require_sensitivity,
    run_sensitivity,
    sensitivity_suite,
)

from tests.evaluation.support import REPOSITORY_ROOT

pytestmark = pytest.mark.allow_match_execution


def decision(*, offset: float = 0.0) -> DecisionDiagnostic:
    scores = (("a", 2.0 + offset), ("b", 1.0 + offset))
    return DecisionDiagnostic(scores, scores, "a", None, 2, 2, 2)


def test_common_score_shift_does_not_prove_relative_sensitivity() -> None:
    delta = compare_decisions(decision(), decision(offset=99))
    assert delta.relative_gap is None
    assert delta.all_action_gap is None
    assert not delta.ranking_changed
    assert not delta.final_action_changed


def test_tactical_override_and_score_ranking_are_reported_separately() -> None:
    before = replace(decision(), override_reason="minimum_commitment_finish")
    after = replace(before, scores=(("b", 3.0), ("a", 2.0)))
    delta = compare_decisions(before, after)
    assert delta.relative_gap is not None
    assert delta.ranking_changed
    assert not delta.final_action_changed
    assert after.override_reason == "minimum_commitment_finish"


def test_omitted_best_action_does_not_replace_the_production_choice() -> None:
    before = replace(decision(), scores=(("a", 2.0),), shortlisted_count=1)
    after = replace(before, all_scores=(("b", 9.0), ("a", 2.0)))
    assert after.best_action_omitted
    assert after.legal_count - after.shortlisted_count == 1
    assert after.retained_count == 2
    delta = compare_decisions(before, after)
    assert delta.relative_gap is None
    assert delta.all_action_gap is not None
    assert delta.all_action_ranking_changed
    assert not delta.final_action_changed


def test_panel_budget_is_checked_before_creating_runs(study: StudySpec, tmp_path: Path) -> None:
    too_small = replace(study, sensitivity=replace(study.sensitivity, max_pilot_matches=11))
    with pytest.raises(SpecError, match="exceeding"):
        _ = run_sensitivity(
            too_small, output_root=tmp_path / "pilot", repository_root=REPOSITORY_ROOT
        )
    assert not (tmp_path / "pilot").exists()


def test_tiny_panel_persists_reproducible_evidence_and_blocks_flat_sensitivity(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot = sensitivity_suite(study)
    assert pilot.purpose is SuitePurpose.DIAGNOSTIC
    assert pilot.seeds == study.sensitivity.pilot_seeds
    assert not set(pilot.seeds).intersection(study.validation.suite.seeds + study.test.suite.seeds)
    output = tmp_path / "pilot"
    report = run_sensitivity(study, output_root=output, repository_root=REPOSITORY_ROOT)
    assert report.planned_matches == report.executed_matches == 12
    assert tuple(item.name for item in report.controls) == (
        "incumbent",
        "lower-bounds",
        "upper-bounds",
    )
    assert all(item.completed == item.planned == 4 for item in report.controls)
    assert report.observation_count == 32
    assert len(report.dimensions) == 11
    assert all(item.witness is not None for item in report.dimensions)
    assert (
        sensitivity.SensitivityReport.from_dict(read_record_mapping(output / "report.json"))
        == report
    )
    assert report.match_execution_seconds > 0
    assert report.disk_bytes > 0

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Resuming a diagnostic must reuse completed matches")

    monkeypatch.setattr(execution, "execute_match", forbidden)
    resumed = run_sensitivity(study, output_root=output, repository_root=REPOSITORY_ROOT)
    assert resumed.executed_matches == 0
    assert resumed.dimensions == report.dimensions
    assert resumed.controls == report.controls
    assert resumed.observations_digest == report.observations_digest
    with pytest.raises(SpecError, match="different study"):
        require_sensitivity(study, replace(report, study_digest="stale"))
    inactive = replace(report.dimensions[0], relative_score_witnesses=0, witness=None)
    with pytest.raises(SpecError, match=f"{inactive.name}: insufficient relative-score"):
        require_sensitivity(
            study, replace(report, dimensions=(inactive, *report.dimensions[1:]), reasons=())
        )

    store = RunStore(output / "runs", "incumbent")
    case_ids = store.read_manifest().planned_case_ids
    loaded = store.load(sample_cases=case_ids)
    sample = next(sample for sample in loaded.samples[case_ids[0]] if sample.kind.value == "action")
    assert decision_sample_from_dict(decision_sample_to_dict(sample)) == sample
    assert not tuple(store.evidence_dir.glob("*.trajectory.json"))

    def flat_decision(*_args: object) -> DecisionDiagnostic:
        assert sample.chosen_option_id is not None
        return replace(decision(), chosen_action=sample.chosen_option_id)

    monkeypatch.setattr(sensitivity, "diagnose_decision", flat_decision)
    flat = measure_dimensions(study, (ObservationCase("synthetic-flat", sample),), resolve_assets())
    assert all(item.relative_score_witnesses == item.final_action_changes == 0 for item in flat)
    with pytest.raises(SpecError, match="insufficient_sensitivity"):
        require_sensitivity(study, replace(report, dimensions=flat, reasons=()))

    changed = replace(study, study_id="different-study")
    with pytest.raises(RunConflictError, match="different frozen study"):
        _ = run_sensitivity(changed, output_root=output, repository_root=REPOSITORY_ROOT)

    _ = store.samples_path(case_ids[0]).write_text("{}\n")
    with pytest.raises(CorruptRecordError, match="Evidence digest"):
        _ = store.load(sample_cases=case_ids)
