from __future__ import annotations

import multiprocessing
import signal
from collections.abc import Generator, Iterator
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import islice
from pathlib import Path
from threading import current_thread, main_thread
from time import perf_counter

from gwent_engine.ai.arena import MatchExecution, execute_match
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO
from gwent_engine.core.randomness import SeededRandom
from gwent_shared.extract import stringify_optional
from gwent_shared.json_payloads import canonical_digest

from gwent_evaluation.agents import ResolvedAgent, resolve_agent, snapshot_suite
from gwent_evaluation.assets import ResolvedAssets, resolve_assets
from gwent_evaluation.holdout import (
    HoldoutAuthorization,
    record_holdout_consumption,
    require_holdout_authorization,
)
from gwent_evaluation.models import (
    RECORD_SCHEMA_VERSION,
    AgentIdentity,
    AgentSpec,
    AssetIdentities,
    EvidenceRefs,
    MatchEvidence,
    MatchResult,
    RunManifest,
    ScheduledMatch,
    SpecError,
    SuiteSpec,
    candidate_score_for_outcome,
)
from gwent_evaluation.progress import advance
from gwent_evaluation.provenance import (
    SEED_DERIVATION_VERSION,
    read_repository_provenance,
    read_runtime_provenance,
)
from gwent_evaluation.recording import ExperimentRecorder, SummaryRecorder
from gwent_evaluation.reporting import RunReport, persist_run_report
from gwent_evaluation.schedule import CASE_ID_VERSION, other_seat, schedule_suite
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.validation import (
    LoadedRun,
    execution_identity,
    validate_result_against_execution,
)


@dataclass(frozen=True, slots=True)
class RunExecution:
    run_id: str
    root: Path
    results: tuple[MatchResult, ...]
    executed_case_ids: tuple[str, ...]
    resumed_case_ids: tuple[str, ...]
    report: RunReport


class EvidencePolicy(StrEnum):
    """How much per-case evidence a run persists."""

    NONE = "none"
    FAILURES = "failures"
    ALL = "all"

    def persists_trajectory(self, *, completed: bool) -> bool:
        if self is EvidencePolicy.ALL:
            return True
        if self is EvidencePolicy.FAILURES:
            return not completed
        return False


@dataclass(frozen=True, slots=True)
class CaseExecution:
    execution: MatchExecution
    evidence: MatchEvidence
    execution_seconds: float
    decision_seconds: float


def validate_worker_count(workers: int) -> None:
    if type(workers) is not int or workers < 1:
        raise SpecError("Workers must be a positive integer.")


@dataclass(frozen=True, slots=True)
class _SummaryWorkerContext:
    assets: ResolvedAssets
    candidate: ResolvedAgent
    opponents: dict[AgentSpec, ResolvedAgent]
    execution_id: str


_summary_worker_context: _SummaryWorkerContext | None = None


def _initialize_summary_worker(manifest: RunManifest, repository_root: Path) -> None:
    global _summary_worker_context
    _ = signal.signal(signal.SIGINT, signal.SIG_IGN)
    suite = manifest.suite
    assets = resolve_assets()
    candidate = resolve_agent(suite.candidate)
    opponents = {item: resolve_agent(item) for item in suite.opponents}
    current = build_run_manifest(
        suite=suite,
        run_id=manifest.run_id,
        matches=schedule_suite(suite),
        candidate=candidate,
        opponents=tuple(opponents.values()),
        assets=assets,
        repository_root=repository_root,
    )
    if current != manifest:
        raise RunConflictError("Worker execution conditions differ from the pinned manifest.")
    _summary_worker_context = _SummaryWorkerContext(
        assets, candidate, opponents, execution_identity(manifest)
    )


def _execute_summary_case(match: ScheduledMatch) -> MatchResult:
    context = _summary_worker_context
    if context is None:
        raise RuntimeError("Summary worker has not been initialized.")
    case = execute_case(
        match,
        candidate=context.candidate,
        opponent=context.opponents[match.opponent_agent],
        assets=context.assets,
        collect_evidence=False,
    )
    return build_result(match, case, evidence=EvidenceRefs(), execution_id=context.execution_id)


