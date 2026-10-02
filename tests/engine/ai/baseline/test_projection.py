from __future__ import annotations

from math import isclose

from gwent_engine.ai.baseline.projection import (
    project_play_action,
    projected_future_card_value,
)
from gwent_engine.ai.baseline.projection.board import current_public_board_projection
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.rules.scoring import calculate_round_scores

from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_DOUBLE_SPY_LEADER_ID,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
)
from ..support import play_action_for


def test_project_play_action_removes_the_played_card_from_hand_value() -> None:
    archer_card_id = CardInstanceId("p1_archer")
    state = (
        scenario("projection_remove_played_card")
        .player(
            "p1",
            hand=[
                card(archer_card_id, "scoiatael_dol_blathanna_archer"),
                card("p1_geralt", "neutral_geralt"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=archer_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.post_action_hand_value == projected_future_card_value(
        CARD_REGISTRY.get(CardDefinitionId("neutral_geralt")),
        observation=observation,
        card_registry=CARD_REGISTRY,
    )


def test_project_play_action_preserves_row_scorch_option_value_in_remaining_hand() -> None:
    vill_card_id = CardInstanceId("p1_vill")
    olgierd_card_id = CardInstanceId("p1_olgierd")
    state = (
        scenario("projection_preserve_row_scorch_option_value")
        .player(
            "p1",
            hand=[
                card(vill_card_id, "neutral_villentretenmerth"),
                card(olgierd_card_id, "neutral_olgierd_von_everec"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=olgierd_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert (
        projection.post_action_hand_value
        > CARD_REGISTRY.get(CardDefinitionId("neutral_villentretenmerth")).base_strength
    )


def test_projected_future_card_value_preserves_unit_horn_reserve_value() -> None:
    state = (
        scenario("future_value_preserves_unit_horn_reserve")
        .player(
            "p1",
            board=rows(
                close=[
                    card("p1_archer", "scoiatael_mahakaman_defender"),
                    card("p1_swordsman", "scoiatael_dol_blathanna_archer"),
                ]
            ),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)

    value = projected_future_card_value(
        CARD_REGISTRY.get(CardDefinitionId("neutral_dandelion")),
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert value > CARD_REGISTRY.get(CardDefinitionId("neutral_dandelion")).base_strength


def test_projected_future_card_value_preserves_morale_boost_reserve_value() -> None:
    state = (
        scenario("future_value_preserves_morale_boost_reserve")
        .player(
            "p1",
            board=rows(
                close=[
                    card("p1_warrior", "skellige_clan_an_craie_warrior"),
                    card("p1_archer", "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)

    value = projected_future_card_value(
        CARD_REGISTRY.get(CardDefinitionId("skellige_olaf")),
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert value > CARD_REGISTRY.get(CardDefinitionId("skellige_olaf")).base_strength


def test_projected_future_card_value_preserves_berserker_transform_reserve_value() -> None:
    state = (
        scenario("future_value_preserves_berserker_transform_reserve")
        .player(
            "p1",
            board=rows(close=[card("p1_mardroeme", "skellige_mardroeme")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)

    value = projected_future_card_value(
        CARD_REGISTRY.get(CardDefinitionId("skellige_berserker")),
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert value > CARD_REGISTRY.get(CardDefinitionId("skellige_berserker")).base_strength


def test_project_play_action_models_spy_as_negative_board_tempo_but_positive_cards() -> None:
    spy_card_id = CardInstanceId("p1_spy")
    draw_a_card_id = CardInstanceId("p1_draw_a")
    draw_b_card_id = CardInstanceId("p1_draw_b")
    state = (
        scenario("projection_spy_draws")
        .player(
            "p1",
            hand=[
                card(spy_card_id, "northern_realms_prince_stennis"),
                card("p1_archer", "scoiatael_dol_blathanna_archer"),
            ],
            deck=[
                card(draw_a_card_id, "scoiatael_dol_blathanna_archer"),
                card(draw_b_card_id, "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=spy_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing < 0
    assert projection.viewer_hand_count_after == 3


def test_project_play_action_caps_spy_draws_to_remaining_deck_size() -> None:
    spy_card_id = CardInstanceId("p1_spy")
    state = (
        scenario("projection_spy_caps_draws")
        .player(
            "p1",
            hand=[card(spy_card_id, "northern_realms_prince_stennis")],
            deck=[card("p1_last_draw", "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=spy_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.viewer_hand_count_after == 1


def test_project_play_action_does_not_gain_cards_from_revived_spy_when_deck_empty() -> None:
    medic_card_id = CardInstanceId("p1_medic")
    state = (
        scenario("projection_medic_empty_deck_spy")
        .player(
            "p1",
            hand=[card(medic_card_id, "nilfgaard_etolian_auxilary_archer")],
            discard=[card("p1_discard_spy", "nilfgaard_shilard_fitz_oesterlen")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=medic_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.viewer_hand_count_after == 0


def test_project_play_action_counts_visible_muster_from_deck() -> None:
    arachas_card_id = CardInstanceId("p1_arachas_1")
    state = (
        scenario("projection_muster_from_deck")
        .player(
            "p1",
            hand=[card(arachas_card_id, "monsters_arachas")],
            deck=[card("p1_arachas_2", "monsters_arachas")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=arachas_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 8
    assert projection.post_action_hand_value == 0
    assert projection.viewer_hand_count_after == 0


def test_project_play_action_consumes_matching_muster_cards_in_hand() -> None:
    brewess_id = CardInstanceId("p1_crone_brewess")
    state = (
        scenario("projection_muster_from_hand_and_deck")
        .player(
            "p1",
            hand=[
                card(brewess_id, "monsters_crone_brewess"),
                card("p1_crone_weavess", "monsters_crone_weavess"),
            ],
            deck=[card("p1_crone_whispess", "monsters_crone_whispess")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=brewess_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 18
    assert projection.viewer_hand_count_after == 0
    assert projection.post_action_hand_value == 0


def test_project_play_action_only_values_horn_when_draw_reachable() -> None:
    spy_card_id = CardInstanceId("p1_spy")
    state = (
        scenario("projection_horn_draw_reachable")
        .player(
            "p1",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            hand=[card(spy_card_id, "northern_realms_prince_stennis")],
            deck=[
                card("p1_deck_horn", "neutral_commanders_horn"),
                card("p1_deck_archer_a", "scoiatael_dol_blathanna_archer"),
                card("p1_deck_archer_b", "scoiatael_dol_blathanna_archer"),
                card("p1_deck_archer_c", "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(close=[card("p1_defender", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=spy_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert isclose(projection.horn_future_option_delta, 2.5)


def test_project_play_action_only_values_leader_horn_on_its_own_row() -> None:
    archer_card_id = CardInstanceId("p1_archer")
    state = (
        scenario("projection_leader_horn_own_row")
        .player(
            "p1",
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=[card(archer_card_id, "scoiatael_dol_blathanna_archer")],
            board=rows(
                close=[
                    card("p1_defender_a", "scoiatael_mahakaman_defender"),
                    card("p1_defender_b", "scoiatael_mahakaman_defender"),
                ]
            ),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)
    action = play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=archer_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.horn_future_option_delta == 4


def test_board_projection_matches_engine_scoring_with_leader_passives() -> None:
    state = (
        scenario("projection_leader_passives")
        .player(
            "p1",
            faction="skellige",
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            board=rows(close=[card("p1_close_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .player(
            "p2",
            faction="monsters",
            leader_id=MONSTERS_DOUBLE_SPY_LEADER_ID,
            board=rows(ranged=[card("p2_spy", "nilfgaard_vattier_de_rideaux")]),
        )
        .weather(rows(close=[card("weather_frost", "neutral_biting_frost")]))
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = current_public_board_projection(
        observation,
        card_registry=CARD_REGISTRY,
    )
    engine_scores = {
        score.player_id: score.total
        for score in calculate_round_scores(
            state,
            CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )
    }

    assert projection.viewer_score == engine_scores[PLAYER_ONE_ID]
    assert projection.opponent_score == engine_scores[PLAYER_TWO_ID]
    viewer_leader = next(
        player.leader
        for player in observation.public_state.players
        if player.player_id == PLAYER_ONE_ID
    )
    assert viewer_leader.halves_weather_penalty

    opponent_observation = build_player_observation(state, PLAYER_TWO_ID, LEADER_REGISTRY)
    opponent_leader = next(
        player.leader
        for player in opponent_observation.public_state.players
        if player.player_id == PLAYER_TWO_ID
    )
    assert opponent_leader.doubles_spy_strength
