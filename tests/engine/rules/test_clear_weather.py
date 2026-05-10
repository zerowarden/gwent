from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import CardPlayedEvent, SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import RowState
from gwent_engine.rules.row_effects import row_has_commanders_horn, row_has_special_mardroeme
from gwent_engine.rules.scoring import calculate_row_score

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_clear_weather_discards_active_weather_cards_and_restores_scores() -> None:
    card_registry = CARD_REGISTRY
    close_weather_card_id = CardInstanceId("p1_active_biting_frost")
    ranged_weather_card_id = CardInstanceId("p2_active_impenetrable_fog")
    clear_weather_card_id = CardInstanceId("p1_clear_weather")
    state = (
        scenario("clear_weather_restores_scores")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(clear_weather_card_id, "neutral_clear_weather"),
                card("p1_reserve_archer", "scoiatael_dol_blathanna_archer"),
            ),
            board=rows(close=[card("p1_close_defender", "scoiatael_mahakaman_defender")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),),
            board=rows(ranged=[card("p2_ranged_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .weather(
            rows(
                close=[card(close_weather_card_id, "neutral_biting_frost")],
                ranged=[
                    card(
                        ranged_weather_card_id,
                        "neutral_impenetrable_fog",
                        owner=PLAYER_TWO_ID,
                    )
                ],
            )
        )
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=clear_weather_card_id,
        ),
        card_registry=card_registry,
    )

    assert state.weather.all_cards() == ()
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 5
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, Row.RANGED) == 4
    assert state.card(close_weather_card_id).zone == Zone.DISCARD
    assert state.card(ranged_weather_card_id).zone == Zone.DISCARD
    assert state.card(clear_weather_card_id).zone == Zone.DISCARD
    assert state.player(PLAYER_ONE_ID).discard == (
        close_weather_card_id,
        clear_weather_card_id,
    )
    assert state.player(PLAYER_TWO_ID).discard == (ranged_weather_card_id,)
    assert isinstance(events[0], CardPlayedEvent)
    assert events[0].target_row is None
    assert isinstance(events[1], SpecialCardResolvedEvent)
    assert events[1].discarded_card_instance_ids == (
        close_weather_card_id,
        ranged_weather_card_id,
        clear_weather_card_id,
    )


def test_clear_weather_only_clears_battlefield_weather_zone() -> None:
    card_registry = CARD_REGISTRY
    clear_weather_card_id = CardInstanceId("p1_clear_weather_spell")
    active_frost_card_id = CardInstanceId("p1_active_biting_frost_weather")
    active_horn_card_id = CardInstanceId("p1_active_commanders_horn_special")
    active_mardroeme_card_id = CardInstanceId("p2_active_mardroeme_special")
    state = (
        scenario("clear_weather_only_clears_weather_zone")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(clear_weather_card_id, "neutral_clear_weather"),
                card("p1_reserve_archer", "scoiatael_dol_blathanna_archer"),
            ),
            board=rows(ranged=[card(active_horn_card_id, "neutral_commanders_horn")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),),
            board=rows(siege=[card(active_mardroeme_card_id, "skellige_mardroeme")]),
        )
        .weather(rows(close=[card(active_frost_card_id, "neutral_biting_frost")]))
        .build()
    )

    next_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=clear_weather_card_id,
        ),
        card_registry=card_registry,
    )

    assert next_state.battlefield_weather == RowState()
    assert next_state.card(active_frost_card_id).zone == Zone.DISCARD
    assert next_state.card(active_horn_card_id).zone == Zone.BATTLEFIELD
    assert next_state.card(active_mardroeme_card_id).zone == Zone.BATTLEFIELD
    assert row_has_commanders_horn(next_state, card_registry, PLAYER_ONE_ID, Row.RANGED)
    assert row_has_special_mardroeme(next_state, card_registry, PLAYER_TWO_ID, Row.SIEGE)
