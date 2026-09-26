from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.agents import BotAgent
from gwent_evaluation import (
    AgentSpec,
    BootstrapConfig,
    CorruptRecordError,
    EvidencePolicy,
    IntervalMethod,
    LoadedRun,
    ReportError,
    ResolvedAgent,
    RunExecution,
    RunStore,
    SuiteSpec,
    build_run_report,
    compare_runs,
    load_run,
    render_comparison_markdown,
    render_report_markdown,
    report_run,
)

from tests.engine.ai.bots import ThrowingBot
from tests.evaluation.support import (
    DECK_A,
    DECK_B,
    execute_suite,
    greedy_agent,
    heuristic_agent,
    int_field,
    read_json_object,
    suite_spec,
    write_json_object,
)


def _suite(
    *,
    suite_id: str = "reporting-test",
    candidate: AgentSpec | None = None,
    seeds: tuple[int, ...] = (3,),
    deck_pairs: tuple[tuple[str, str], ...] = ((DECK_A, DECK_B),),
) -> SuiteSpec:
    return suite_spec(
        suite_id=suite_id,
        candidate=candidate,
        seeds=seeds,
        deck_pairs=deck_pairs,
    )


def _execute(
    output_root: Path,
    *,
    suite: SuiteSpec | None = None,
    run_id: str = "run",
) -> RunExecution:
    return execute_suite(
        output_root,
        suite=suite or _suite(),
        run_id=run_id,
        evidence_policy=EvidencePolicy.FAILURES,
    )


