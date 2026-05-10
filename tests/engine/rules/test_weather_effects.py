import pytest
from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import CardPlayedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.battlefield_effects import active_weather_cards, weather_card_affects_row
from gwent_engine.rules.scoring import calculate_row_score

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


@pytest.mark.parametrize(
    (
        "player_one_unit_definition_id",
        "player_two_unit_definition_id",
        "weather_card_definition_id",
        "affected_row",
    ),
    (
        (
            "scoiatael_mahakaman_defender",
            "scoiatael_mahakaman_defender",
            "neutral_biting_frost",
            Row.CLOSE,
        ),
        (
            "scoiatael_dol_blathanna_archer",
            "scoiatael_dol_blathanna_archer",
            "neutral_impenetrable_fog",
            Row.RANGED,
        ),
        (
            "northern_realms_ballista",
            "northern_realms_ballista",
            "neutral_torrential_rain",
            Row.SIEGE,
        ),
    ),
)
def test_weather_cards_set_affected_row_to_one_for_both_players(
    player_one_unit_definition_id: str,
    player_two_unit_definition_id: str,
    weather_card_definition_id: str,
    affected_row: Row,
) -> None:
    card_registry = CARD_REGISTRY
    player_one_unit_id = CardInstanceId("p1_weather_target_unit")
    player_two_unit_id = CardInstanceId("p2_weather_target_unit")
    weather_card_id = CardInstanceId("p1_weather_special")
    player_one_reserve_card_id = CardInstanceId("p1_reserve_card")
    player_two_reserve_card_id = CardInstanceId("p2_reserve_card")
    state = (
        scenario(f"weather_cards_set_{affected_row.value}_to_one")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(weather_card_id, weather_card_definition_id),
                card(player_one_reserve_card_id, "scoiatael_dol_blathanna_archer"),
            ],
            board=rows(
                **{affected_row.value: [card(player_one_unit_id, player_one_unit_definition_id)]}
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_reserve_card_id, "scoiatael_mahakaman_defender")],
            board=rows(
                **{affected_row.value: [card(player_two_unit_id, player_two_unit_definition_id)]}
            ),
        )
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=weather_card_id,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, affected_row) == 1
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, affected_row) == 1
    assert state.weather.cards_for(affected_row) == (weather_card_id,)
    assert state.card(weather_card_id).zone == Zone.WEATHER
    assert isinstance(events[0], CardPlayedEvent)
    assert events[0].target_row == affected_row
    assert len(events) == 1


def test_skellige_storm_sets_ranged_and_siege_rows_to_one_for_both_players() -> None:
    card_registry = CARD_REGISTRY
    player_one_ranged_unit_id = CardInstanceId("p1_ranged_archer_under_skellige_storm")
    player_one_siege_unit_id = CardInstanceId("p1_siege_ballista_under_skellige_storm")
    player_two_ranged_unit_id = CardInstanceId("p2_ranged_archer_under_skellige_storm")
    player_two_siege_unit_id = CardInstanceId("p2_siege_ballista_under_skellige_storm")
    storm_card_id = CardInstanceId("p1_skellige_storm_weather")
    player_one_reserve_card_id = CardInstanceId("p1_reserve_defender")
    player_two_reserve_card_id = CardInstanceId("p2_reserve_recruit")
    state = (
        scenario("skellige_storm_sets_ranged_and_siege_rows_to_one")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(storm_card_id, "neutral_skellige_storm"),
                card(player_one_reserve_card_id, "scoiatael_mahakaman_defender"),
            ],
            board=rows(
                ranged=[card(player_one_ranged_unit_id, "scoiatael_dol_blathanna_archer")],
                siege=[card(player_one_siege_unit_id, "northern_realms_ballista")],
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_reserve_card_id, "scoiatael_vrihedd_brigade_recruit")],
            board=rows(
                ranged=[card(player_two_ranged_unit_id, "scoiatael_dol_blathanna_archer")],
                siege=[card(player_two_siege_unit_id, "northern_realms_ballista")],
            ),
        )
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=storm_card_id,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.RANGED) == 1
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.SIEGE) == 1
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, Row.RANGED) == 1
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, Row.SIEGE) == 1
    assert active_weather_cards(state) == (storm_card_id,)
    assert state.battlefield_weather.cards_for(Row.RANGED) == (storm_card_id,)
    assert state.battlefield_weather.cards_for(Row.SIEGE) == ()
    assert state.card(storm_card_id).zone == Zone.WEATHER
    assert state.player(PLAYER_ONE_ID).rows.cards_for(Row.RANGED) == (player_one_ranged_unit_id,)
    assert weather_card_affects_row(state, card_registry, storm_card_id, Row.RANGED)
    assert weather_card_affects_row(state, card_registry, storm_card_id, Row.SIEGE)
    assert isinstance(events[0], CardPlayedEvent)
    assert events[0].target_row == Row.RANGED
    assert len(events) == 1


