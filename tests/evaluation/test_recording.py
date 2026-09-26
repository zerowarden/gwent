from __future__ import annotations

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.arena import (
    MatchDecisionKind,
    MatchStepKind,
)
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.cli.recording import CliMatchRecorder
from gwent_evaluation import DecisionSample, ExperimentRecorder

from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    execute_recorded_match,
)

_GAME_ID = "experiment_recording_test"


def test_experiment_recorder_captures_samples_and_trajectory() -> None:
    recorder = ExperimentRecorder()

    execution = execute_recorded_match(game_id=_GAME_ID, recorder=recorder)
    evidence = recorder.evidence()

    assert execution.completed
    assert all(isinstance(sample, DecisionSample) for sample in evidence.samples)
    assert {sample.kind for sample in evidence.samples} >= {
        MatchDecisionKind.MULLIGAN,
        MatchDecisionKind.ACTION,
    }
    assert all(sample.legal_option_ids for sample in evidence.samples)
    assert all(sample.chosen_option_id for sample in evidence.samples)
    assert all(sample.duration_seconds >= 0.0 for sample in evidence.samples)
    assert evidence.trajectory[0].kind is MatchStepKind.SETUP
    assert evidence.trajectory[1].kind is MatchStepKind.MULLIGAN
    assert evidence.trajectory[-1].kind is MatchStepKind.MATCH_ENDED
    assert all(step.state_before is not None for step in evidence.trajectory)
    assert all(step.state_after is not None for step in evidence.trajectory)


def test_recording_does_not_change_outcome() -> None:
    summary = execute_recorded_match(game_id=_GAME_ID, recorder=None)
    recorder = ExperimentRecorder()
    recorded = execute_recorded_match(game_id=_GAME_ID, recorder=recorder)
    evidence = recorder.evidence()

    assert summary.termination is recorded.termination
    assert summary.match_winner == recorded.match_winner
    assert summary.accepted_transitions == recorded.accepted_transitions
    assert summary.decision_count == recorded.decision_count
    assert summary.pending_choice_occurred == recorded.pending_choice_occurred
    assert len(evidence.samples) == summary.decision_count
    assert len(evidence.trajectory) == summary.accepted_transitions + 1


def test_experiment_and_rich_recordings_agree_on_semantics() -> None:
    experiment = ExperimentRecorder()
    experiment_execution = execute_recorded_match(game_id=_GAME_ID, recorder=experiment)
    rich = CliMatchRecorder(
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    rich_execution = execute_recorded_match(game_id=_GAME_ID, recorder=rich)
    evidence = experiment.evidence()

    assert experiment_execution.termination is rich_execution.termination
    assert experiment_execution.match_winner == rich_execution.match_winner
    assert tuple(step.action_id for step in evidence.trajectory) == tuple(
        action_to_id(step.action) for step in rich.steps
    )
    assert tuple(state_fingerprint(step.state_after) for step in evidence.trajectory) == tuple(
        state_fingerprint(step.state_after) for step in rich.steps
    )