@contextmanager
def _parallel_summary_results(
    matches: tuple[ScheduledMatch, ...],
    manifest: RunManifest,
    repository_root: Path,
    *,
    workers: int,
) -> Generator[Iterator[tuple[ScheduledMatch, MatchResult]]]:
    """Keep pool ownership around consumption, including coordinator persistence."""
    pool = ProcessPoolExecutor(
        max_workers=min(workers, len(matches)),
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize_summary_worker,
        initargs=(manifest, repository_root),
    )

    def results() -> Iterator[tuple[ScheduledMatch, MatchResult]]:
        remaining = iter(matches)
        pending = {
            pool.submit(_execute_summary_case, match): match for match in islice(remaining, workers)
        }
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                match = pending.pop(future)
                yield match, future.result()
            for _ in range(len(done)):
                next_match = next(remaining, None)
                if next_match is None:
                    break
                pending[pool.submit(_execute_summary_case, next_match)] = next_match

    stopped = False
    try:
        yield results()
    except BaseException:
        stopped = True
        raise
    finally:
        # Repeated Ctrl-C must not release the caller's writer lock before workers exit.
        on_main_thread = current_thread() is main_thread()
        previous = signal.getsignal(signal.SIGINT)
        if on_main_thread:
            _ = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            try:
                if stopped:
                    advance("dispatch stopped; waiting for running workers to finish")
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        finally:
            if on_main_thread:
                _ = signal.signal(signal.SIGINT, previous)


def execute_run(
    *,
    suite: SuiteSpec,
    run_id: str,
    output_root: Path,
    repository_root: Path,
    evidence_policy: EvidencePolicy = EvidencePolicy.FAILURES,
    expected_manifest: RunManifest | None = None,
    workers: int = 1,
    holdout_authorization: HoldoutAuthorization | None = None,
) -> RunExecution:
    """Execute or resume one run, persisting results and evidence atomically.

    Cases already persisted are verified and reused, so a resumed run never
    re-executes or silently replaces completed work. Held-out suites require a
    `HoldoutAuthorization` issued by the finalization workflow or by the
    explicit manual-consumption escape hatch.
    """

    validate_worker_count(workers)
    if workers > 1 and evidence_policy is not EvidencePolicy.NONE:
        raise SpecError("Parallel execution requires evidence policy 'none'.")
    suite = snapshot_suite(suite)
    require_holdout_authorization(suite, holdout_authorization)
    assets = resolve_assets()
    candidate = resolve_agent(suite.candidate)
    opponents = {opponent: resolve_agent(opponent) for opponent in suite.opponents}
    matches = schedule_suite(suite)
    manifest = build_run_manifest(
        suite=suite,
        run_id=run_id,
        matches=matches,
        candidate=candidate,
        opponents=tuple(opponents.values()),
        assets=assets,
        repository_root=repository_root,
    )
    if expected_manifest is not None and manifest != expected_manifest:
        raise RunConflictError("Execution conditions differ from the pinned manifest.")
    if suite.purpose.requires_clean_checkout and not manifest.repository.is_clean_checkout:
        raise RunConflictError(
            "Optimization, validation and test runs require a clean checkout with a lockfile."
        )
    store = RunStore(output_root=output_root, run_id=run_id)
    prepared = store.prepare(manifest, matches=matches)
    if holdout_authorization is not None:
        record_holdout_consumption(store, authorization=holdout_authorization)
    persisted = prepared.results
    execution_id = prepared.execution_identity
    results = dict(persisted)
    resumed_case_ids = tuple(match.case_id for match in matches if match.case_id in persisted)
    missing = tuple(match for match in matches if match.case_id not in persisted)
    effective_workers = min(workers, len(missing)) if missing else 0
    detail = f"{run_id[:24]} / {suite.suite_id} / {effective_workers} workers"
    advance(detail, completed=len(persisted), total=len(matches))

    def save(match: ScheduledMatch, result: MatchResult) -> None:
        validate_result_against_execution(result, match, prepared)
        store.write_result(result)
        results[match.case_id] = result
        advance(detail, completed=len(results), total=len(matches))

    if workers > 1 and missing:
        with _parallel_summary_results(
            missing, manifest, repository_root, workers=workers
        ) as completed:
            for match, result in completed:
                save(match, result)
    else:
        for match in missing:
            case = execute_case(
                match,
                candidate=candidate,
                opponent=opponents[match.opponent_agent],
                assets=assets,
                collect_evidence=evidence_policy is not EvidencePolicy.NONE,
            )
            include_trajectory = evidence_policy.persists_trajectory(
                completed=case.execution.completed
            )
            evidence_refs = EvidenceRefs()
            if evidence_policy is not EvidencePolicy.NONE:
                evidence_refs = store.write_evidence(
                    match.case_id,
                    case.evidence,
                    include_trajectory=include_trajectory,
                    execution_identity=execution_id,
                )
            result = build_result(match, case, evidence=evidence_refs, execution_id=execution_id)
            save(match, result)

    report = persist_run_report(
        store,
        LoadedRun(
            manifest=manifest,
            matches=matches,
            results=results,
        ),
    )
    return RunExecution(
        run_id=run_id,
        root=store.root,
        results=tuple(results[match.case_id] for match in matches),
        executed_case_ids=tuple(match.case_id for match in missing),
        resumed_case_ids=resumed_case_ids,
        report=report,
    )


