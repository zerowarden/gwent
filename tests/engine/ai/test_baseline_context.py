from gwent_engine.ai.baseline.context import (
    PressureMode,
    TacticalMode,
    TempoState,
    classify_context,
)

from .test_baseline_support import make_assessment


def test_classify_context_detects_opening_even_state() -> None:
    context = classify_context(make_assessment())

    assert context.tempo == TempoState.EVEN
    assert context.mode == TacticalMode.PROBE
    assert context.pressure == PressureMode.OPENING
    assert context.prioritize_card_advantage is True
    assert context.prioritize_immediate_points is False


def test_classify_context_detects_opponent_passed_finish_mode() -> None:
    context = classify_context(
        make_assessment(
            score_gap=3, opponent_passed=True, viewer_board_strength=6, opponent_board_strength=3
        )
    )

    assert context.tempo == TempoState.AHEAD
    assert context.mode == TacticalMode.FINISH_AFTER_PASS
    assert context.pressure == PressureMode.OPPONENT_PASSED
    assert context.minimum_commitment_mode is True
    assert context.prioritize_immediate_points is True


def test_classify_context_detects_elimination_pressure() -> None:
    context = classify_context(make_assessment(is_elimination_round=True, score_gap=-4))

    assert context.tempo == TempoState.BEHIND
    assert context.mode == TacticalMode.ALL_IN
    assert context.pressure == PressureMode.ELIMINATION
    assert context.preserve_resources is False
