from __future__ import annotations

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline.projection import (
    current_public_scorch_impact,
    project_play_action,
)
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId

from tests.support import PLAYER_ONE_ID

from ...scenario_builder import card, rows, scenario
from ...support import (
    CARD_REGISTRY,
)
from ..support import play_action_for


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
    action = play_action_for(
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
    action = play_action_for(
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
            board=rows(ranged=[card("p1_ermion", "skellige_ermion")]),
        )
        .build()
    )
    observation = build_player_observation(state, PLAYER_ONE_ID)
    action = play_action_for(
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
    action = play_action_for(
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
    action = play_action_for(
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
