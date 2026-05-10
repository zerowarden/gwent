from gwent_engine.core import Phase, Zone
from gwent_engine.core.actions import PassAction
from gwent_engine.core.events import CardsMovedToDiscardEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


def test_round_cleanup_discards_active_weather_and_horn_cards() -> None:
    card_registry = CARD_REGISTRY
    player_one_unit_id = CardInstanceId("p1_close_frontliner")
    player_two_unit_id = CardInstanceId("p2_close_frontliner")
    horn_card_id = CardInstanceId("p1_close_row_horn")
    weather_card_id = CardInstanceId("p2_close_row_frost")
    player_two_reserve_id = CardInstanceId("p2_round_cleanup_reserve_unit")
    state = (
        scenario("round_cleanup_discards_active_weather_and_horn_cards")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card(player_one_unit_id, "scoiatael_mahakaman_defender"),
                    card(horn_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_reserve_id, "scoiatael_dol_blathanna_archer")],
            board=rows(close=[card(player_two_unit_id, "scoiatael_mahakaman_defender")]),
        )
        .weather(rows(close=[card(weather_card_id, "neutral_biting_frost")]))
        .build()
    )
    state, _ = apply_action(state, PassAction(player_id=PLAYER_ONE_ID), card_registry=card_registry)

    state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )

    cleanup_event = next(event for event in events if isinstance(event, CardsMovedToDiscardEvent))

    assert set(cleanup_event.card_instance_ids) == {
        player_one_unit_id,
        player_two_unit_id,
        horn_card_id,
        weather_card_id,
    }
    assert state.weather.all_cards() == ()
    assert state.card(horn_card_id).zone == Zone.DISCARD
    assert state.card(weather_card_id).zone == Zone.DISCARD
    assert state.phase == Phase.IN_ROUND
