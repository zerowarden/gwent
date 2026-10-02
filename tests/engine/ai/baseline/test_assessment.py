import pytest
from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.context import (
    PressureMode,
    TacticalMode,
    TempoState,
    classify_context,
)
from gwent_engine.ai.baseline.features import dead_card_penalty
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row
from gwent_engine.core.ids import CardDefinitionId

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import ScenarioCard, card, rows, scenario
from ...support import CARD_REGISTRY
from ..support import make_assessment


def test_build_assessment_computes_reusable_player_and_board_signals() -> None:
    state = (
        scenario("assessment_reusable_signals")
        .player(
            "p1",
            hand=[
                card("p1_hand_unit", "scoiatael_mahakaman_defender"),
                card("p1_hand_weather", "neutral_biting_frost"),
            ],
            board=rows(ranged=[card("p1_board_unit", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            "p2",
            board=rows(ranged=[card("p2_board_unit", "nilfgaard_black_infantry_archer")]),
        )
        .weather(rows(close=[card("active_close_weather", "neutral_biting_frost")]))
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assessment = build_assessment(
        observation,
        CARD_REGISTRY,
        legal_actions=legal_actions,
    )

    assert assessment.viewer.hand_count == 2
    assert assessment.viewer.hand_value == 5
    assert assessment.viewer.unit_hand_count == 1
    assert assessment.viewer.board_strength == 4
    assert assessment.viewer.ranged.non_hero_unit_count == 1
    assert assessment.viewer.ranged.non_hero_unit_base_strength == 4
    assert assessment.opponent.board_strength == 10
    assert assessment.score_gap == -6
    assert assessment.card_advantage == 2
    assert assessment.active_weather_rows == (Row.CLOSE,)
    assert assessment.legal_action_count == len(legal_actions)
    assert assessment.legal_pass_available is True
    assert assessment.legal_play_count >= 1


def test_build_assessment_uses_effective_board_strength_for_score_gap() -> None:
    state = (
        scenario("assessment_effective_board_strength")
        .player(
            "p1",
            board=rows(
                close=[
                    card("p1_close_unit", "scoiatael_mahakaman_defender"),
                    card("p1_close_horn", "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            "p2",
            board=rows(close=[card("p2_close_unit", "nilfgaard_black_infantry_archer")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)

    assessment = build_assessment(
        observation,
        CARD_REGISTRY,
        legal_actions=(),
    )

    assert assessment.viewer.close.base_strength == 5
    assert assessment.viewer.board_strength == 10
    assert assessment.opponent.board_strength == 10
    assert assessment.score_gap == 0


def test_dead_card_penalty_counts_redundant_weather_and_clear_weather() -> None:
    definitions = (
        CARD_REGISTRY.get(CardDefinitionId("neutral_clear_weather")),
        CARD_REGISTRY.get(CardDefinitionId("neutral_biting_frost")),
    )

    assert dead_card_penalty(definitions) == 1
    assert dead_card_penalty(definitions, active_weather_rows=(Row.CLOSE,)) == 1


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


@pytest.mark.parametrize("card_advantage", [-2, 0, 2])
@pytest.mark.parametrize(
    "round_number, viewer_gems, opponent_gems, preserve_resources, mode",
    [
        (1, 2, 2, True, TacticalMode.PROBE),
        (2, 1, 2, False, TacticalMode.ALL_IN),
        (2, 2, 1, False, TacticalMode.ALL_IN),
        (3, 1, 1, False, TacticalMode.ALL_IN),
    ],
)
def test_only_round_one_preserves_resources_whatever_the_card_advantage(
    card_advantage: int,
    round_number: int,
    viewer_gems: int,
    opponent_gems: int,
    preserve_resources: bool,
    mode: TacticalMode,
) -> None:
    def hand(prefix: str, size: int) -> list[ScenarioCard]:
        return [
            card(f"{prefix}_hand_{index}", "scoiatael_mahakaman_defender") for index in range(size)
        ]

    state = (
        scenario("preserve_resources_by_round")
        .round(round_number)
        .player("p1", gems_remaining=viewer_gems, hand=hand("p1", 3 + max(card_advantage, 0)))
        .player("p2", gems_remaining=opponent_gems, hand=hand("p2", 3 + max(-card_advantage, 0)))
        .build()
    )
    assessment = build_assessment(build_player_observation(state, PLAYER_ONE_ID), CARD_REGISTRY)

    context = classify_context(assessment)

    assert assessment.card_advantage == card_advantage
    assert context.preserve_resources is preserve_resources
    assert context.mode == mode
