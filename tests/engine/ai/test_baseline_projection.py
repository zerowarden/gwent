from __future__ import annotations

from math import isclose

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.projection import (
    current_public_scorch_impact,
    project_leader_action,
    project_play_action,
    projected_future_card_value,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.cards.registry import CardRegistry
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.core.state import GameState

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    PLAYER_ONE_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
)
from .test_baseline_support import (
    make_clear_weather_leader_state,
    make_horn_own_row_leader_state,
    make_optimize_agile_rows_leader_state,
    make_play_weather_from_deck_leader_state,
    make_steel_forged_live_state,
    make_steel_forged_noop_state,
)


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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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
    action = _play_action_for(
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


def test_project_leader_action_models_steel_forged_as_noop_below_row_threshold() -> None:
    state = make_steel_forged_noop_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.projected_net_board_swing == 0
    assert projection.minimum_row_total == 10
    assert projection.opponent_row_total == 6
    assert projection.live_targets == 0
    assert projection.has_effect is False


def test_project_leader_action_models_steel_forged_live_row_scorch() -> None:
    state = make_steel_forged_live_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.minimum_row_total == 10
    assert projection.opponent_row_total == 12
    assert projection.live_targets == 2
    assert projection.projected_net_board_swing == 12
    assert projection.has_effect is True


def test_project_leader_action_models_clear_weather_recovery() -> None:
    state = make_clear_weather_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "clear_weather"
    assert projection.projected_net_board_swing == 9
    assert projection.has_effect is True


def test_project_leader_action_models_horn_own_row_swing() -> None:
    state = make_horn_own_row_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "horn_own_row"
    assert projection.projected_net_board_swing == 8
    assert projection.affected_row == Row.SIEGE
    assert projection.has_effect is True


def test_project_leader_action_models_weather_from_deck_swing() -> None:
    state = make_play_weather_from_deck_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(
            player_id=PLAYER_ONE_ID,
            target_card_instance_id=CardInstanceId("p1_frost"),
        ),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "play_weather_from_deck"
    assert projection.projected_net_board_swing == 8
    assert projection.weather_rows_changed == (Row.CLOSE,)
    assert projection.has_effect is True


def test_project_leader_action_models_agile_row_optimization() -> None:
    state = make_optimize_agile_rows_leader_state()
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "optimize_agile_rows"
    assert projection.projected_net_board_swing == 1
    assert projection.moved_units == 1
    assert projection.has_effect is True


def test_project_leader_action_models_discard_and_choose_from_deck_value() -> None:
    state = (
        scenario("projection_leader_discard_and_choose")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_destroyer_of_worlds",
            hand=[
                card("p1_discard_recruit", "scoiatael_vrihedd_brigade_recruit"),
                card("p1_discard_archer", "scoiatael_dol_blathanna_archer"),
            ],
            deck=[
                card("p1_pick_geralt", "neutral_geralt"),
                card("p1_skip_trebuchet", "northern_realms_trebuchet"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "discard_and_choose_from_deck"
    assert projection.projected_net_board_swing == 0
    assert projection.projected_hand_value_delta == 9
    assert projection.viewer_hand_count_delta == -1
    assert projection.live_targets == 4
    assert projection.has_effect is True


def test_project_leader_action_models_return_from_own_discard_value() -> None:
    state = (
        scenario("projection_leader_return_discard")
        .player(
            "p1",
            faction="monsters",
            leader_id="monsters_eredin_bringer_of_death",
            discard=[
                card("p1_return_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_return_catapult", "northern_realms_catapult"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "return_card_from_own_discard_to_hand"
    assert projection.projected_hand_value_delta == 8
    assert projection.viewer_hand_count_delta == 1
    assert projection.live_targets == 2
    assert projection.has_effect is True


def test_project_leader_action_models_take_from_opponent_discard_value() -> None:
    state = (
        scenario("projection_leader_take_opponent_discard")
        .player(
            "p1",
            faction="nilfgaard",
            leader_id="nilfgaard_emhyr_the_relentless",
        )
        .player(
            "p2",
            discard=[
                card("p2_steal_hero", "neutral_geralt"),
                card("p2_steal_catapult", "northern_realms_catapult"),
            ],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    projection = project_leader_action(
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        observation=observation,
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert projection is not None
    assert projection.ability_kind.value == "take_card_from_opponent_discard_to_hand"
    assert projection.projected_hand_value_delta == 8
    assert projection.viewer_hand_count_delta == 1
    assert projection.live_targets == 1
    assert projection.has_effect is True


def test_current_public_scorch_impact_uses_effective_strengths() -> None:
    state = (
        scenario("projection_effective_scorch_impact")
        .player(
            "p2",
            leader_horn_row=Row.CLOSE,
            board=rows(close=[card("p2_defender", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)

    impact = current_public_scorch_impact(
        observation,
        card_registry=CARD_REGISTRY,
    )

    assert impact.viewer_strength_lost == 0
    assert impact.opponent_strength_lost == 10
    assert impact.net_swing == 10


def test_project_play_action_exposes_exact_scorch_damage_split() -> None:
    scorch_card_id = CardInstanceId("p1_scorch")
    state = (
        scenario("projection_scorch_damage_split")
        .player(
            "p1",
            leader_horn_row=Row.CLOSE,
            hand=[card(scorch_card_id, "neutral_scorch")],
            board=rows(close=[card("p1_defender", "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            leader_horn_row=Row.CLOSE,
            board=rows(close=[card("p2_defender", "scoiatael_mahakaman_defender")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = _play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=scorch_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.viewer_scorch_damage == 10
    assert projection.opponent_scorch_damage == 10
    assert projection.net_scorch_swing == 0


def test_project_play_action_models_row_scorch() -> None:
    toad_card_id = CardInstanceId("p1_toad")
    state = (
        scenario("projection_row_scorch")
        .player(
            "p1",
            hand=[card(toad_card_id, "monsters_toad")],
        )
        .player(
            "p2",
            board=rows(
                ranged=[
                    card("p2_archer", "skellige_clan_brokvar_archer"),
                    card("p2_recruit", "scoiatael_vrihedd_brigade_recruit"),
                ]
            ),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = _play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=toad_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 13


def test_project_play_action_transforms_berserker_when_special_mardroeme_is_played() -> None:
    mardroeme_card_id = CardInstanceId("p1_mardroeme")
    state = (
        scenario("projection_special_mardroeme")
        .player(
            "p1",
            hand=[card(mardroeme_card_id, "skellige_mardroeme")],
            board=rows(close=[card("p1_berserker", "skellige_berserker")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = next(
        candidate
        for candidate in enumerate_legal_actions(
            state,
            player_id=PLAYER_ONE_ID,
            card_registry=CARD_REGISTRY,
        )
        if (
            isinstance(candidate, PlayCardAction)
            and candidate.card_instance_id == mardroeme_card_id
            and candidate.target_row == Row.CLOSE
        )
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 10


def test_project_play_action_transforms_new_berserker_on_active_mardroeme_row() -> None:
    young_berserker_card_id = CardInstanceId("p1_young_berserker")
    state = (
        scenario("projection_active_mardroeme_row")
        .player(
            "p1",
            hand=[card(young_berserker_card_id, "skellige_young_berserker")],
            board=rows(close=[card("p1_ermion", "skellige_ermion")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = _play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=young_berserker_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 8


def test_project_play_action_exposes_delayed_avenger_value() -> None:
    kambi_card_id = CardInstanceId("p1_kambi")
    state = (
        scenario("projection_delayed_avenger_value")
        .player(
            "p1",
            hand=[card(kambi_card_id, "skellige_kambi")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = _play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=kambi_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 0
    assert projection.projected_avenger_value == 11


def test_project_play_action_does_not_value_avenger_reserve_in_final_round() -> None:
    kambi_card_id = CardInstanceId("p1_kambi")
    state = (
        scenario("projection_final_round_no_avenger_reserve")
        .round(3)
        .player(
            "p1",
            hand=[card(kambi_card_id, "skellige_kambi")],
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = _play_action_for(
        state,
        card_registry=CARD_REGISTRY,
        card_instance_id=kambi_card_id,
    )

    projection = project_play_action(
        action,
        observation=observation,
        card_registry=CARD_REGISTRY,
    )

    assert projection.projected_net_board_swing == 0
    assert projection.projected_avenger_value == 0


def _play_action_for(
    state: GameState,
    *,
    card_registry: CardRegistry,
    card_instance_id: CardInstanceId,
) -> PlayCardAction:
    legal_actions = enumerate_legal_actions(
        state,
        player_id=PLAYER_ONE_ID,
        card_registry=card_registry,
    )
    return next(
        action
        for action in legal_actions
        if isinstance(action, PlayCardAction) and action.card_instance_id == card_instance_id
    )
