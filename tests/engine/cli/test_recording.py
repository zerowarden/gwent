from __future__ import annotations

import pytest
from gwent_engine.ai.arena import (
    MatchExecution,
    MatchRecorder,
    MatchStepKind,
    create_bot,
    execute_match,
)
from gwent_engine.cards import DeckDefinition
from gwent_engine.cli.models import CliStep
from gwent_engine.cli.recording import CliMatchRecorder
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.decks import load_sample_decks

from tests.engine.support import CARD_REGISTRY, DATA_DIR, LEADER_REGISTRY

_DECK_IDS = ("monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict")


def _decks() -> dict[str, DeckDefinition]:
    decks = load_sample_decks(DATA_DIR / "sample_decks.yaml", CARD_REGISTRY, LEADER_REGISTRY)
    return {str(deck.deck_id): deck for deck in decks}


def _execute(*, recorder: MatchRecorder | None, seed: int = 7) -> MatchExecution:
    decks = _decks()
    return execute_match(
        game_id=GameId("cli_recording_test"),
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


def _rich_recorder() -> CliMatchRecorder:
    return CliMatchRecorder(
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def test_rich_recorder_builds_cli_steps_with_kinds_and_strengths() -> None:
    recorder = _rich_recorder()

    execution = _execute(recorder=recorder)
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

    execution = _execute(recorder=None)

    assert execution.completed