def test_multiple_weather_effects_can_be_active_at_once() -> None:
    card_registry = CARD_REGISTRY
    close_unit_id = CardInstanceId("p1_close_defender_under_frost")
    ranged_unit_id = CardInstanceId("p1_ranged_archer_under_storm")
    siege_unit_id = CardInstanceId("p1_siege_ballista_under_storm")
    active_frost_card_id = CardInstanceId("p2_active_biting_frost")
    storm_card_id = CardInstanceId("p1_skellige_storm_weather")
    player_one_reserve_card_id = CardInstanceId("p1_reserve_recruit")
    player_two_reserve_card_id = CardInstanceId("p2_reserve_defender")
    state = (
        scenario("multiple_weather_effects_can_be_active")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(storm_card_id, "neutral_skellige_storm"),
                card(player_one_reserve_card_id, "scoiatael_vrihedd_brigade_recruit"),
            ],
            board=rows(
                close=[card(close_unit_id, "scoiatael_mahakaman_defender")],
                ranged=[card(ranged_unit_id, "scoiatael_dol_blathanna_archer")],
                siege=[card(siege_unit_id, "northern_realms_ballista")],
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_reserve_card_id, "scoiatael_mahakaman_defender")],
        )
        .weather(rows(close=[card(active_frost_card_id, "neutral_biting_frost")]))
        .build()
    )

    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=storm_card_id,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 1
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.RANGED) == 1
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.SIEGE) == 1
    assert state.weather.cards_for(Row.CLOSE) == (active_frost_card_id,)
    assert state.weather.cards_for(Row.RANGED) == (storm_card_id,)
    assert state.card(active_frost_card_id).zone == Zone.WEATHER
    assert state.card(storm_card_id).zone == Zone.WEATHER


def test_duplicate_weather_effects_do_not_stack() -> None:
    card_registry = CARD_REGISTRY
    close_unit_id = CardInstanceId("p1_close_defender_under_double_frost")
    first_frost_card_id = CardInstanceId("p1_first_biting_frost_weather")
    second_frost_card_id = CardInstanceId("p1_second_biting_frost_weather")
    player_one_reserve_card_id = CardInstanceId("p1_reserve_recruit")
    player_two_archer_card_id = CardInstanceId("p2_archer_during_double_frost")
    base_state = (
        scenario("duplicate_weather_effects_do_not_stack")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(first_frost_card_id, "neutral_biting_frost"),
                card(second_frost_card_id, "neutral_biting_frost"),
                card(player_one_reserve_card_id, "scoiatael_vrihedd_brigade_recruit"),
            ],
            board=rows(close=[card(close_unit_id, "scoiatael_mahakaman_defender")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_archer_card_id, "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    state, _ = apply_action(
        base_state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=first_frost_card_id,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_TWO_ID,
            card_instance_id=player_two_archer_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=second_frost_card_id,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 1
    assert state.weather.cards_for(Row.CLOSE) == (first_frost_card_id, second_frost_card_id)
