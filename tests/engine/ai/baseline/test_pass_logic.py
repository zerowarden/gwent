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
    should_cut_losses_after_pass,
    should_pass_now,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG
from gwent_engine.core import Row
from gwent_engine.core.actions import GameAction, PlayCardAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import card, rows, scenario
from ...support import CARD_REGISTRY, LEADER_REGISTRY, NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID
from ..support import make_assessment, make_final_round_horned_gap_state


def test_should_pass_now_when_opponent_passed_and_viewer_is_ahead() -> None:
    assessment = make_assessment(
        score_gap=4, opponent_passed=True, viewer_board_strength=8, opponent_board_strength=4
    )
    context = classify_context(assessment)

    assert should_pass_now(assessment, context, config=DEFAULT_BASELINE_CONFIG.pass_logic) is True


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


def _minimum_commitment_finish(state: GameState) -> GameAction | None:
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    return minimum_commitment_finish(
        legal_actions,
        observation=observation,
        assessment=build_assessment(observation, CARD_REGISTRY, legal_actions=legal_actions),
        card_registry=CARD_REGISTRY,
        config=DEFAULT_BASELINE_CONFIG.pass_logic,
        leader_registry=LEADER_REGISTRY,
    )


def test_minimum_commitment_finish_skips_a_unit_that_weather_stops_from_finishing() -> None:
    state = (
        scenario("minimum_commitment_finish_under_frost")
        .player(
            "p1",
            hand=[
                card("p1_frosted_close_unit", "scoiatael_dennis_cranmer"),
                card("p1_ranged_unit", "nilfgaard_black_infantry_archer"),
            ],
        )
        .player(
            "p2",
            passed=True,
            board=rows(ranged=[card("p2_ranged_unit", "northern_realms_keira_metz")]),
        )
        .weather(rows(close=[card("weather_frost", "neutral_biting_frost")]))
        .build()
    )

    assert _minimum_commitment_finish(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_ranged_unit"),
        target_row=Row.RANGED,
    )


def test_minimum_commitment_finish_never_chooses_a_leader_without_effect() -> None:
    state = (
        scenario("minimum_commitment_finish_noop_leader")
        .round(3)
        .player(
            "p1",
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
            gems_remaining=1,
            round_wins=1,
            hand=[card("p1_small_spy", "northern_realms_thaler")],
            board=rows(siege=[card("p1_siege_tower", "northern_realms_siege_tower")]),
        )
        .player(
            "p2",
            faction="nilfgaard",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            passed=True,
            board=rows(
                close=[card("p2_close_unit", "scoiatael_mahakaman_defender")],
                siege=[
                    card("p2_siege_engineer", "nilfgaard_siege_engineer"),
                    card("p2_siege_technician", "nilfgaard_siege_technician"),
                ],
            ),
        )
        .build()
    )

    assert _minimum_commitment_finish(state) is None


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
