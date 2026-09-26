from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter

from gwent_engine.ai.arena import MatchExecution, execute_match
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_shared.extract import stringify_optional

from gwent_evaluation.agents import ResolvedAgent, resolve_agent
from gwent_evaluation.assets import ResolvedAssets, resolve_assets
from gwent_evaluation.models import (
    RECORD_SCHEMA_VERSION,
    AgentIdentity,
    AssetIdentities,
    EvidenceRefs,
    MatchEvidence,
    MatchResult,
    RunExecution,
    RunManifest,
    ScheduledMatch,
    SuiteSpec,
)
from gwent_evaluation.provenance import (
    SEED_DERIVATION_VERSION,
    canonical_digest,
    read_repository_provenance,
    read_runtime_provenance,
)
from gwent_evaluation.recording import ExperimentRecorder
from gwent_evaluation.reporting import LoadedRun, persist_run_report
from gwent_evaluation.schedule import CASE_ID_VERSION, other_seat, schedule_suite
from gwent_evaluation.storage import RunStore


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


def execute_run(
    *,
    suite: SuiteSpec,
    run_id: str,
    output_root: Path,
    repository_root: Path,
    evidence_policy: EvidencePolicy = EvidencePolicy.FAILURES,
) -> RunExecution:
    """Execute or resume one run, persisting results and evidence atomically.

    Cases already persisted are verified and reused, so a resumed run never
    re-executes or silently replaces completed work.
    """

    assets = resolve_assets()
    candidate = resolve_agent(suite.candidate)
    opponents = {opponent: resolve_agent(opponent) for opponent in suite.opponents}
    matches = schedule_suite(suite)
    manifest = _build_manifest(
        suite=suite,
        run_id=run_id,
        matches=matches,
        candidate=candidate,
        opponents=tuple(opponents.values()),
        assets=assets,
        repository_root=repository_root,
    )
    store = RunStore(output_root=output_root, run_id=run_id)
    store.prepare(manifest, matches=matches)

    results: list[MatchResult] = []
    executed_case_ids: list[str] = []
    resumed_case_ids: list[str] = []
    for match in matches:
        existing = store.read_result(match.case_id)
        if existing is not None:
            results.append(existing)
            resumed_case_ids.append(match.case_id)
            continue
        case = execute_case(
            match,
            candidate=candidate,
            opponent=opponents[match.opponent_agent],
            assets=assets,
        )
        include_trajectory = evidence_policy.persists_trajectory(completed=case.execution.completed)
        evidence_refs = store.write_evidence(
            match.case_id,
            case.evidence,
            include_trajectory=include_trajectory,
        )
        result = _build_result(match, case, evidence=evidence_refs)
        store.write_result(result)
        results.append(result)
        executed_case_ids.append(match.case_id)

    _ = persist_run_report(
        store,
        LoadedRun(
            manifest=manifest,
            matches=matches,
            results={result.case_id: result for result in results},
        ),
    )
    return RunExecution(
        run_id=run_id,
        root=store.root,
        results=tuple(results),
        executed_case_ids=tuple(executed_case_ids),
        resumed_case_ids=tuple(resumed_case_ids),
    )


def _build_manifest(
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
    return RunManifest(
        schema_version=RECORD_SCHEMA_VERSION,
        run_id=run_id,
        suite=suite,
        seed_derivation_version=SEED_DERIVATION_VERSION,
        case_id_version=CASE_ID_VERSION,
        planned_case_ids=tuple(match.case_id for match in matches),
        candidate=_agent_identity(candidate),
        opponents=tuple(_agent_identity(opponent) for opponent in opponents),
        assets=AssetIdentities(
            deck_digests=tuple((deck_id, assets.deck_digest(deck_id)) for deck_id in deck_ids),
            card_data_digest=assets.card_data_digest(),
            leader_data_digest=assets.leader_data_digest(),
        ),
        repository=read_repository_provenance(repository_root),
        runtime=read_runtime_provenance(),
    )


def _agent_identity(resolved: ResolvedAgent) -> AgentIdentity:
    return AgentIdentity(
        agent_id=resolved.agent_id,
        family=resolved.family_id,
        profile=resolved.profile_id,
        digest=resolved.digest(),
    )


def execute_case(
    match: ScheduledMatch,
    *,
    candidate: ResolvedAgent,
    opponent: ResolvedAgent,
    assets: ResolvedAssets,
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
    recorder = ExperimentRecorder()
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
        decision_seconds=sum(sample.duration_seconds for sample in evidence.samples),
    )


def _build_result(
    match: ScheduledMatch,
    case: CaseExecution,
    *,
    evidence: EvidenceRefs,
) -> MatchResult:
    execution = case.execution
    final_state = execution.final_state
    winner = execution.match_winner
    return MatchResult(
        schema_version=RECORD_SCHEMA_VERSION,
        case_id=match.case_id,
        termination=execution.termination,
        candidate_agent_id=match.candidate_agent.agent_id,
        opponent_agent_id=match.opponent_agent.agent_id,
        candidate_seat=match.candidate_seat,
        requested_starting_player=match.requested_starting_player,
        actual_starting_player=(None if final_state is None else final_state.starting_player),
        winner=winner,
        candidate_score=_candidate_score(
            winner=winner,
            candidate_seat=match.candidate_seat,
            completed=execution.completed,
        ),
        accepted_transitions=execution.accepted_transitions,
        decision_count=execution.decision_count,
        pending_choice_occurred=execution.pending_choice_occurred,
        observation_contract_version=OBSERVATION_CONTRACT_VERSION,
        semantic_digest=semantic_digest(execution, case.evidence),
        decision_seconds=case.decision_seconds,
        execution_seconds=case.execution_seconds,
        environment_seed=match.environment_seed,
        evidence=evidence,
        failure=execution.failure,
    )


def _candidate_score(
    *,
    winner: PlayerId | None,
    candidate_seat: PlayerId,
    completed: bool,
) -> float | None:
    if not completed:
        return None
    if winner is None:
        return 0.5
    return 1.0 if winner == candidate_seat else 0.0


def semantic_digest(execution: MatchExecution, evidence: MatchEvidence) -> str:
    return canonical_digest(
        {
            "termination": execution.termination.value,
            "winner": stringify_optional(execution.match_winner),
            "actions": tuple(sample.chosen_option_id for sample in evidence.samples),
            "states": tuple(state_fingerprint(step.state_after) for step in evidence.trajectory),
            "events": tuple(step.event_fingerprints for step in evidence.trajectory),
        }
    )
