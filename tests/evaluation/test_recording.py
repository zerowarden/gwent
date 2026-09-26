from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

import pytest
from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.agents import GreedyBot
from gwent_engine.ai.arena import (
    MatchDecisionKind,
    MatchStepKind,
    TerminationReason,
)
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.hashing import state_fingerprint
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.cards import CardRegistry
from gwent_engine.cli.recording import CliMatchRecorder
from gwent_engine.core.actions import GameAction, MulliganSelection, PassAction, PlayCardAction
from gwent_engine.core.enums import Row
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.leaders import LeaderRegistry
from gwent_evaluation.execution import semantic_digest
from gwent_evaluation.models import DecisionSample
from gwent_evaluation.recording import ExperimentRecorder, SummaryRecorder

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


def test_second_mulligan_failure_retains_both_decision_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gwent_engine.ai.agents import GreedyBot
    from gwent_engine.ai.arena import TerminationReason

    from tests.engine.support import PLAYER_TWO_ID

    original = GreedyBot.choose_mulligan

    def choose(
        self: GreedyBot,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        if observation.viewer_player_id == PLAYER_TWO_ID:
            raise RuntimeError("second mulligan failed")
        return original(
            self,
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    monkeypatch.setattr(GreedyBot, "choose_mulligan", choose)
    recorder = ExperimentRecorder()
    execution = execute_recorded_match(game_id="failed_mulligan", recorder=recorder)
    assert execution.termination is TerminationReason.AGENT_ERROR
    assert execution.decision_count == 2
    assert len(recorder.samples) == 2
    assert recorder.samples[0].failure is None
    assert recorder.samples[0].chosen_option_id is not None
    assert recorder.samples[1].failure is not None
    assert recorder.samples[1].observation.viewer_player_id == PLAYER_TWO_ID
    assert recorder.samples[1].chosen_option_id is None
    assert len(recorder.trajectory) == 1


def test_illegal_returned_action_is_recorded_before_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gwent_engine.ai.arena import TerminationReason
    from gwent_engine.ai.baseline import HeuristicBot
    from gwent_engine.core.actions import PassAction

    from tests.engine.support import PLAYER_TWO_ID

    def choose(
        self: HeuristicBot,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> GameAction:
        del self, observation, legal_actions, card_registry, leader_registry
        return PassAction(player_id=PLAYER_TWO_ID)

    monkeypatch.setattr(HeuristicBot, "choose_action", choose)
    recorder = ExperimentRecorder()
    execution = execute_recorded_match(game_id="invalid_attempt", recorder=recorder)
    assert execution.termination is TerminationReason.ILLEGAL_ACTION
    attempt = recorder.samples[-1]
    assert attempt.failure is not None
    assert attempt.chosen_option_id == action_to_id(PassAction(player_id=PLAYER_TWO_ID))
    assert attempt.chosen_option_id not in attempt.legal_option_ids
    assert len(recorder.trajectory) == execution.accepted_transitions + 1


@pytest.mark.parametrize(
    "method,returned_value",
    [
        ("choose_action", object),
        ("choose_action", lambda: PassAction(player_id=cast(PlayerId, object()))),
        (
            "choose_action",
            lambda: PlayCardAction(
                player_id=PlayerId("p1"),
                card_instance_id=CardInstanceId("missing"),
                target_row=cast(Row, object()),
            ),
        ),
        ("choose_mulligan", object),
        ("choose_mulligan", lambda: MulliganSelection(player_id=cast(PlayerId, object()))),
        (
            "choose_mulligan",
            lambda: MulliganSelection(
                player_id=PlayerId("p1"), cards_to_replace=(cast(CardInstanceId, object()),)
            ),
        ),
    ],
)
def test_malformed_returns_have_stable_semantics_and_separate_diagnostics(
    monkeypatch: pytest.MonkeyPatch, method: str, returned_value: Callable[[], object]
) -> None:
    # Retain both values so their address-bearing representations cannot reuse an address.
    values: list[object] = []

    def choose(*_args: object, **_kwargs: object) -> object:
        value = returned_value()
        values.append(value)
        return value

    monkeypatch.setattr(HeuristicBot, method, choose)
    summary = SummaryRecorder()
    detailed = ExperimentRecorder()
    first = execute_recorded_match(game_id="malformed_return", recorder=summary)
    second = execute_recorded_match(game_id="malformed_return", recorder=detailed)

    assert first.termination is second.termination is TerminationReason.ILLEGAL_ACTION
    assert first.failure is not None and second.failure is not None
    assert repr(values[0]) in first.failure.message
    assert repr(values[1]) in second.failure.message
    assert first.failure.message != second.failure.message
    assert summary.trace_digest == detailed.trace_digest
    assert semantic_digest(first, summary.evidence()) == semantic_digest(
        second, detailed.evidence()
    )
    value_type = type(values[0])
    assert detailed.samples[-1].chosen_option_id == (
        f"malformed_return:{value_type.__module__}.{value_type.__qualname__}"
    )
