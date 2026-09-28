import json
from pathlib import Path
from typing import cast

import pytest
from gwent_evaluation.cli import main
from gwent_evaluation.tuning.models import StudySpec


def test_default_plan_and_env_paths_do_not_play_games(
    study_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GWENT_TUNING_SPEC", str(study_path))
    monkeypatch.setenv("GWENT_TUNING_OUTPUT_ROOT", str(tmp_path / "custom"))
    monkeypatch.setenv("GWENT_TUNING_STUDY_ID", "custom-study")
    assert main(["tune", "plan"]) == 0
    output = capsys.readouterr().out
    assert "custom-study" in output
    assert str(tmp_path / "custom/custom-study") in output
    assert "No games played" in output
    assert not (tmp_path / "custom").exists()
    assert main(["tune", "plan", "--study-id", "explicit", "--json"]) == 0
    payload = cast(dict[str, object], json.loads(capsys.readouterr().out))
    assert payload["study_id"] == "explicit"
    assert main(["tune", "plan", "--study-id", "../outside"]) == 2


def test_explicit_spec_overrides_environment(
    study_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GWENT_TUNING_SPEC", "/missing.json")
    assert main(["tune", "plan", str(study_path)]) == 0
    assert "tuning-smoke-v1" in capsys.readouterr().out


@pytest.mark.allow_match_execution
def test_smoke_workflow_and_candidate_latency_use_recorded_observations(
    study: StudySpec,
    tmp_path: Path,
) -> None:
    from gwent_evaluation.tuning.latency import measure_selected_latency
    from gwent_evaluation.tuning.study_report import build_study_report
    from gwent_evaluation.tuning.workflow import run_tuning

    from tests.evaluation.support import REPOSITORY_ROOT

    run_tuning(study, output_root=tmp_path, repository_root=REPOSITORY_ROOT)
    selected = study.bind((1.0,) * len(study.parameter_space.parameters))
    measure_selected_latency(study, selected, root=tmp_path, repository_root=REPOSITORY_ROOT)
    report = build_study_report(tmp_path)
    assert report.stage == "diagnostic_complete"
    assert report.verdict == "not_assessed"
    assert report.confirmation is None
    latency = cast(dict[str, object], report.inputs["selected_latency"])
    configurations = cast(list[dict[str, object]], latency["configurations"])
    assert [item["configuration_digest"] for item in configurations] == [
        study.incumbent.digest(),
        selected.digest(),
    ]
    assert configurations[0]["samples"] == configurations[1]["samples"]
    assert cast(int, configurations[0]["samples"]) > 0
    assert all(cast(float, item["mean_seconds"]) >= 0 for item in configurations)
    before = (tmp_path / "latency.json").read_bytes()
    measure_selected_latency(study, selected, root=tmp_path, repository_root=REPOSITORY_ROOT)
    assert (tmp_path / "latency.json").read_bytes() == before
