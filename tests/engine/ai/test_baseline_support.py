from gwent_engine.ai.baseline.assessment import DecisionAssessment, PlayerAssessment, RowSummary
from gwent_engine.core import ChoiceSourceKind, GameStatus, Phase, Row
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState

from ..scenario_builder import ScenarioCard, ScenarioRows, card, rows, scenario
from ..support import (
    NILFGAARD_WHITE_FLAME_LEADER_ID,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
    SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
    SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
)

ScenarioCards = tuple[ScenarioCard, ...] | list[ScenarioCard]


def make_player_assessment(
    *,
    player_id: str,
    hand_count: int = 3,
    hand_value: int = 12,
    board_strength: int = 0,
    gems_remaining: int = 2,
    round_wins: int = 0,
    passed: bool = False,
    leader_used: bool = False,
    close: RowSummary | None = None,
    ranged: RowSummary | None = None,
    siege: RowSummary | None = None,
) -> PlayerAssessment:
    empty_rows = (
        RowSummary(Row.CLOSE, 0, 0, 0, 0),
        RowSummary(Row.RANGED, 0, 0, 0, 0),
        RowSummary(Row.SIEGE, 0, 0, 0, 0),
    )
    return PlayerAssessment(
        player_id=PlayerId(player_id),
        hand_count=hand_count,
        hand_value=hand_value,
        unit_hand_count=hand_count,
        hand_definitions=(),
        discard_definitions=(),
        board_strength=board_strength,
        close=close or empty_rows[0],
        ranged=ranged or empty_rows[1],
        siege=siege or empty_rows[2],
        gems_remaining=gems_remaining,
        round_wins=round_wins,
        passed=passed,
        leader_used=leader_used,
    )


def make_assessment(
    *,
    viewer: PlayerAssessment | None = None,
    opponent: PlayerAssessment | None = None,
    score_gap: int = 0,
    card_advantage: int = 0,
    opponent_passed: bool = False,
    is_elimination_round: bool = False,
    viewer_board_strength: int = 0,
    opponent_board_strength: int = 0,
) -> DecisionAssessment:
    viewer_assessment = viewer or make_player_assessment(
        player_id="p1",
        board_strength=viewer_board_strength,
    )
    opponent_assessment = opponent or make_player_assessment(
        player_id="p2",
        board_strength=opponent_board_strength,
        passed=opponent_passed,
    )
    return DecisionAssessment(
        viewer_player_id=PlayerId("p1"),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        round_number=1,
        viewer=viewer_assessment,
        opponent=opponent_assessment,
        active_weather_rows=(),
        score_gap=score_gap,
        card_advantage=card_advantage,
        legal_action_count=3,
        legal_pass_available=True,
        legal_play_count=2,
        pending_choice_source_kind=None,
        opponent_passed=opponent_passed,
        is_final_round=False,
        is_elimination_round=is_elimination_round,
    )


