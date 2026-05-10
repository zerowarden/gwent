from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.assessment import build_assessment
from gwent_engine.ai.baseline.context import (
    DecisionContext,
    TacticalMode,
    TempoState,
    classify_context,
)
from gwent_engine.ai.baseline.pass_logic import (
    minimum_commitment_finish,
    should_continue_contesting,
    should_cut_losses_after_pass,
    should_pass_now,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId

from ..scenario_builder import card, rows, scenario
from ..support import CARD_REGISTRY, PLAYER_ONE_ID
from .test_baseline_support import make_assessment, make_final_round_horned_gap_state


def test_should_pass_now_when_opponent_passed_and_viewer_is_ahead() -> None:
    assessment = make_assessment(
        score_gap=4, opponent_passed=True, viewer_board_strength=8, opponent_board_strength=4
    )
    context = classify_context(assessment)

    assert should_pass_now(assessment, context, config=DEFAULT_BASELINE_CONFIG.pass_logic) is True


def test_should_continue_contesting_when_behind_in_elimination_round() -> None:
    assessment = make_assessment(score_gap=-5, is_elimination_round=True)
    context = classify_context(assessment)

    assert (
        should_continue_contesting(
            assessment,
            context,
            config=DEFAULT_BASELINE_CONFIG.pass_logic,
        )
        is True
    )


def test_minimum_commitment_finish_prefers_cheapest_winning_action() -> None:
    state = (
        scenario("minimum_commitment_finish_state")
        .player(
            "p1",
            hand=[
                card("p1_medium_finisher", "scoiatael_mahakaman_defender"),
                card("p1_large_finisher", "neutral_geralt"),
            ],
            board=rows(ranged=[card("p1_existing_board_unit", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            "p2",
            passed=True,
            board=rows(close=[card("p2_existing_board_unit", "scoiatael_mahakaman_defender")]),
        )
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

    action = minimum_commitment_finish(
        legal_actions,
        observation=observation,
        assessment=assessment,
        card_registry=CARD_REGISTRY,
        config=DEFAULT_BASELINE_CONFIG.pass_logic,
    )

    assert action == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_medium_finisher"),
        target_row=Row.CLOSE,
    )


def test_should_not_cut_losses_when_a_spy_can_still_draw_into_the_deck() -> None:
    state = (
        scenario("spy_draw_cut_losses_state")
        .round(3)
        .player(
            "p1",
            gems_remaining=1,
            round_wins=1,
            deck=[
                card("p1_draw_yennefer", "neutral_yennefer"),
                card("p1_draw_geralt", "neutral_geralt"),
            ],
            hand=[card("p1_spy_line", "neutral_mysterious_elf")],
        )
        .player(
            "p2",
            gems_remaining=1,
            round_wins=1,
            passed=True,
            board=rows(close=[card("p2_frontliner", "scoiatael_mahakaman_defender")]),
        )
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

    assert (
        should_cut_losses_after_pass(
            legal_actions,
            observation=observation,
            assessment=assessment,
            card_registry=CARD_REGISTRY,
            config=DEFAULT_BASELINE_CONFIG.pass_logic,
        )
        is False
    )


def test_should_not_safe_pass_when_effectively_behind_in_final_round() -> None:
    state = make_final_round_horned_gap_state()
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
    context = classify_context(assessment)

    assert should_pass_now(assessment, context, config=DEFAULT_BASELINE_CONFIG.pass_logic) is False


def test_should_not_use_generic_safe_pass_rule_in_all_in_state() -> None:
    assessment = make_assessment(
        score_gap=4,
        opponent_passed=False,
        is_elimination_round=True,
        viewer_board_strength=8,
        opponent_board_strength=4,
    )
    context = DecisionContext(
        tempo=TempoState.AHEAD,
        mode=TacticalMode.ALL_IN,
        preserve_resources=True,
    )

    assert should_pass_now(assessment, context, config=DEFAULT_BASELINE_CONFIG.pass_logic) is False
