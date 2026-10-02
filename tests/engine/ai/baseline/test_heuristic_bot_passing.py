from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline.profile_catalog import get_base_profile_definition
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row
from gwent_engine.core.actions import (
    LeaveAction,
    PassAction,
    PlayCardAction,
)
from gwent_engine.core.ids import CardInstanceId

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    choose_bot_response,
    legal_actions_for,
)
from ..support import (
    make_final_round_cow_setup_state,
    make_final_round_horned_gap_state,
    make_opponent_passed_guaranteed_win_state,
    make_opponent_passed_spy_draw_catch_up_state,
    make_round_three_visible_win_state,
    make_unsafe_pass_winning_play_state,
)


def test_heuristic_bot_uses_safe_pass_when_ahead_and_resources_are_preserved() -> None:
    state = (
        scenario("heuristic_safe_pass")
        .player(
            "p1",
            hand=[card("p1_backup_unit", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p1_board_unit", "neutral_geralt")]),
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_vrihedd_brigade_recruit")]),
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PassAction(player_id=PLAYER_ONE_ID)


def test_conservative_bot_does_not_pass_when_one_card_secures_a_safe_lead() -> None:
    state = make_unsafe_pass_winning_play_state()

    selected = choose_bot_response(
        HeuristicBot(
            profile_definition=get_base_profile_definition("conservative"),
        ),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_yennefer_finisher")


def test_conservative_bot_does_not_pass_too_early_in_elimination_round() -> None:
    hidden_cards = [
        card(f"p1_hidden_{index}", "scoiatael_dol_blathanna_archer") for index in range(8)
    ]
    state = (
        scenario("conservative_elimination_round")
        .round(2)
        .current_player("p2")
        .player(
            "p1",
            gems_remaining=1,
            hand=hidden_cards,
            board=rows(
                close=[card("p1_board_geralt", "neutral_geralt")],
                ranged=[card("p1_board_yennefer", "neutral_yennefer")],
                siege=[card("p1_board_archer", "scoiatael_dol_blathanna_archer")],
            ),
        )
        .player(
            "p2",
            gems_remaining=1,
            hand=[
                card("p2_geralt", "neutral_geralt"),
                card("p2_ciri", "neutral_ciri"),
                card("p2_yennefer", "neutral_yennefer"),
                card("p2_scorch", "neutral_scorch"),
            ],
            board=rows(
                close=[card("p2_board_ciri", "neutral_ciri")],
                ranged=[card("p2_board_geralt", "neutral_geralt")],
                siege=[
                    card("p2_board_yennefer", "neutral_yennefer"),
                    card("p2_board_archer", "scoiatael_dol_blathanna_archer"),
                ],
            ),
        )
        .build()
    )
    selected = choose_bot_response(
        HeuristicBot(profile_definition=get_base_profile_definition("conservative")),
        state,
        player_id=PLAYER_TWO_ID,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)


def test_heuristic_bot_contests_final_round_when_effectively_behind_after_pass() -> None:
    state = make_final_round_horned_gap_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_geralt_finisher"),
        target_row=Row.CLOSE,
    )


def test_heuristic_bot_does_not_play_cow_as_dead_final_round_setup() -> None:
    state = make_final_round_cow_setup_state()

    selected = choose_bot_response(
        HeuristicBot(profile_definition=get_base_profile_definition("conservative")),
        state,
        player_id=PLAYER_TWO_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_TWO_ID,
        card_instance_id=CardInstanceId("p2_small_unit"),
        target_row=Row.RANGED,
    )


def test_heuristic_bot_does_not_choose_leave_when_pass_is_available() -> None:
    state = (
        scenario("heuristic_no_leave")
        .round(3)
        .player(
            "p1",
            gems_remaining=1,
            hand=[card("p1_reserve_weather", "neutral_clear_weather")],
        )
        .player(
            "p2",
            gems_remaining=1,
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    legal_actions = legal_actions_for(state, player_id=PLAYER_ONE_ID, card_registry=CARD_REGISTRY)
    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert LeaveAction(player_id=PLAYER_ONE_ID) in legal_actions
    assert selected in legal_actions
    assert selected != LeaveAction(player_id=PLAYER_ONE_ID)


def test_heuristic_bot_prefers_minimum_commitment_finish_after_opponent_passes() -> None:
    state = make_opponent_passed_guaranteed_win_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot().choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_small_finisher"),
        target_row=Row.RANGED,
    )


def test_heuristic_bot_does_not_pass_when_a_spy_line_can_still_draw_into_deck() -> None:
    state = make_opponent_passed_spy_draw_catch_up_state()
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    selected = HeuristicBot(
        profile_definition=get_base_profile_definition("conservative"),
    ).choose_action(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_actions,
        card_registry=CARD_REGISTRY,
    )

    assert isinstance(selected, PlayCardAction)
    assert selected.card_instance_id == CardInstanceId("p1_spy_line")


def test_heuristic_bot_chooses_visible_round_three_winning_line() -> None:
    state = make_round_three_visible_win_state()

    selected = choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )

    assert selected == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_large_unit"),
        target_row=Row.CLOSE,
    )
