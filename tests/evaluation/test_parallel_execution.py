"""Bounded dispatch, process transport and coordinator-owned recovery on smoke seeds."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import multiprocessing
import os
import signal
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from multiprocessing.synchronize import Barrier, Event
from pathlib import Path
from time import perf_counter
from typing import NoReturn, cast, final
from unittest.mock import patch

import pytest
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_evaluation import execution
from gwent_evaluation.execution import EvidencePolicy, RunExecution
from gwent_evaluation.models import MatchResult, RunManifest, ScheduledMatch, SpecError, SuiteSpec
from gwent_evaluation.progress import Progress, observe
from gwent_evaluation.records import CorruptRecordError
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.storage import RunStore
from gwent_evaluation.tuning.storage import StudyLockedError, exclusive_writer

from tests.evaluation.support import REPOSITORY_ROOT, heuristic_agent, suite_spec


def _suite(*, action_budget: int = 512) -> SuiteSpec:
    config = HeuristicConfiguration()
    config = replace(
        config,
        baseline=replace(
            config.baseline, weights=replace(config.baseline.weights, card_advantage=4.0)
        ),
    )
    return suite_spec(
        suite_id="parallel-smoke",
        seeds=(780013,),
        action_budget=action_budget,
        candidate=replace(heuristic_agent(), heuristic_configuration=config),
    )


def _run(root: Path, *, workers: int = 1, suite: SuiteSpec | None = None) -> RunExecution:
    return execution.execute_run(
        suite=suite or _suite(),
        run_id="run",
        output_root=root,
        repository_root=REPOSITORY_ROOT,
        evidence_policy=EvidencePolicy.NONE,
        workers=workers,
    )


def _no_pool(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("No process pool or game should start")


@pytest.mark.parametrize("workers", [True, False, 0, -2, 1.5, "2"])
def test_invalid_workers_rejected_before_writes(tmp_path: Path, workers: int) -> None:
    with pytest.raises(SpecError, match="positive integer"):
        _ = _run(tmp_path / "invalid", workers=workers)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("policy", [EvidencePolicy.ALL, EvidencePolicy.FAILURES])
def test_parallel_trajectory_rejected_before_writes(tmp_path: Path, policy: EvidencePolicy) -> None:
    with pytest.raises(SpecError, match="evidence policy"):
        _ = execution.execute_run(
            suite=_suite(),
            run_id="run",
            output_root=tmp_path / "invalid",
            repository_root=REPOSITORY_ROOT,
            evidence_policy=policy,
            workers=2,
        )
    assert not (tmp_path / "invalid").exists()


def test_real_spawned_results_match_serial_and_completed_run_never_creates_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_property: Callable[[str, object], None]
) -> None:
    start = perf_counter()
    with monkeypatch.context() as scoped:
        scoped.setattr(execution, "ProcessPoolExecutor", _no_pool)
        serial = _run(tmp_path / "serial")
    serial_seconds = perf_counter() - start
    start = perf_counter()
    parallel = _run(tmp_path / "parallel", workers=2)
    parallel_seconds = perf_counter() - start
    record_property("serial_wall_seconds", serial_seconds)
    record_property("parallel_wall_seconds", parallel_seconds)
    print(f"Smoke observation: serial={serial_seconds:.3f}s, parallel={parallel_seconds:.3f}s")
    assert serial.report.completed_matches == parallel.report.completed_matches == 8
    assert serial.executed_case_ids == parallel.executed_case_ids
    for a, b in zip(serial.results, parallel.results, strict=True):
        assert (
            replace(a, execution_seconds=b.execution_seconds, decision_seconds=b.decision_seconds)
            == b
        )
    assert replace(serial.report, latency=parallel.report.latency) == parallel.report
    monkeypatch.setattr(execution, "ProcessPoolExecutor", _no_pool)
    monkeypatch.setattr(execution, "execute_case", _no_pool)
    repeated = _run(tmp_path / "parallel", workers=4)
    assert repeated.results == parallel.results
    assert repeated.executed_case_ids == ()
    assert repeated.resumed_case_ids == parallel.executed_case_ids
    assert repeated.report == parallel.report


@final
class ControlledPool:
    """Completed futures with deliberately reversed delivery, without background work."""

    def __init__(self, outcomes: dict[str, MatchResult | BaseException], *, bound: int) -> None:
        self.outcomes = outcomes
        self.bound = bound
        self.pending: dict[Future[MatchResult], ScheduledMatch] = {}
        self.submitted: list[str] = []
        self.closed = False
        self.interrupt_ignored = False

    def submit(self, _fn: object, match: ScheduledMatch) -> Future[MatchResult]:
        assert len(self.pending) < self.bound
        future: Future[MatchResult] = Future()
        outcome = self.outcomes[match.case_id]
        if isinstance(outcome, BaseException):
            future.set_exception(outcome)
        else:
            future.set_result(outcome)
        self.pending[future] = match
        self.submitted.append(match.case_id)
        return future

    def wait(
        self, pending: Iterable[Future[MatchResult]], *, return_when: str
    ) -> tuple[set[Future[MatchResult]], set[Future[MatchResult]]]:
        assert return_when == "FIRST_COMPLETED"
        assert set(self.pending) == set(pending)
        future = next(reversed(self.pending))
        del self.pending[future]
        return {future}, set(self.pending)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        assert wait and cancel_futures
        self.interrupt_ignored = signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        self.closed = True


def _install_pool(monkeypatch: pytest.MonkeyPatch, pool: ControlledPool) -> None:
    def factory(**kwargs: object) -> ControlledPool:
        assert kwargs["max_workers"] == pool.bound
        assert kwargs["initializer"] is execution._initialize_summary_worker
        return pool

    monkeypatch.setattr(execution, "ProcessPoolExecutor", factory)
    monkeypatch.setattr(execution, "wait", pool.wait)


def test_out_of_order_save_interrupt_and_resume_only_missing_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _run(tmp_path / "reference")
    pool = ControlledPool({r.case_id: r for r in reference.results}, bound=2)
    root = tmp_path / "interrupted"
    original = RunStore.write_result
    saved: list[str] = []
    interrupt = KeyboardInterrupt("stop after two saves")

    def save(store: RunStore, result: MatchResult) -> None:
        original(store, result)
        saved.append(result.case_id)
        if len(saved) == 2:
            raise interrupt

    with monkeypatch.context() as scoped:
        _install_pool(scoped, pool)
        scoped.setattr(RunStore, "write_result", save)
        with pytest.raises(KeyboardInterrupt) as caught:
            _ = _run(root, workers=2)
        assert caught.value is interrupt
    assert pool.closed and pool.interrupt_ignored
    assert len(pool.submitted) == 3  # Replenish only after persistence succeeds.
    assert saved == list(reference.executed_case_ids[1:3])
    assert not (root / "run/report.json").exists()
    before = {p: p.read_bytes() for p in (root / "run/matches").glob("*.json")}
    resumed = _run(root, workers=3)
    assert resumed.executed_case_ids == tuple(
        c for c in reference.executed_case_ids if c not in saved
    )
    assert resumed.resumed_case_ids == tuple(saved)
    assert tuple(r.case_id for r in resumed.results) == reference.executed_case_ids
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("failure", [RuntimeError("worker task"), BrokenProcessPool("initializer")])
def test_worker_error_stops_dispatch_and_propagates_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    reference = _run(tmp_path / "reference", suite=_suite(action_budget=1))
    pool = ControlledPool({r.case_id: failure for r in reference.results}, bound=2)
    _install_pool(monkeypatch, pool)
    with pytest.raises(type(failure)) as caught:
        _ = _run(tmp_path / "failed", workers=2, suite=_suite(action_budget=1))
    assert caught.value is failure
    assert pool.closed and pool.submitted == list(reference.executed_case_ids[:2])
    assert not list((tmp_path / "failed/run/matches").glob("*.json"))
    assert not (tmp_path / "failed/run/report.json").exists()


def test_save_error_cleans_up_without_replacing_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _run(tmp_path / "reference", suite=_suite(action_budget=1))
    pool = ControlledPool({r.case_id: r for r in reference.results}, bound=2)
    _install_pool(monkeypatch, pool)
    error = OSError("disk unavailable")

    def fail(_store: RunStore, _result: MatchResult) -> NoReturn:
        raise error

    monkeypatch.setattr(RunStore, "write_result", fail)
    with pytest.raises(OSError) as caught:
        _ = _run(tmp_path / "failed", workers=2, suite=_suite(action_budget=1))
    assert caught.value is error
    assert pool.closed and pool.interrupt_ignored
    assert len(pool.submitted) == 2


def test_real_process_action_limit_remains_explicit_and_corruption_precedes_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, workers=2, suite=_suite(action_budget=1))
    assert run.report.failed_matches == len(run.results)
    assert all(
        r.termination.value == "action_limit" and r.candidate_score is None for r in run.results
    )
    monkeypatch.setattr(execution, "ProcessPoolExecutor", _no_pool)
    assert _run(tmp_path, workers=3, suite=_suite(action_budget=1)).results == run.results
    path = run.root / "matches" / f"{run.results[-1].case_id}.json"
    _ = path.write_text(
        path.read_text().replace('"accepted_transitions": 1', '"accepted_transitions": 2')
    )
    with pytest.raises(CorruptRecordError):
        _ = _run(tmp_path, workers=2, suite=_suite(action_budget=1))


# Module-level callables are imported in real spawned processes. Parent monkeypatches
# deliberately do not supply game behavior or provenance inside these children.
_gate: tuple[Barrier, Event, str, Path] | None = None


def _initialize_gated_worker(
    manifest: RunManifest,
    repository: Path,
    barrier: Barrier,
    release: Event,
    fast_case: str,
    root: Path,
) -> None:
    global _gate
    execution._initialize_summary_worker(manifest, repository)
    _gate = barrier, release, fast_case, root


def _gated_case(match: ScheduledMatch) -> MatchResult:
    assert _gate is not None
    barrier, release, fast_case, root = _gate
    (root / f"worker-{os.getpid()}").touch()
    _ = barrier.wait(timeout=30)
    if match.case_id != fast_case and not release.wait(30):
        raise TimeoutError("test worker was not released")
    return execution._execute_summary_case(match)


def _locked_coordinator(root: Path, barrier: Barrier, release: Event, shutting_down: Event) -> None:
    suite = _suite(action_budget=1)
    fast_case = schedule_suite(suite)[0].case_id
    original_write = RunStore.write_result

    def factory(**kwargs: object) -> ProcessPoolExecutor:
        manifest, repository = cast(tuple[RunManifest, Path], kwargs["initargs"])
        return ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize_gated_worker,
            initargs=(manifest, repository, barrier, release, fast_case, root),
        )

    def interrupt(store: RunStore, result: MatchResult) -> None:
        original_write(store, result)
        raise KeyboardInterrupt

    def progress(event: Progress) -> None:
        if "dispatch stopped" in event.detail:
            shutting_down.set()

    with (
        exclusive_writer(root),
        observe(progress),
        patch.object(execution, "ProcessPoolExecutor", factory),
        patch.object(execution, "_execute_summary_case", _gated_case),
        patch.object(RunStore, "write_result", interrupt),
    ):
        try:
            _ = _run(root, workers=2, suite=suite)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("expected interruption")


def test_real_overlap_and_active_writer_remains_locked_until_workers_exit(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    barrier, release, shutting_down = context.Barrier(2), context.Event(), context.Event()
    process = context.Process(
        target=_locked_coordinator, args=(tmp_path, barrier, release, shutting_down)
    )
    process.start()
    try:
        assert shutting_down.wait(40), "coordinator never reached shutdown"
        # Passing the two-party barrier proves overlap without a speed threshold.
        assert len(list(tmp_path.glob("worker-*"))) == 2
        assert len(list((tmp_path / "run/matches").glob("*.json"))) == 1
        for recover in (False, True):
            with pytest.raises(StudyLockedError, match="already owns"):
                with exclusive_writer(tmp_path, recover_lock=recover):
                    pytest.fail("active writer displaced")
        assert process.pid is not None
        os.kill(process.pid, signal.SIGINT)
        release.set()
        process.join(40)
        assert process.exitcode == 0
        before = {p: p.read_bytes() for p in (tmp_path / "run/matches").glob("*.json")}
        with exclusive_writer(tmp_path):
            resumed = _run(tmp_path, workers=3, suite=_suite(action_budget=1))
        assert len(resumed.resumed_case_ids) == 1 and len(resumed.executed_case_ids) == 7
        assert all(p.read_bytes() == data for p, data in before.items())
    finally:
        release.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)


def _raise_task(_match: ScheduledMatch) -> NoReturn:
    raise RuntimeError("spawned task failed")


def _die_task(_match: ScheduledMatch) -> NoReturn:
    os._exit(7)


@pytest.mark.parametrize("mode", ["initialization", "task", "death"])
def test_real_process_failure_has_no_fabricated_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    if mode == "initialization":

        def factory(**kwargs: object) -> ProcessPoolExecutor:
            manifest, repository = cast(tuple[RunManifest, Path], kwargs["initargs"])
            stale = replace(manifest, runtime=replace(manifest.runtime, python_version="0.0"))
            return ProcessPoolExecutor(
                max_workers=2,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=execution._initialize_summary_worker,
                initargs=(stale, repository),
            )

        monkeypatch.setattr(execution, "ProcessPoolExecutor", factory)
    else:
        monkeypatch.setattr(
            execution, "_execute_summary_case", _raise_task if mode == "task" else _die_task
        )
    with pytest.raises(RuntimeError if mode == "task" else BrokenProcessPool):
        _ = _run(tmp_path, workers=2, suite=_suite(action_budget=1))
    assert not list((tmp_path / "run/matches").glob("*.json"))
    assert not (tmp_path / "run/report.json").exists()


def test_worker_result_is_validated_before_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _run(tmp_path / "reference", suite=_suite(action_budget=1))
    pool = ControlledPool(
        {r.case_id: replace(r, environment_seed=-1) for r in reference.results}, bound=2
    )
    _install_pool(monkeypatch, pool)
    with pytest.raises(CorruptRecordError):
        _ = _run(tmp_path / "invalid", workers=2, suite=_suite(action_budget=1))
    assert pool.closed
    assert not list((tmp_path / "invalid/run/matches").glob("*.json"))


def test_pool_size_is_capped_by_missing_games(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = _suite(action_budget=1)
    reference = _run(tmp_path / "reference", suite=suite)
    loaded = RunStore.from_root(reference.root).load()
    partial = RunStore(tmp_path / "partial", "run")
    _ = partial.prepare(loaded.manifest, matches=loaded.matches)
    for result in reference.results[:-1]:
        partial.write_result(result)
    remaining = reference.results[-1]
    pool = ControlledPool({remaining.case_id: remaining}, bound=1)
    _install_pool(monkeypatch, pool)
    resumed = _run(tmp_path / "partial", workers=8, suite=suite)
    assert pool.closed and pool.submitted == [remaining.case_id]
    assert resumed.results == reference.results
    assert resumed.executed_case_ids == (remaining.case_id,)
    assert resumed.resumed_case_ids == reference.executed_case_ids[:-1]


def test_progress_counts_persisted_games_and_resume_from_gaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import StringIO

    from gwent_evaluation.progress import TerminalProgress, stage

    suite = _suite(action_budget=1)
    reference = _run(tmp_path / "reference", suite=suite)
    loaded = RunStore.from_root(reference.root).load()
    partial = RunStore(tmp_path / "partial", "run")
    _ = partial.prepare(loaded.manifest, matches=loaded.matches)
    for index in (1, 3):
        partial.write_result(reference.results[index])
    pool = ControlledPool({r.case_id: r for r in reference.results}, bound=3)
    _install_pool(monkeypatch, pool)
    stream = StringIO()
    renderer = TerminalProgress(stream)
    events: list[Progress] = []
    original_update = renderer.update

    def update(event: Progress) -> None:
        if event.completed is not None:
            assert event.completed == len(list((partial.root / "matches").glob("*.json")))
            events.append(event)
        original_update(event)

    monkeypatch.setattr(renderer, "update", update)
    with renderer.display(), stage("range recheck"):
        _ = _run(tmp_path / "partial", workers=3, suite=suite)
    assert [event.completed for event in events] == list(range(2, 9))
    assert {event.stage for event in events} == {"range recheck"}
    assert len({event.detail for event in events}) == 1
    assert all(event.detail.endswith("/ 3 workers") and event.total == 8 for event in events)
    assert len(stream.getvalue().splitlines()) == 6
    assert "\x1b" not in stream.getvalue()
    assert "8/8" in stream.getvalue()

    monkeypatch.setattr(execution, "ProcessPoolExecutor", _no_pool)
    events.clear()
    with renderer.display(), stage("range screening"):
        _ = _run(tmp_path / "partial", workers=8, suite=suite)
    assert len(events) == 1
    assert events[0].completed == 8 and events[0].detail.endswith("/ 0 workers")


def test_progress_shows_actual_pool_size_when_fewer_games_remain(
    tmp_path: Path,
) -> None:
    events: list[Progress] = []
    with observe(events.append):
        _ = _run(tmp_path, workers=16, suite=_suite(action_budget=1))
    games = [event for event in events if event.completed is not None]
    assert [event.completed for event in games] == list(range(9))
    assert all(event.detail.endswith("/ 8 workers") for event in games)
