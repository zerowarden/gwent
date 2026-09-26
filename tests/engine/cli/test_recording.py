from __future__ import annotations

import pytest
from gwent_engine.ai.arena import (
    MatchStepKind,
)
from gwent_engine.cli.models import CliStep
from gwent_engine.cli.recording import CliMatchRecorder

from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    execute_recorded_match,
)


def _rich_recorder() -> CliMatchRecorder:
    return CliMatchRecorder(
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def test_rich_recorder_builds_cli_steps_with_kinds_and_strengths() -> None:
    recorder = _rich_recorder()

    execution = execute_recorded_match(game_id="cli_recording_test", recorder=recorder)
    steps = recorder.steps

    assert execution.completed
    assert steps[0].kind is MatchStepKind.SETUP
    assert steps[1].kind is MatchStepKind.MULLIGAN
    assert any(step.kind is MatchStepKind.ACTION for step in steps)
    assert steps[-1].kind is MatchStepKind.MATCH_ENDED
    assert all(isinstance(step, CliStep) for step in steps)
    assert any(step.effective_strengths_after for step in steps)


def test_no_recorder_does_not_build_strength_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_strengths(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("Recording must not build strength maps without the CLI recorder.")

    monkeypatch.setattr(
        "gwent_engine.cli.recording.battlefield_effective_strengths",
        reject_strengths,
    )

    execution = execute_recorded_match(game_id="cli_recording_test", recorder=None)

    assert execution.completed
