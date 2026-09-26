"""Shared identities and manifest ↔ schedule ↔ result ↔ evidence contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.arena.models import MatchFailureStage, MatchStepKind, TerminationReason
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.core import GameStatus
from gwent_engine.core.actions import StartGameAction

from gwent_evaluation.models import MatchResult, RunManifest, ScheduledMatch, TrajectoryStep
from gwent_evaluation.provenance import SEED_DERIVATION_VERSION, canonical_digest
from gwent_evaluation.records import CorruptRecordError, record_to_dict
from gwent_evaluation.schedule import CASE_ID_VERSION, schedule_suite


@dataclass(frozen=True)
class LoadedRun:
    """Run records with identities cached for this immutable manifest."""

    manifest: RunManifest
    matches: tuple[ScheduledMatch, ...]
    results: Mapping[str, MatchResult]
    trajectories: Mapping[str, tuple[TrajectoryStep, ...]] = field(
        default_factory=dict[str, tuple[TrajectoryStep, ...]]
    )

    @cached_property
    def benchmark_identity(self) -> str:
        return benchmark_identity(self.manifest)

    @cached_property
    def execution_identity(self) -> str:
        return _execution_identity(self.manifest, self.benchmark_identity)


def benchmark_identity(manifest: RunManifest) -> str:
    """Candidate-independent conditions for paired comparisons."""
    suite = record_to_dict(manifest.suite)
    del suite["candidate"]
    return canonical_digest(
        {
            "suite": suite,
            "opponents": manifest.opponents,
            "assets": manifest.assets,
            "repository": manifest.repository,
            "runtime": manifest.runtime,
            "seed_derivation_version": manifest.seed_derivation_version,
            "case_id_version": manifest.case_id_version,
            "planned_case_ids": manifest.planned_case_ids,
        }
    )


def execution_identity(manifest: RunManifest) -> str:
    return _execution_identity(manifest, benchmark_identity(manifest))


def _execution_identity(manifest: RunManifest, benchmark: str) -> str:
    return canonical_digest(
        {
            "benchmark": benchmark,
            "candidate": manifest.candidate,
            "candidate_spec": manifest.suite.candidate,
        }
    )


def validate_schedule(manifest: RunManifest, matches: tuple[ScheduledMatch, ...]) -> None:
    if (
        manifest.seed_derivation_version != SEED_DERIVATION_VERSION
        or manifest.case_id_version != CASE_ID_VERSION
    ):
        raise CorruptRecordError("Unsupported scheduling versions.")
    if manifest.repository.implementation_digest is None:
        raise CorruptRecordError("Manifest has no implementation identity.")
    expected = schedule_suite(manifest.suite)
    if matches != expected or manifest.planned_case_ids != tuple(m.case_id for m in expected):
        raise CorruptRecordError("The persisted schedule does not match its manifest.")
    if (
        manifest.candidate.agent_id != manifest.suite.candidate.agent_id
        or manifest.candidate.family != manifest.suite.candidate.family.value
    ):
        raise CorruptRecordError("Manifest candidate does not match its suite.")
    if tuple((a.agent_id, a.family) for a in manifest.opponents) != tuple(
        (a.agent_id, a.family.value) for a in manifest.suite.opponents
    ):
        raise CorruptRecordError("Manifest opponents do not match its suite.")


def validate_result_against_execution(
    result: MatchResult,
    scheduled_match: ScheduledMatch,
    run: LoadedRun,
) -> None:
    match = scheduled_match
    manifest = run.manifest
    checks = {
        "execution identity": (result.execution_identity, run.execution_identity),
        "case id": (result.case_id, match.case_id),
        "candidate": (result.candidate_agent_id, manifest.candidate.agent_id),
        "opponent": (result.opponent_agent_id, match.opponent_agent.agent_id),
        "candidate seat": (result.candidate_seat, match.candidate_seat),
        "requested starter": (result.requested_starting_player, match.requested_starting_player),
        "environment seed": (result.environment_seed, match.environment_seed),
        "observation contract": (
            result.observation_contract_version,
            manifest.suite.observation_contract_version,
        ),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise CorruptRecordError(f"Result {match.case_id!r} {label} does not match execution.")
    if result.accepted_transitions > match.action_budget:
        raise CorruptRecordError("Result exceeds its action budget.")
    if (
        result.termination is TerminationReason.ACTION_LIMIT
        and result.accepted_transitions != match.action_budget
    ):
        raise CorruptRecordError("Action limit result has not exhausted its budget.")
    # Model construction also enforces this for direct Python callers.
    try:
        result.__post_init__()
    except ValueError as error:
        raise CorruptRecordError(str(error)) from error


def validate_trajectory(
    steps: tuple[TrajectoryStep, ...],
    result: MatchResult,
    match: ScheduledMatch,
) -> None:
    if not steps:
        if result.failure is None or result.failure.stage is not MatchFailureStage.START:
            raise CorruptRecordError("Trajectory is empty for an executed match.")
        return
    if len(steps) != result.accepted_transitions + 1:
        raise CorruptRecordError("Trajectory transition count does not match result.")
    if steps[0].action_id != action_to_id(StartGameAction(match.requested_starting_player)):
        raise CorruptRecordError("Trajectory must begin with the scheduled start action.")
    if steps[0].kind is not MatchStepKind.SETUP:
        raise CorruptRecordError("Trajectory must begin with a start step.")
    for index, step in enumerate(steps, 1):
        if step.index != index:
            raise CorruptRecordError("Trajectory indices must be contiguous and ordered.")
        if step.state_before.game_id != match.game_id or step.state_after.game_id != match.game_id:
            raise CorruptRecordError("Trajectory belongs to another game.")
        if index > 1 and steps[index - 2].state_after != step.state_before:
            raise CorruptRecordError("Trajectory state links are inconsistent.")
    terminal = steps[-1].state_after
    if state_fingerprint(terminal) != result.final_state_digest:
        raise CorruptRecordError("Trajectory final state does not match result.")
    completed = terminal.status is GameStatus.MATCH_ENDED
    if completed != (result.termination is TerminationReason.COMPLETED):
        raise CorruptRecordError("Trajectory terminal status does not match result.")
    if (
        terminal.match_winner != result.winner
        or terminal.starting_player != result.actual_starting_player
    ):
        raise CorruptRecordError("Trajectory outcome does not match result.")


def validate_loaded_run(loaded: LoadedRun) -> None:
    validate_schedule(loaded.manifest, loaded.matches)
    if set(loaded.results) - set(loaded.manifest.planned_case_ids):
        raise CorruptRecordError("Results contain an unscheduled case.")
    for match in loaded.matches:
        result = loaded.results.get(match.case_id)
        if result is not None:
            validate_result_against_execution(result, match, loaded)
