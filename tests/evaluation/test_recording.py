from __future__ import annotations

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.arena import (
    MatchDecisionKind,
    MatchExecution,
    MatchRecorder,
    MatchStepKind,
    create_bot,
    execute_match,
)
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.cards import DeckDefinition
from gwent_engine.cli.recording import CliMatchRecorder
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.decks import load_sample_decks
from gwent_evaluation import DecisionSample, ExperimentRecorder

from tests.engine.support import CARD_REGISTRY, DATA_DIR, LEADER_REGISTRY

_DECK_IDS = ("monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict")


def _decks() -> dict[str, DeckDefinition]:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    return {str(deck.deck_id): deck for deck in decks}


def _execute(*, recorder: MatchRecorder | None, seed: int = 7) -> MatchExecution:
    decks = _decks()
    return execute_match(
        game_id=GameId("experiment_recording_test"),
        player_one_bot=create_bot("heuristic", bot_id="p1_bot"),
        player_two_bot=create_bot("greedy", bot_id="p2_bot"),
        player_one_deck=decks[_DECK_IDS[0]],
        player_two_deck=decks[_DECK_IDS[1]],
        starting_player=PlayerId("p1"),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
        rng=SeededRandom(seed),
        action_budget=512,
        environment_seed=seed,
        recorder=recorder,
    )


def test_experiment_recorder_captures_samples_and_trajectory() -> None:
    recorder = ExperimentRecorder()

    execution = _execute(recorder=recorder)
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
    summary = _execute(recorder=None)
    recorder = ExperimentRecorder()
    recorded = _execute(recorder=recorder)
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
    experiment_execution = _execute(recorder=experiment)
    rich = CliMatchRecorder(
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    rich_execution = _execute(recorder=rich)
    evidence = experiment.evidence()

    assert experiment_execution.termination is rich_execution.termination
    assert experiment_execution.match_winner == rich_execution.match_winner
    assert tuple(step.action_id for step in evidence.trajectory) == tuple(
        action_to_id(step.action) for step in rich.steps
    )
    assert tuple(state_fingerprint(step.state_after) for step in evidence.trajectory) == tuple(
        state_fingerprint(step.state_after) for step in rich.steps
    )
