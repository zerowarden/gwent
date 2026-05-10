import json

from gwent_engine.ai.observations import build_player_observation, build_public_game_view
from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    build_in_round_game_state,
)


def test_player_observation_hides_opponent_hand_identities() -> None:
    state, _ = build_in_round_game_state()
    observation = build_player_observation(state, PLAYER_ONE_ID)
    opponent_hand_ids = state.player(PLAYER_TWO_ID).hand

    payload = json.dumps(
        {
            "public_state": build_public_game_view(state),
            "observation": observation,
        },
        default=str,
        sort_keys=True,
    )

    assert {card.instance_id for card in observation.viewer_hand} == set(
        state.player(PLAYER_ONE_ID).hand
    )
    assert all(str(card_id) not in payload for card_id in opponent_hand_ids)
    assert observation.public_state.players[1].hand_count == len(opponent_hand_ids)


def test_player_observation_exposes_viewer_deck_and_available_horn_row() -> None:
    state = (
        scenario("observation_viewer_deck")
        .player(
            "p1",
            deck=[
                card("p1_deck_archer", "scoiatael_dol_blathanna_archer"),
                card("p1_deck_horn", "neutral_commanders_horn"),
            ],
        )
        .build()
    )

    observation = build_player_observation(state, PLAYER_ONE_ID, LEADER_REGISTRY)

    assert tuple(card.instance_id for card in observation.viewer_deck) == (
        "p1_deck_archer",
        "p1_deck_horn",
    )
    assert observation.public_state.players[0].leader.available_horn_row == Row.RANGED
    assert observation.public_state.players[1].leader.available_horn_row == Row.RANGED


def test_only_pending_choice_player_sees_legal_targets() -> None:
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    battlefield_target_id = CardInstanceId("p1_mahakaman_defender_frontliner")
    opponent_card_id = CardInstanceId("p2_dol_blathanna_archer_skirmisher")
    state = (
        scenario("pending_choice_visibility")
        .player(
            "p1",
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card(battlefield_target_id, "scoiatael_mahakaman_defender")]),
        )
        .player(
            "p2",
            board=rows(ranged=[card(opponent_card_id, "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )
    pending_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    chooser_observation = build_player_observation(pending_state, PLAYER_ONE_ID)
    opponent_observation = build_player_observation(pending_state, PLAYER_TWO_ID)

    assert chooser_observation.visible_pending_choice is not None
    assert chooser_observation.visible_pending_choice.legal_target_card_instance_ids == (
        battlefield_target_id,
    )
    assert opponent_observation.visible_pending_choice is None
    assert opponent_observation.public_state.pending_choice is not None


def test_public_game_view_exposes_weather_cards_from_weather_zone() -> None:
    state = (
        scenario("public_game_view_weather")
        .weather(
            rows(
                close=[card("p1_active_biting_frost_weather", "neutral_biting_frost")],
                ranged=[card("p2_active_impenetrable_fog_weather", "neutral_impenetrable_fog")],
            )
        )
        .build()
    )

    public_view = build_public_game_view(state)

    assert public_view.battlefield_weather.close[0].instance_id == "p1_active_biting_frost_weather"
    assert public_view.battlefield_weather.close[0].row == Row.CLOSE
    assert public_view.battlefield_weather.close[0].battlefield_side is None
    assert public_view.battlefield_weather.ranged[0].instance_id == (
        "p2_active_impenetrable_fog_weather"
    )
    assert public_view.battlefield_weather.ranged[0].row == Row.RANGED