def test_execute_run_writes_json_and_markdown_reports(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    root = execution.root

    assert (root / "report.json").is_file()
    assert (root / "report.md").is_file()
    payload = read_json_object(root / "report.json")
    assert payload["schema_version"] == 1
    assert payload["run_id"] == "run"
    assert payload["suite_id"] == "reporting-test"
    assert payload["observation_contract_version"] == 1
    assert payload["planned_matches"] == len(execution.results)
    assert payload["completed_matches"] == len(execution.results)
    assert payload["failed_matches"] == 0
    assert payload["missing_matches"] == 0
    assert payload["valid_for_comparison"] is True
    assert payload["validity_reasons"] == []
    candidate = cast(dict[str, object], payload["candidate"])
    assert int_field(candidate, "completed") == len(execution.results)
    total = (
        int_field(candidate, "wins")
        + int_field(candidate, "draws")
        + int_field(candidate, "losses")
    )
    assert total == len(execution.results)
    interval = cast(dict[str, object], payload["interval"])
    assert interval["method"] == IntervalMethod.INSUFFICIENT_SAMPLE.value
    latency = cast(dict[str, object], payload["latency"])
    assert int_field(latency, "transitions") > 0
    strata = cast(list[object], payload["strata"])
    assert strata
    markdown = (root / "report.md").read_text(encoding="utf-8")
    assert "# Run report: run" in markdown
    assert "## Candidate score" in markdown


def test_manifest_round_trips_through_storage(tmp_path: Path) -> None:
    execution = _execute(tmp_path)

    manifest = RunStore.from_root(execution.root).read_manifest()

    assert manifest.run_id == "run"
    assert manifest.suite.suite_id == "reporting-test"
    assert manifest.planned_case_ids == tuple(result.case_id for result in execution.results)
    assert manifest.candidate.agent_id == "candidate"


def test_manifest_identity_tampering_is_detected(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    path = execution.root / "manifest.json"
    document = dict(read_json_object(path))
    suite = dict(cast(dict[str, object], document["suite"]))
    suite["suite_id"] = "tampered"
    document["suite"] = suite
    write_json_object(path, document)

    with pytest.raises(CorruptRecordError, match="identity mismatch"):
        _ = RunStore.from_root(execution.root).read_manifest()


def test_schedule_content_tampering_is_detected(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    path = execution.root / "schedule.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = dict(cast(dict[str, object], json.loads(lines[0])))
    first["requested_starting_player"] = (
        "p2" if first["requested_starting_player"] == "p1" else "p1"
    )
    lines[0] = json.dumps(first)
    _ = path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(CorruptRecordError, match="does not match its manifest"):
        _ = load_run(execution.root)


def test_report_records_failures_without_manufacturing_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build(_self: ResolvedAgent, *, bot_id: str, seed: int | None = None) -> BotAgent:
        del seed
        return ThrowingBot(bot_id=bot_id)

    monkeypatch.setattr(ResolvedAgent, "build", build)

    execution = _execute(tmp_path)
    report = build_run_report(load_run(execution.root))

    assert report.failed_matches == report.planned_matches
    assert report.executed_matches == report.planned_matches
    assert report.candidate.completed == 0
    assert report.candidate.score is None
    assert report.balanced_score is None
    assert report.valid_for_comparison is False
    assert report.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE
    assert report.validity_reasons
    markdown = render_report_markdown(report)
    assert "## Validity" in markdown
    assert "did not complete" in markdown


def test_report_run_rebuilds_persisted_report(tmp_path: Path) -> None:
    execution = _execute(tmp_path)

    rebuilt = report_run(execution.root)

    assert rebuilt == build_run_report(load_run(execution.root))


def test_missing_result_is_reported_as_invalid(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    missing_case_id = execution.results[0].case_id
    (execution.root / "matches" / f"{missing_case_id}.json").unlink()

    report = build_run_report(load_run(execution.root))

    assert report.missing_matches == 1
    assert report.valid_for_comparison is False
    assert report.completed_matches == report.planned_matches - 1


def test_completed_result_without_score_is_rejected(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    loaded = load_run(execution.root)
    case_id = loaded.manifest.planned_case_ids[0]
    corrupted = dict(loaded.results)
    corrupted[case_id] = replace(corrupted[case_id], candidate_score=None)

    with pytest.raises(ReportError, match="no candidate score"):
        _ = build_run_report(
            LoadedRun(manifest=loaded.manifest, matches=loaded.matches, results=corrupted)
        )


def test_report_building_is_deterministic(tmp_path: Path) -> None:
    execution = _execute(tmp_path)

    first = build_run_report(load_run(execution.root))
    second = build_run_report(load_run(execution.root))

    assert first == second


def test_compare_runs_of_same_suite_is_valid(tmp_path: Path) -> None:
    reference = _execute(
        tmp_path / "reference",
        suite=_suite(candidate=greedy_agent()),
        run_id="reference",
    )
    candidate = _execute(
        tmp_path / "candidate",
        suite=_suite(candidate=heuristic_agent()),
        run_id="candidate",
    )

    comparison = compare_runs(reference.root, candidate.root)

    assert comparison.compatible is True
    assert comparison.valid is True
    assert comparison.reasons == ()
    assert len(comparison.block_differences) == 1
    assert comparison.mean_difference == cast(float, comparison.candidate_score) - cast(
        float, comparison.reference_score
    )
    assert comparison.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE
    markdown = render_comparison_markdown(comparison)
    assert "## Paired blocks" in markdown
    assert "Valid for comparison: yes" in markdown


def test_compare_runs_reports_block_bootstrap_interval(tmp_path: Path) -> None:
    reference = _execute(
        tmp_path / "reference",
        suite=_suite(suite_id="paired-test", seeds=(3, 11)),
        run_id="reference",
    )
    candidate = _execute(
        tmp_path / "candidate",
        suite=_suite(
            suite_id="paired-test",
            candidate=heuristic_agent(),
            seeds=(3, 11),
        ),
        run_id="candidate",
    )
    bootstrap = BootstrapConfig(minimum_blocks=2, resamples=200)

    comparison = compare_runs(reference.root, candidate.root, bootstrap=bootstrap)

    assert comparison.valid is True
    assert len(comparison.block_differences) == 2
    assert comparison.interval.method is IntervalMethod.BLOCK_BOOTSTRAP
    assert comparison.interval.blocks == 2
    assert comparison.interval.resamples == 200
    lower = comparison.interval.lower
    upper = comparison.interval.upper
    mean = comparison.mean_difference
    assert lower is not None
    assert upper is not None
    assert mean is not None
    assert lower <= mean <= upper


def test_compare_runs_to_itself_has_zero_difference(tmp_path: Path) -> None:
    execution = _execute(
        tmp_path,
        suite=_suite(suite_id="self-test", seeds=(3, 11)),
    )
    bootstrap = BootstrapConfig(minimum_blocks=2, resamples=200)

    comparison = compare_runs(execution.root, execution.root, bootstrap=bootstrap)

    assert comparison.valid is True
    assert comparison.mean_difference == 0.0
    assert comparison.interval.lower == 0.0
    assert comparison.interval.upper == 0.0


def test_incompatible_runs_are_rejected(tmp_path: Path) -> None:
    reference = _execute(
        tmp_path / "reference",
        suite=_suite(suite_id="comparison-a"),
        run_id="reference",
    )
    candidate = _execute(
        tmp_path / "candidate",
        suite=_suite(suite_id="comparison-b", deck_pairs=((DECK_A, DECK_A),)),
        run_id="candidate",
    )

    comparison = compare_runs(reference.root, candidate.root)

    assert comparison.compatible is False
    assert comparison.valid is False
    assert any(reason.startswith("suite ids differ") for reason in comparison.reasons)
    assert "scheduled case sets differ" in comparison.reasons
    assert comparison.block_differences == ()
    assert comparison.mean_difference is None
    assert comparison.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE


def test_incomplete_run_comparison_is_diagnostic_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete = _execute(tmp_path / "complete", run_id="complete")

    def build(_self: ResolvedAgent, *, bot_id: str, seed: int | None = None) -> BotAgent:
        del seed
        return ThrowingBot(bot_id=bot_id)

    with monkeypatch.context() as patch:
        patch.setattr(ResolvedAgent, "build", build)
        failing = _execute(tmp_path / "failing", run_id="failing")

    comparison = compare_runs(failing.root, complete.root)

    assert comparison.compatible is True
    assert comparison.valid is False
    assert any("did not complete" in reason for reason in comparison.reasons)
    assert comparison.interval.method is IntervalMethod.INSUFFICIENT_SAMPLE
    markdown = render_comparison_markdown(comparison)
    assert "Valid for comparison: no" in markdown
    assert "## Reasons" in markdown
