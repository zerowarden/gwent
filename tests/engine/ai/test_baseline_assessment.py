from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row

from ..scenario_builder import card, rows, scenario
from ..support import CARD_REGISTRY, PLAYER_ONE_ID


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
