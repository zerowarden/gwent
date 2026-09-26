"""Reproduction and scripted replay of persisted experiment records.

Reproduction re-executes the declared agents and assets for one scheduled case
and compares the outcome against the persisted record. Scripted replay instead
drives the reducer from the recorded action stream and environment seed, never
calling policy code, so it can separate engine drift from policy drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gwent_engine.ai.arena import TerminationReason, build_initial_state
from gwent_engine.ai.arena.models import MatchFailure
from gwent_engine.ai.hashing import event_fingerprint, state_fingerprint
from gwent_engine.core.errors import GwentEngineError, SerializationError
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action_with_intermediate_state
from gwent_engine.core.state import GameState
from gwent_engine.serialize import action_from_id

from gwent_evaluation.agents import resolve_agent
from gwent_evaluation.assets import ResolvedAssets, resolve_assets
from gwent_evaluation.execution import CaseExecution, execute_case, semantic_digest
from gwent_evaluation.models import MatchResult, ScheduledMatch, TrajectoryStep
from gwent_evaluation.schedule import other_seat
from gwent_evaluation.storage import RunStore
from gwent_evaluation.validation import LoadedRun


class ReplayError(ValueError):
    """Raised when a recorded case cannot be reconstructed or replayed."""


@dataclass(frozen=True, slots=True)
class Divergence:
    """First recorded difference between a re-run and its persisted record.

    Result-level divergences carry index `0`; step-level divergences carry the
    1-based trajectory index of the first differing step.
    """

    index: int
    field: str
    expected: object
    actual: object


@dataclass(frozen=True, slots=True)
class ReproductionOutcome:
    case_id: str
    termination: TerminationReason
    reproduced: bool
    divergences: tuple[Divergence, ...]


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    case_id: str
    termination: TerminationReason
    reproduced: bool
    prefix_verified: bool
    replayed_steps: int
    total_steps: int
    divergences: tuple[Divergence, ...]

    @property
    def prefix_only(self) -> bool:
        """Whether only a failed case's valid prefix could be replayed."""

        return self.termination is not TerminationReason.COMPLETED


def reproduce_case(run_root: Path, case_id: str) -> ReproductionOutcome:
    """Re-execute one recorded case with its declared agents, assets, and seeds."""

    store = _store(run_root)
    assets = resolve_assets()
    loaded = store.load(trajectory_cases=(case_id,), card_registry=assets.card_registry)
    match, result = _require_case(loaded, case_id)
    case = execute_case(
        match,
        candidate=resolve_agent(match.candidate_agent),
        opponent=resolve_agent(match.opponent_agent),
        assets=assets,
    )
    divergences = _compare_execution(result, case)
    recorded_steps = loaded.trajectories.get(case_id)
    if divergences and recorded_steps is not None:
        step_divergences = _compare_steps(recorded_steps, case.evidence.trajectory)
        if step_divergences:
            divergences = step_divergences
    return ReproductionOutcome(
        case_id=case_id,
        termination=result.termination,
        reproduced=not divergences,
        divergences=divergences,
    )


def replay_case(run_root: Path, case_id: str) -> ReplayOutcome:
    """Drive the reducer from recorded actions, without calling policy code."""

    store = _store(run_root)
    assets = resolve_assets()
    loaded = store.load(trajectory_cases=(case_id,), card_registry=assets.card_registry)
    match, result = _require_case(loaded, case_id)
    steps = loaded.trajectories.get(case_id)
    if steps is None:
        raise ReplayError(f"Case {case_id!r} has no persisted trajectory evidence to replay.")
    divergences = _drive(match, steps, assets=assets)
    return ReplayOutcome(
        case_id=case_id,
        termination=result.termination,
        reproduced=not divergences and result.termination is TerminationReason.COMPLETED,
        prefix_verified=not divergences,
        replayed_steps=_replayed_steps(divergences, total=len(steps)),
        total_steps=len(steps),
        divergences=divergences,
    )