def build_run_manifest(
    *,
    suite: SuiteSpec,
    run_id: str,
    matches: tuple[ScheduledMatch, ...],
    candidate: ResolvedAgent,
    opponents: tuple[ResolvedAgent, ...],
    assets: ResolvedAssets,
    repository_root: Path,
) -> RunManifest:
    deck_ids = sorted({deck_id for pair in suite.deck_pairs for deck_id in pair})
    for deck_id in deck_ids:
        _ = assets.require_valid_deck(deck_id)
    return RunManifest(
        schema_version=RECORD_SCHEMA_VERSION,
        run_id=run_id,
        suite=suite,
        seed_derivation_version=SEED_DERIVATION_VERSION,
        case_id_version=CASE_ID_VERSION,
        planned_case_ids=tuple(match.case_id for match in matches),
        candidate=agent_identity(candidate),
        opponents=tuple(agent_identity(opponent) for opponent in opponents),
        assets=AssetIdentities(
            deck_digests=tuple((deck_id, assets.deck_digest(deck_id)) for deck_id in deck_ids),
            card_data_digest=assets.card_data_digest(),
            leader_data_digest=assets.leader_data_digest(),
        ),
        repository=read_repository_provenance(repository_root),
        runtime=read_runtime_provenance(),
    )


def agent_identity(resolved: ResolvedAgent) -> AgentIdentity:
    """The recorded identity of a resolved participant."""
    return AgentIdentity(
        agent_id=resolved.agent_id,
        family=resolved.family_id,
        profile=resolved.profile_id,
        digest=resolved.digest(),
    )


def candidate_manifest(
    manifest: RunManifest, configuration: HeuristicConfiguration, *, run_id: str
) -> RunManifest:
    """Bind complete candidate values while preserving the frozen benchmark conditions."""
    candidate = replace(
        manifest.suite.candidate, profile=None, heuristic_configuration=configuration
    )
    return replace(
        manifest,
        run_id=run_id,
        suite=replace(manifest.suite, candidate=candidate),
        candidate=agent_identity(resolve_agent(candidate)),
    )


def pin_manifest(
    suite: SuiteSpec,
    *,
    run_id: str,
    repository_root: Path,
    assets: ResolvedAssets | None = None,
) -> RunManifest:
    """The manifest a run of `suite` pins against the current checkout and assets."""
    return build_run_manifest(
        suite=suite,
        run_id=run_id,
        matches=schedule_suite(suite),
        candidate=resolve_agent(suite.candidate),
        opponents=tuple(resolve_agent(agent) for agent in suite.opponents),
        assets=assets or resolve_assets(),
        repository_root=repository_root,
    )