def make_opponent_passed_guaranteed_win_state() -> GameState:
    return (
        scenario("opponent_passed_guaranteed_win_state")
        .round(3)
        .player(
            "p1",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[
                card("p1_small_finisher", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_large_finisher", "neutral_geralt"),
            ],
        )
        .player(
            "p2",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            passed=True,
            board=rows(close=[card("p2_frontliner", "scoiatael_dwarven_skirmisher")]),
        )
        .build()
    )


def _player_one_tactical_state(
    *,
    name: str,
    hand: ScenarioCards | None = None,
    discard: ScenarioCards | None = None,
    board: ScenarioRows | None = None,
    opponent_board: ScenarioRows | None = None,
    choice_id: str | None = None,
    source_kind: ChoiceSourceKind | None = None,
    source_card_instance_id: str | None = None,
    legal_target_card_instance_ids: tuple[str, ...] | list[str] = (),
) -> GameState:
    builder = scenario(name).player("p1", hand=hand, discard=discard, board=board)
    if opponent_board is not None:
        builder = builder.player("p2", board=opponent_board)
    if choice_id is not None:
        if source_kind is None or source_card_instance_id is None:
            raise ValueError("choice states require source_kind and source_card_instance_id")
        builder = builder.card_choice(
            choice_id=choice_id,
            player_id="p1",
            source_kind=source_kind,
            source_card_instance_id=source_card_instance_id,
            legal_target_card_instance_ids=legal_target_card_instance_ids,
        )
    return builder.build()


def make_mardroeme_transform_choice_state() -> GameState:
    return _player_one_tactical_state(
        name="mardroeme_transform_choice_state",
        hand=[
            card("p1_mardroeme", "skellige_mardroeme"),
            card("p1_archer", "scoiatael_dol_blathanna_archer"),
        ],
        board=rows(close=[card("p1_berserker", "skellige_berserker")]),
        opponent_board=rows(
            ranged=[
                card("p2_archer", "skellige_clan_brokvar_archer"),
                card("p2_recruit", "scoiatael_vrihedd_brigade_recruit"),
            ]
        ),
    )


def make_clear_weather_leader_state() -> GameState:
    return (
        scenario("clear_weather_leader_state")
        .player(
            "p1",
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            board=rows(
                ranged=[
                    card("p1_archer_a", "scoiatael_dol_blathanna_archer"),
                    card("p1_archer_b", "scoiatael_dol_blathanna_archer"),
                    card("p1_archer_c", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .player("p2", board=rows(close=[card("p2_defender", "scoiatael_mahakaman_defender")]))
        .weather(rows(ranged=[card("weather_fog", "neutral_impenetrable_fog")]))
        .build()
    )


def make_horn_own_row_leader_state() -> GameState:
    return (
        scenario("horn_own_row_leader_state")
        .player(
            "p1",
            faction="northern_realms",
            board=rows(
                siege=[
                    card("p1_archer_a", "scoiatael_dol_blathanna_archer"),
                    card("p1_archer_b", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .build()
    )


def make_play_weather_from_deck_leader_state() -> GameState:
    return (
        scenario("play_weather_from_deck_leader_state")
        .player(
            "p1",
            leader_id=SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
            deck=[card("p1_frost", "neutral_biting_frost")],
        )
        .player(
            "p2",
            board=rows(
                close=[
                    card("p2_defender", "scoiatael_mahakaman_defender"),
                    card("p2_griffin", "monsters_griffin"),
                ]
            ),
        )
        .build()
    )


def make_optimize_agile_rows_leader_state() -> GameState:
    return (
        scenario("optimize_agile_rows_leader_state")
        .player(
            "p1",
            leader_id=SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
            board=rows(close=[card("p1_harpy", "monsters_harpy")]),
        )
        .weather(rows(close=[card("weather_frost", "neutral_biting_frost")]))
        .build()
    )


def _round_three_passed_opponent_state(
    name: str,
    *,
    player_one_faction: str | None = "northern_realms",
    player_one_leader_id: str | None = NORTHERN_REALMS_SIEGE_SCORCH_LEADER_ID,
    player_one_leader_used: bool = False,
    player_one_deck: list[ScenarioCard] | None = None,
    player_one_hand: list[ScenarioCard] | None = None,
    player_one_board: ScenarioRows | None = None,
    player_two_faction: str | None = "nilfgaard",
    player_two_leader_used: bool = True,
    player_two_hand: list[ScenarioCard] | None = None,
    player_two_board: ScenarioRows | None = None,
    player_two_passed: bool = True,
) -> GameState:
    return (
        scenario(name)
        .round(3)
        .player(
            "p1",
            faction=player_one_faction,
            leader_id=player_one_leader_id,
            leader_used=player_one_leader_used,
            gems_remaining=1,
            round_wins=1,
            deck=player_one_deck,
            hand=player_one_hand,
            board=player_one_board,
        )
        .player(
            "p2",
            faction=player_two_faction,
            leader_used=player_two_leader_used,
            gems_remaining=1,
            round_wins=1,
            passed=player_two_passed,
            hand=player_two_hand,
            board=player_two_board,
        )
        .build()
    )


def make_round_three_visible_win_state() -> GameState:
    return _round_three_passed_opponent_state(
        "round_three_visible_win_state",
        player_one_faction=None,
        player_one_leader_id=None,
        player_one_leader_used=True,
        player_one_hand=[
            card("p1_small_unit", "scoiatael_vrihedd_brigade_recruit"),
            card("p1_large_unit", "neutral_geralt"),
        ],
        player_two_faction=None,
        player_two_leader_used=True,
        player_two_hand=[card("p2_hidden_card", "scoiatael_dol_blathanna_archer")],
        player_two_board=rows(close=[card("p2_board_unit", "scoiatael_mahakaman_defender")]),
        player_two_passed=False,
    )


def make_steel_forged_noop_state() -> GameState:
    return _round_three_passed_opponent_state(
        "steel_forged_noop_state",
        player_one_hand=[card("p1_catapult", "northern_realms_catapult")],
        player_one_board=rows(siege=[card("p1_siege_tower", "northern_realms_siege_tower")]),
        player_two_board=rows(
            close=[card("p2_close_unit", "scoiatael_mahakaman_defender")],
            siege=[
                card("p2_siege_engineer", "nilfgaard_siege_engineer"),
                card("p2_siege_technician", "nilfgaard_siege_technician"),
            ],
        ),
    )


def make_steel_forged_live_state() -> GameState:
    return _round_three_passed_opponent_state(
        "steel_forged_live_state",
        player_one_hand=[card("p1_recruit", "scoiatael_vrihedd_brigade_recruit")],
        player_two_board=rows(
            siege=[
                card("p2_siege_engineer", "nilfgaard_siege_engineer"),
                card("p2_siege_tower", "northern_realms_siege_tower"),
            ]
        ),
    )


def make_opponent_passed_spy_draw_catch_up_state() -> GameState:
    return _round_three_passed_opponent_state(
        "opponent_passed_spy_draw_catch_up_state",
        player_one_faction="nilfgaard",
        player_one_leader_id=NILFGAARD_WHITE_FLAME_LEADER_ID,
        player_one_leader_used=True,
        player_one_deck=[
            card("p1_draw_yennefer", "neutral_yennefer"),
            card("p1_draw_geralt", "neutral_geralt"),
        ],
        player_one_hand=[card("p1_spy_line", "neutral_mysterious_elf")],
        player_two_board=rows(close=[card("p2_frontliner", "scoiatael_mahakaman_defender")]),
    )


def make_unsafe_pass_winning_play_state() -> GameState:
    return (
        scenario("unsafe_pass_winning_play_state")
        .player(
            "p1",
            leader_used=True,
            hand=[card("p1_yennefer_finisher", "neutral_yennefer")],
            discard=[card("p1_revive_target", "scoiatael_vrihedd_brigade_recruit")],
            board=rows(
                close=[
                    card("p1_board_archer", "scoiatael_dol_blathanna_archer"),
                    card("p1_board_defender", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .player(
            "p2",
            leader_used=True,
            hand=[card("p2_equalizer", "scoiatael_mahakaman_defender")],
            board=rows(close=[card("p2_board_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )


def make_decoy_pending_choice_state() -> GameState:
    return (
        scenario("decoy_pending_choice_state")
        .player(
            "p1",
            hand=[card("p1_decoy_source", "neutral_decoy")],
            board=rows(
                ranged=[
                    card("p1_spy_target", "neutral_mysterious_elf", owner="p2"),
                    card("p1_filler_target", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .card_choice(
            choice_id="decoy_pending_choice",
            player_id="p1",
            source_kind=ChoiceSourceKind.DECOY,
            source_card_instance_id="p1_decoy_source",
            legal_target_card_instance_ids=("p1_spy_target", "p1_filler_target"),
        )
        .build()
    )


def make_final_round_horned_gap_state() -> GameState:
    return (
        scenario("final_round_horned_gap_state")
        .round(3)
        .player(
            "p1",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[card("p1_geralt_finisher", "neutral_geralt")],
            board=rows(ranged=[card("p1_board_archer", "nilfgaard_black_infantry_archer")]),
        )
        .player(
            "p2",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            passed=True,
            board=rows(
                close=[
                    card("p2_close_defender", "scoiatael_mahakaman_defender"),
                    card("p2_close_archer", "scoiatael_dol_blathanna_archer"),
                    card("p2_close_horn", "neutral_commanders_horn"),
                ]
            ),
        )
        .build()
    )


def make_final_round_cow_setup_state() -> GameState:
    return (
        scenario("final_round_cow_setup_state")
        .round(3)
        .current_player("p2")
        .player(
            "p1",
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[card("p1_hidden_card", "scoiatael_dol_blathanna_archer")],
        )
        .player(
            "p2",
            faction="nilfgaard",
            leader_id=NILFGAARD_WHITE_FLAME_LEADER_ID,
            leader_used=True,
            gems_remaining=1,
            round_wins=1,
            hand=[
                card("p2_cow", "neutral_avenger_cow"),
                card("p2_small_unit", "scoiatael_dol_blathanna_archer"),
            ],
        )
        .build()
    )