def _drive(
    match: ScheduledMatch,
    steps: tuple[TrajectoryStep, ...],
    *,
    assets: ResolvedAssets,
) -> tuple[Divergence, ...]:
    decks = {
        match.candidate_seat: assets.deck(match.candidate_deck_id),
        other_seat(match.candidate_seat): assets.deck(match.opponent_deck_id),
    }
    state = build_initial_state(
        game_id=match.game_id,
        player_one_deck=decks[PLAYER_ONE],
        player_two_deck=decks[PLAYER_TWO],
        environment_seed=match.environment_seed,
    )
    rng = SeededRandom(match.environment_seed)
    for step in steps:
        if state != step.state_before:
            return (
                Divergence(
                    step.index,
                    "state_before",
                    state_fingerprint(step.state_before),
                    state_fingerprint(state),
                ),
            )
        try:
            action = action_from_id(step.action_id)
        except SerializationError as error:
            return (Divergence(step.index, "action_id", step.action_id, str(error)),)
        try:
            state, events, _ = apply_action_with_intermediate_state(
                state,
                action,
                rng=rng,
                card_registry=assets.card_registry,
                leader_registry=assets.leader_registry,
            )
        except GwentEngineError as error:
            return (
                Divergence(
                    step.index,
                    "reduce",
                    step.action_id,
                    f"{type(error).__name__}: {error}",
                ),
            )
        divergence = _step_state_divergence(
            step.index,
            expected_state=step.state_after,
            expected_events=step.event_fingerprints,
            actual_state=state,
            actual_events=tuple(event_fingerprint(event) for event in events),
        )
        if divergence is not None:
            return (divergence,)
    return ()


def _compare_execution(result: MatchResult, case: CaseExecution) -> tuple[Divergence, ...]:
    execution = case.execution
    checks: tuple[tuple[str, object, object], ...] = (
        ("termination", result.termination, execution.termination),
        ("winner", result.winner, execution.match_winner),
        ("accepted_transitions", result.accepted_transitions, execution.accepted_transitions),
        ("decision_count", result.decision_count, execution.decision_count),
        (
            "pending_choice_occurred",
            result.pending_choice_occurred,
            execution.pending_choice_occurred,
        ),
        ("failure", _failure_identity(result.failure), _failure_identity(execution.failure)),
        ("semantic_digest", result.semantic_digest, semantic_digest(execution, case.evidence)),
    )
    return tuple(
        Divergence(index=0, field=field, expected=expected, actual=actual)
        for field, expected, actual in checks
        if expected != actual
    )


def _compare_steps(
    recorded: tuple[TrajectoryStep, ...],
    observed: tuple[TrajectoryStep, ...],
) -> tuple[Divergence, ...]:
    for expected, actual in zip(recorded, observed, strict=False):
        if expected.action_id != actual.action_id:
            return (Divergence(expected.index, "action_id", expected.action_id, actual.action_id),)
        divergence = _step_state_divergence(
            expected.index,
            expected_state=expected.state_after,
            expected_events=expected.event_fingerprints,
            actual_state=actual.state_after,
            actual_events=actual.event_fingerprints,
        )
        if divergence is not None:
            return (divergence,)
    if len(recorded) != len(observed):
        return (
            Divergence(
                min(len(recorded), len(observed)) + 1,
                "step_count",
                len(recorded),
                len(observed),
            ),
        )
    return ()


def _step_state_divergence(
    index: int,
    *,
    expected_state: GameState,
    expected_events: tuple[str, ...],
    actual_state: GameState,
    actual_events: tuple[str, ...],
) -> Divergence | None:
    if actual_state != expected_state:
        return Divergence(
            index,
            "state_after",
            state_fingerprint(expected_state),
            state_fingerprint(actual_state),
        )
    if actual_events != expected_events:
        return Divergence(index, "event_fingerprints", expected_events, actual_events)
    return None


def _failure_identity(failure: MatchFailure | None) -> tuple[str, str, str | None] | None:
    if failure is None:
        return None
    return (
        failure.stage.value,
        failure.exception_type,
        None if failure.actor is None else str(failure.actor),
    )


def _replayed_steps(divergences: tuple[Divergence, ...], *, total: int) -> int:
    if not divergences:
        return total
    return max(divergences[0].index - 1, 0)


def _store(run_root: Path) -> RunStore:
    return RunStore.from_root(run_root)


def _require_case(loaded: LoadedRun, case_id: str) -> tuple[ScheduledMatch, MatchResult]:
    match = next((match for match in loaded.matches if match.case_id == case_id), None)
    if match is None:
        raise ReplayError(f"Case {case_id!r} is not part of run {loaded.manifest.run_id!r}.")
    result = loaded.results.get(case_id)
    if result is None:
        raise ReplayError(
            f"Case {case_id!r} has no persisted result in run {loaded.manifest.run_id!r}."
        )
    return match, result