def validate_run_environment(manifest: RunManifest, *, repository_root: Path) -> None:
    """Recheck pinned implementation, runtime, participants, and assets at a run boundary."""
    current = pin_manifest(manifest.suite, run_id=manifest.run_id, repository_root=repository_root)
    if current != manifest:
        raise RunConflictError("Execution conditions differ from the pinned manifest.")


def execute_case(
    match: ScheduledMatch,
    *,
    candidate: ResolvedAgent,
    opponent: ResolvedAgent,
    assets: ResolvedAssets,
    collect_evidence: bool = True,
) -> CaseExecution:
    opponent_seat = other_seat(match.candidate_seat)
    bots = {
        match.candidate_seat: candidate.build(
            bot_id=f"{match.case_id}_candidate",
            seed=match.candidate_policy_seed,
        ),
        opponent_seat: opponent.build(
            bot_id=f"{match.case_id}_opponent",
            seed=match.opponent_policy_seed,
        ),
    }
    decks = {
        match.candidate_seat: assets.deck(match.candidate_deck_id),
        opponent_seat: assets.deck(match.opponent_deck_id),
    }
    recorder = ExperimentRecorder() if collect_evidence else SummaryRecorder()
    started = perf_counter()
    execution = execute_match(
        game_id=match.game_id,
        player_one_bot=bots[PLAYER_ONE],
        player_two_bot=bots[PLAYER_TWO],
        player_one_deck=decks[PLAYER_ONE],
        player_two_deck=decks[PLAYER_TWO],
        starting_player=match.requested_starting_player,
        card_registry=assets.card_registry,
        leader_registry=assets.leader_registry,
        rng=SeededRandom(match.environment_seed),
        action_budget=match.action_budget,
        environment_seed=match.environment_seed,
        recorder=recorder,
    )
    execution_seconds = perf_counter() - started
    evidence = recorder.evidence()
    return CaseExecution(
        execution=execution,
        evidence=evidence,
        execution_seconds=execution_seconds,
        decision_seconds=recorder.decision_seconds,
    )


def build_result(
    match: ScheduledMatch,
    case: CaseExecution,
    *,
    evidence: EvidenceRefs,
    execution_id: str,
) -> MatchResult:
    """Reduce an executed case to the authoritative persisted outcome record."""
    execution = case.execution
    final_state = execution.final_state
    winner = execution.match_winner
    return MatchResult(
        schema_version=RECORD_SCHEMA_VERSION,
        execution_identity=execution_id,
        case_id=match.case_id,
        termination=execution.termination,
        candidate_agent_id=match.candidate_agent.agent_id,
        opponent_agent_id=match.opponent_agent.agent_id,
        candidate_seat=match.candidate_seat,
        requested_starting_player=match.requested_starting_player,
        actual_starting_player=(None if final_state is None else final_state.starting_player),
        winner=winner,
        candidate_score=candidate_score_for_outcome(
            winner=winner,
            candidate_seat=match.candidate_seat,
            completed=execution.completed,
        ),
        accepted_transitions=execution.accepted_transitions,
        decision_count=execution.decision_count,
        pending_choice_occurred=execution.pending_choice_occurred,
        observation_contract_version=OBSERVATION_CONTRACT_VERSION,
        final_state_digest=None if final_state is None else state_fingerprint(final_state),
        semantic_digest=semantic_digest(execution, case.evidence),
        decision_seconds=case.decision_seconds,
        execution_seconds=case.execution_seconds,
        environment_seed=match.environment_seed,
        evidence=evidence,
        failure=execution.failure,
    )


def semantic_digest(execution: MatchExecution, evidence: MatchEvidence) -> str:
    return canonical_digest(
        {
            "termination": execution.termination.value,
            "winner": stringify_optional(execution.match_winner),
            "trace": evidence.trace_digest,
            "final_state": (
                None if execution.final_state is None else state_fingerprint(execution.final_state)
            ),
        }
    )
