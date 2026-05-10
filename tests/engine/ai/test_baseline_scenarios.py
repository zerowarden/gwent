from __future__ import annotations

from typing import cast

from gwent_engine.ai.actions import enumerate_mulligan_selections
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import ChoiceSourceKind, Phase, Row
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
)
from gwent_engine.core.ids import CardInstanceId, ChoiceId
from gwent_engine.core.state import GameState

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    choose_bot_response,
)


def test_safe_pass_scenario() -> None:
    state = (
        scenario("safe_pass_scenario")
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

    assert _choose_action(state) == PassAction(player_id=PLAYER_ONE_ID)


def test_forced_contest_scenario() -> None:
    state = (
        scenario("forced_contest_scenario")
        .round(2)
        .player(
            "p1",
            gems_remaining=1,
            hand=[card("p1_contest_unit", "scoiatael_vrihedd_brigade_recruit")],
        )
        .player(
            "p2",
            gems_remaining=1,
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_contest_unit"),
        target_row=Row.RANGED,
    )


def test_opponent_passed_minimum_commitment_scenario() -> None:
    state = (
        scenario("minimum_commitment_scenario")
        .round(3)
        .player(
            "p1",
            gems_remaining=1,
            hand=[
                card("p1_recruit_finish", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_defender_overkill", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(
            "p2",
            gems_remaining=1,
            round_wins=1,
            passed=True,
            board=rows(close=[card("p2_frontliner", "scoiatael_dwarven_skirmisher")]),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_recruit_finish"),
        target_row=Row.RANGED,
    )


def test_opponent_passed_hopeless_catch_up_scenario() -> None:
    state = (
        scenario("hopeless_catch_up_scenario")
        .player(
            "p1",
            hand=[
                card("p1_small_unit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_medium_unit", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            "p2",
            passed=True,
            board=rows(
                close=[
                    card("p2_big_unit_1", "scoiatael_mahakaman_defender"),
                    card("p2_big_unit_2", "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )

    assert _choose_action(state) == PassAction(player_id=PLAYER_ONE_ID)


def test_round_three_must_win_scenario() -> None:
    state = (
        scenario("round_three_must_win_scenario")
        .round(3)
        .player(
            "p1",
            gems_remaining=1,
            hand=[
                card("p1_small_unit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_large_unit", "neutral_geralt"),
            ],
        )
        .player(
            "p2",
            gems_remaining=1,
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_board_unit", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_large_unit"),
        target_row=Row.CLOSE,
    )


def test_weather_trap_scenario() -> None:
    state = (
        scenario("weather_trap_scenario")
        .round(2)
        .player(
            "p1",
            hand=[
                card("p1_frost", "neutral_biting_frost"),
                card("p1_backup_unit", "scoiatael_vrihedd_brigade_recruit"),
            ],
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(
                close=[
                    card("p2_close_big_1", "scoiatael_mahakaman_defender"),
                    card("p2_close_big_2", "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_frost"),
        target_row=None,
    )


def test_horn_timing_scenario() -> None:
    state = (
        scenario("horn_timing_scenario")
        .round(2)
        .player(
            "p1",
            faction="northern_realms",
            hand=[
                card("p1_horn", "neutral_commanders_horn"),
                card("p1_extra_unit", "northern_realms_redanian_foot_solider"),
            ],
            board=rows(close=[card("p1_close_unit", "northern_realms_blue_stripes_commando")]),
        )
        .player(
            "p2",
            faction="northern_realms",
            hand=[card("p2_hidden_card", "northern_realms_redanian_foot_solider")],
            board=rows(close=[card("p2_close_unit", "northern_realms_blue_stripes_commando")]),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_extra_unit"),
        target_row=Row.CLOSE,
    )


def test_scorch_exposure_scenario() -> None:
    state = (
        scenario("scorch_exposure_scenario")
        .round(2)
        .player(
            "p1",
            hand=[
                card("p1_big_unit", "neutral_geralt"),
                card("p1_safe_unit", "scoiatael_vrihedd_brigade_recruit"),
            ],
            board=rows(close=[card("p1_existing_unit", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card("p2_existing_unit", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    assert _choose_action(state) == PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId("p1_safe_unit"),
        target_row=Row.RANGED,
    )


def test_decoy_tactical_choice_scenario() -> None:
    state = (
        scenario("decoy_choice_scenario")
        .player(
            "p1",
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_spy_target", "neutral_mysterious_elf", owner="p2"),
                    card("p1_plain_target", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="decoy_choice_scenario",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_spy_target", "p1_plain_target"),
        )
        .build()
    )

    assert _choose_pending_choice(state) == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("decoy_choice_scenario"),
        selected_card_instance_ids=(CardInstanceId("p1_spy_target"),),
    )


def test_medic_tactical_choice_scenario() -> None:
    state = (
        scenario("medic_choice_scenario")
        .player(
            "p1",
            deck=[
                card("p1_draw_one", "scoiatael_dol_blathanna_archer"),
                card("p1_draw_two", "scoiatael_mahakaman_defender"),
            ],
            discard=[
                card("p1_spy_discard", "neutral_mysterious_elf"),
                card("p1_plain_discard", "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(close=[card("p1_medic_source", "northern_realms_dun_banner_medic")]),
        )
        .card_choice(
            choice_id="medic_choice_scenario",
            player_id="p1",
            source_kind=ChoiceSourceKind.MEDIC,
            source_card_instance_id="p1_medic_source",
            legal_target_card_instance_ids=("p1_spy_discard", "p1_plain_discard"),
        )
        .build()
    )

    assert _choose_pending_choice(state) == ResolveChoiceAction(
        player_id=PLAYER_ONE_ID,
        choice_id=ChoiceId("medic_choice_scenario"),
        selected_card_instance_ids=(CardInstanceId("p1_spy_discard"),),
    )


def test_mulligan_redundancy_cleanup_scenario() -> None:
    state = (
        scenario("mulligan_redundancy_cleanup_scenario")
        .phase(Phase.MULLIGAN)
        .current_player(None)
        .player(
            "p1",
            faction="northern_realms",
            hand=[
                card("p1_duplicate_1", "northern_realms_redanian_foot_solider"),
                card("p1_duplicate_2", "northern_realms_redanian_foot_solider"),
                card("p1_hero_keep", "neutral_geralt"),
            ],
        )
        .player("p2", faction="northern_realms")
        .build()
    )
    legal_selections = enumerate_mulligan_selections(state, PLAYER_ONE_ID)
    selected = HeuristicBot().choose_mulligan(
        build_player_observation(state, PLAYER_ONE_ID),
        legal_selections,
        card_registry=CARD_REGISTRY,
    )

    assert selected in {
        MulliganSelection(
            player_id=PLAYER_ONE_ID,
            cards_to_replace=(CardInstanceId("p1_duplicate_1"),),
        ),
        MulliganSelection(
            player_id=PLAYER_ONE_ID,
            cards_to_replace=(CardInstanceId("p1_duplicate_2"),),
        ),
        MulliganSelection(
            player_id=PLAYER_ONE_ID,
            cards_to_replace=(
                CardInstanceId("p1_duplicate_1"),
                CardInstanceId("p1_duplicate_2"),
            ),
        ),
    }


def _choose_action(state: GameState) -> GameAction:
    return choose_bot_response(
        HeuristicBot(),
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=CARD_REGISTRY,
    )


def _choose_pending_choice(state: GameState) -> ResolveChoiceAction:
    return cast(
        ResolveChoiceAction,
        choose_bot_response(
            HeuristicBot(),
            state,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
            pending_choice=True,
        ),
    )
