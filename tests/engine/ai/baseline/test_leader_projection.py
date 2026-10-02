from __future__ import annotations

from gwent_engine.ai.baseline.projection import (
    project_leader_action,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.ids import CardInstanceId

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import card, scenario
from ...support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
)
from ..support import (
    make_clear_weather_leader_state,
    make_horn_own_row_leader_state,
    make_optimize_agile_rows_leader_state,
    make_play_weather_from_deck_leader_state,
    make_steel_forged_live_state,
    make_steel_forged_noop_state,
)


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
