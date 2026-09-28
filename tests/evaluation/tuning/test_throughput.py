"""Throughput measurements preserve workload shape and use diagnostic seeds only."""

from pathlib import Path
from typing import cast

import pytest
from gwent_evaluation.models import SpecError, SuitePurpose
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.storage import read_record_mapping
from gwent_evaluation.tuning import throughput
from gwent_evaluation.tuning.specs import load_study_spec
from gwent_evaluation.tuning.storage import StudyStore

from tests.evaluation.support import REPOSITORY_ROOT


def test_throughput_suites_keep_production_shape_with_separate_smoke_seeds() -> None:
    study = load_study_spec(
        REPOSITORY_ROOT / "experiments/tuning/benchmark-v2.json", repository_root=REPOSITORY_ROOT
    )
    existing = set(
        study.optimization.suite.seeds + study.validation.suite.seeds + study.test.suite.seeds
    )
    for name, original, expected in (
        ("screening", study.optimization.suite, 1024),
        ("recheck", study.validation.suite, 2048),
    ):
        suite = throughput.workload_suite(original, study.incumbent, name=name)
        assert len(schedule_suite(suite)) == expected
        assert suite.purpose is SuitePurpose.SMOKE
        assert set(suite.seeds).isdisjoint(existing)
        assert suite.opponents == original.opponents and suite.deck_pairs == original.deck_pairs
        assert suite.action_budget == original.action_budget
        assert suite.candidate.heuristic_configuration == study.incumbent


@pytest.mark.parametrize("workers", [(), (4, 8), (1, 1), (1, 0), (1, True)])
def test_invalid_throughput_counts_fail_before_files(
    tmp_path: Path, workers: tuple[int, ...]
) -> None:
    with pytest.raises(SpecError):
        throughput.measure_throughput(
            tmp_path / "missing", tmp_path / "output", workers=workers, repeats=1
        )
    assert not (tmp_path / "output").exists()


def test_throughput_report_rebuild_reuses_measurements_without_games(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot: dict[str, object] = {"hardware": {"cpu_model": "fixture"}}
    rows: list[dict[str, object]] = [
        {"workload": "screening", "workers": w, "seconds": s, "games": 1024}
        for w, s in [(1, 100.0), (8, 20.0), (1, 102.0), (8, 22.0)]
    ]
    store = StudyStore(tmp_path)
    with store.writer():
        store.prepare(snapshot)
        for row in rows:
            _ = store.record("measurement", row)
        _ = store.record("complete", {"measurements": len(rows)})
        store.finish()

    def no_games(*_args: object, **_kwargs: object) -> None:
        pytest.fail("report rebuilding must play no games")

    monkeypatch.setattr(throughput, "execute_run", no_games)
    throughput.rebuild_throughput_report(tmp_path)
    before = (tmp_path / "report.json").read_bytes()
    throughput.rebuild_throughput_report(tmp_path)
    assert (tmp_path / "report.json").read_bytes() == before
    summary = cast(
        list[dict[str, object]], read_record_mapping(tmp_path / "report.json")["summary"]
    )
    assert summary[0]["median_seconds"] == 101.0
    assert summary[1]["median_seconds"] == 21.0
    assert summary[1]["speedup"] == 101 / 21
    assert "<svg" in (tmp_path / "report.html").read_text()
