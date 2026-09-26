from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.agents import BotAgent
from gwent_engine.ai.arena import execute_match as engine_execute_match
from gwent_engine.ai.arena.models import (
    MatchExecution,
    MatchFailureStage,
    TerminationReason,
)
from gwent_evaluation import AgentSpec, EvidencePolicy, SuiteSpec
from gwent_evaluation import execution as execution_module
from gwent_evaluation.agents import ResolvedAgent
from gwent_evaluation.models import MatchResult, RunExecution
from gwent_evaluation.records import CorruptRecordError
from gwent_evaluation.storage import RunConflictError

from tests.engine.ai.bots import ThrowingBot
from tests.evaluation.support import (
    evaluation_suite,
    execute_evaluation_suite,
    greedy_agent,
    read_json_object,
    write_json_object,
)


def _suite(
    *,
    candidate: AgentSpec | None = None,
    opponents: tuple[AgentSpec, ...] | None = None,
) -> SuiteSpec:
    return evaluation_suite("execution-test", candidate=candidate, opponents=opponents)


def _execute(
    output_root: Path,
    *,
    suite: SuiteSpec | None = None,
    run_id: str = "run",
    evidence_policy: EvidencePolicy = EvidencePolicy.FAILURES,
) -> RunExecution:
    return execute_evaluation_suite(
        output_root,
        suite=suite or _suite(),
        run_id=run_id,
        evidence_policy=evidence_policy,
    )


def _semantics(results: tuple[MatchResult, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            result.case_id,
            result.termination.value,
            result.winner,
            result.candidate_score,
            result.semantic_digest,
        )
        for result in results
    )


def test_run_persists_manifest_schedule_results_and_samples(tmp_path: Path) -> None:
    execution = _execute(tmp_path)

    root = tmp_path / "run"
    assert execution.root == root
    assert execution.executed_case_ids == tuple(result.case_id for result in execution.results)
    assert execution.resumed_case_ids == ()
    assert len(execution.results) == 8

    manifest = read_json_object(root / "manifest.json")
    assert manifest["run_id"] == "run"
    assert manifest["manifest_identity"]
    planned_case_ids = cast(list[object], manifest["planned_case_ids"])
    assert len(planned_case_ids) == 8
    assert len((root / "schedule.jsonl").read_text(encoding="utf-8").splitlines()) == 8

    for result in execution.results:
        assert result.termination is TerminationReason.COMPLETED
        assert result.candidate_score in {0.0, 0.5, 1.0}
        assert result.evidence.trajectory_path is None
        assert result.evidence.samples_path is not None
        assert (root / result.evidence.samples_path).is_file()
    assert len(list((root / "matches").glob("*.json"))) == 8


def test_interrupted_run_resumes_with_identical_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uninterrupted = _execute(tmp_path / "uninterrupted")
    real_execute_match: Callable[..., MatchExecution] = engine_execute_match
    calls = 0

    def interrupting(*args: object, **kwargs: object) -> MatchExecution:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise RuntimeError("simulated interruption")
        return real_execute_match(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(execution_module, "execute_match", interrupting)
        with pytest.raises(RuntimeError, match="simulated interruption"):
            _ = _execute(tmp_path / "interrupted")

    resumed = _execute(tmp_path / "interrupted")

    assert resumed.executed_case_ids == uninterrupted.executed_case_ids[2:]
    assert resumed.resumed_case_ids == uninterrupted.executed_case_ids[:2]
    assert _semantics(resumed.results) == _semantics(uninterrupted.results)


def test_corrupt_result_is_detected(tmp_path: Path) -> None:
    execution = _execute(tmp_path)
    result_path = tmp_path / "run" / "matches" / f"{execution.results[0].case_id}.json"
    document = dict(read_json_object(result_path))
    document["winner"] = "p2" if document["winner"] != "p2" else "p1"
    write_json_object(result_path, document)

    with pytest.raises(CorruptRecordError, match="digest mismatch"):
        _ = _execute(tmp_path)


def test_throwing_bot_records_explicit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build(_self: ResolvedAgent, *, bot_id: str, seed: int | None = None) -> BotAgent:
        del seed
        return ThrowingBot(bot_id=bot_id)

    monkeypatch.setattr(ResolvedAgent, "build", build)

    execution = _execute(tmp_path)

    for result in execution.results:
        assert result.termination is TerminationReason.AGENT_ERROR
        assert result.candidate_score is None
        assert result.winner is None
        assert result.failure is not None
        assert result.failure.stage is MatchFailureStage.CHOOSE_MULLIGAN
        assert result.failure.exception_type == "RuntimeError"
        assert result.evidence.trajectory_path is not None
        assert (execution.root / result.evidence.trajectory_path).is_file()


def test_rerunning_completed_run_performs_no_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _execute(tmp_path)

    def unexpected(*args: object, **kwargs: object) -> MatchExecution:
        del args, kwargs
        raise AssertionError("completed cases must not be re-executed")

    with monkeypatch.context() as patch:
        patch.setattr(execution_module, "execute_match", unexpected)
        second = _execute(tmp_path)

    assert second.executed_case_ids == ()
    assert second.resumed_case_ids == first.executed_case_ids
    assert _semantics(second.results) == _semantics(first.results)


def test_conflicting_run_is_rejected(tmp_path: Path) -> None:
    _ = _execute(tmp_path)
    conflicting = _suite(opponents=(greedy_agent("other-opponent"),))

    with pytest.raises(RunConflictError, match="different manifest"):
        _ = _execute(tmp_path, suite=conflicting)


def test_evidence_policy_all_persists_trajectory(tmp_path: Path) -> None:
    execution = _execute(tmp_path, evidence_policy=EvidencePolicy.ALL)

    for result in execution.results:
        assert result.evidence.trajectory_path is not None
        trajectory_path = execution.root / result.evidence.trajectory_path
        payload = read_json_object(trajectory_path)
        assert payload["case_id"] == result.case_id
        steps = cast(list[object], payload["steps"])
        assert steps
