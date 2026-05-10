from gwent_engine.core import AbilityKind, Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_scorch_kills_all_tied_strongest_units_and_discards_itself() -> None:
    card_registry = CARD_REGISTRY
    scorch_card = card("p1_global_scorch_special", "neutral_scorch")
    player_one_unit = card("p1_close_strongest_unit", "scoiatael_mahakaman_defender")
    player_two_unit = card("p2_close_strongest_unit", "scoiatael_mahakaman_defender")
    state = (
        scenario("scorch_kills_tied_strongest")
        .player(
            PLAYER_ONE_ID,
            hand=(scorch_card,),
            board=rows(close=[player_one_unit]),
        )
        .player(PLAYER_TWO_ID, board=rows(close=[player_two_unit]))
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(scorch_card.instance_id),
        ),
        card_registry=card_registry,
    )

    assert state.player(PLAYER_ONE_ID).rows.close == ()
    assert state.player(PLAYER_ONE_ID).rows.siege == ()
    assert state.player(PLAYER_TWO_ID).rows.close == ()
    assert state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId(player_one_unit.instance_id),
        CardInstanceId(scorch_card.instance_id),
    )
    assert state.player(PLAYER_TWO_ID).discard == (CardInstanceId(player_two_unit.instance_id),)
    assert state.card(CardInstanceId(player_one_unit.instance_id)).zone == Zone.DISCARD
    assert state.card(CardInstanceId(player_two_unit.instance_id)).zone == Zone.DISCARD
    assert state.card(CardInstanceId(scorch_card.instance_id)).zone == Zone.DISCARD
    assert isinstance(events[1], SpecialCardResolvedEvent)
    assert events[1].discarded_card_instance_ids == (
        CardInstanceId(player_one_unit.instance_id),
        CardInstanceId(player_two_unit.instance_id),
        CardInstanceId(scorch_card.instance_id),
    )


def test_scorch_ignores_special_cards_when_no_units_exist() -> None:
    card_registry = CARD_REGISTRY
    frost = card("p1_weather_only_frost", "neutral_biting_frost")
    scorch_card = card("p1_weather_only_scorch", "neutral_scorch")
    reserve = card("p2_weather_test_reserve_unit", "scoiatael_dol_blathanna_archer")
    state = (
        scenario("scorch_ignores_specials_without_units")
        .player(PLAYER_ONE_ID, hand=(scorch_card,))
        .player(PLAYER_TWO_ID, hand=(reserve,))
        .weather(rows(close=[frost]))
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(scorch_card.instance_id),
        ),
        card_registry=card_registry,
    )

    assert state.weather.close == (CardInstanceId(frost.instance_id),)
    assert state.player(PLAYER_ONE_ID).discard == (CardInstanceId(scorch_card.instance_id),)
    assert isinstance(events[1], SpecialCardResolvedEvent)
    assert events[1].discarded_card_instance_ids == (CardInstanceId(scorch_card.instance_id),)


def test_unit_scorch_card_uses_global_scorch_logic_without_discarding_itself() -> None:
    card_registry = CARD_REGISTRY
    pirate_card = card("p1_clan_dimun_pirate_scorcher", "skellige_clan_dimun_pirate")
    player_one_strongest = card("p1_strongest_schirru_target", "scoiatael_schirru")
    player_two_strongest = card("p2_strongest_schirru_target", "scoiatael_schirru")
    player_two_reserve = card("p2_reserve_defender", "scoiatael_mahakaman_defender")
    state = (
        scenario("unit_scorch_uses_global_logic")
        .player(
            PLAYER_ONE_ID,
            hand=(pirate_card,),
            board=rows(siege=[player_one_strongest]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(player_two_reserve,),
            board=rows(siege=[player_two_strongest]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(pirate_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(CardInstanceId(pirate_card.instance_id)).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId(pirate_card.instance_id)).row == Row.RANGED
    assert next_state.card(CardInstanceId(player_one_strongest.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(player_two_strongest.instance_id)).zone == Zone.DISCARD
    scorch_event = next(
        event
        for event in events
        if isinstance(event, SpecialCardResolvedEvent)
        and event.card_instance_id == CardInstanceId(pirate_card.instance_id)
    )
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert scorch_event.discarded_card_instance_ids == (
        CardInstanceId(player_one_strongest.instance_id),
        CardInstanceId(player_two_strongest.instance_id),
    )


def test_clan_dimun_pirate_self_destructs_when_no_stronger_units_exist() -> None:
    card_registry = CARD_REGISTRY
    pirate_card = card("p1_clan_dimun_pirate_self_destructs", "skellige_clan_dimun_pirate")
    player_one_weaker = card("p1_weaker_close_defender", "scoiatael_mahakaman_defender")
    player_two_weaker = card("p2_weaker_ranged_archer", "scoiatael_dol_blathanna_archer")
    player_two_reserve = card("p2_reserve_skirmisher", "scoiatael_vrihedd_brigade_recruit")
    state = (
        scenario("clan_dimun_pirate_self_destructs")
        .player(
            PLAYER_ONE_ID,
            hand=(pirate_card,),
            board=rows(close=[player_one_weaker]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(player_two_reserve,),
            board=rows(ranged=[player_two_weaker]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(pirate_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(CardInstanceId(pirate_card.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(player_one_weaker.instance_id)).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId(player_two_weaker.instance_id)).zone == Zone.BATTLEFIELD
    scorch_event = next(
        event
        for event in events
        if isinstance(event, SpecialCardResolvedEvent)
        and event.card_instance_id == CardInstanceId(pirate_card.instance_id)
    )
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert scorch_event.discarded_card_instance_ids == (CardInstanceId(pirate_card.instance_id),)


def test_clan_dimun_pirate_destroys_itself_and_tied_highest_units() -> None:
    card_registry = CARD_REGISTRY
    pirate_card = card("p1_clan_dimun_pirate_tied_for_highest", "skellige_clan_dimun_pirate")
    tied_enemy = card("p2_tied_six_strength_archer", "skellige_clan_brokvar_archer")
    surviving_enemy = card("p2_lower_strength_defender", "scoiatael_mahakaman_defender")
    player_two_reserve = card("p2_reserve_skirmisher", "scoiatael_vrihedd_brigade_recruit")
    state = (
        scenario("clan_dimun_pirate_destroys_tied_highest")
        .player(PLAYER_ONE_ID, hand=(pirate_card,))
        .player(
            PLAYER_TWO_ID,
            hand=(player_two_reserve,),
            board=rows(close=[surviving_enemy], ranged=[tied_enemy]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(pirate_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(CardInstanceId(pirate_card.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(tied_enemy.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(surviving_enemy.instance_id)).zone == Zone.BATTLEFIELD
    scorch_event = next(
        event
        for event in events
        if isinstance(event, SpecialCardResolvedEvent)
        and event.card_instance_id == CardInstanceId(pirate_card.instance_id)
    )
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert set(scorch_event.discarded_card_instance_ids) == {
        CardInstanceId(pirate_card.instance_id),
        CardInstanceId(tied_enemy.instance_id),
    }


def test_clan_dimun_pirate_under_fog_can_destroy_strength_one_units() -> None:
    card_registry = CARD_REGISTRY
    pirate_card = card("p1_clan_dimun_pirate_under_fog", "skellige_clan_dimun_pirate")
    enemy_weathered = card("p2_weathered_ranged_archer", "scoiatael_dol_blathanna_archer")
    active_fog = card("p1_active_impenetrable_fog", "neutral_impenetrable_fog")
    player_two_reserve = card("p2_reserve_defender", "scoiatael_mahakaman_defender")
    state = (
        scenario("clan_dimun_pirate_under_fog")
        .player(PLAYER_ONE_ID, hand=(pirate_card,))
        .player(
            PLAYER_TWO_ID,
            hand=(player_two_reserve,),
            board=rows(ranged=[enemy_weathered]),
        )
        .weather(rows(ranged=[active_fog]))
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(pirate_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(CardInstanceId(pirate_card.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(enemy_weathered.instance_id)).zone == Zone.DISCARD
    scorch_event = next(
        event
        for event in events
        if isinstance(event, SpecialCardResolvedEvent)
        and event.card_instance_id == CardInstanceId(pirate_card.instance_id)
    )
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert set(scorch_event.discarded_card_instance_ids) == {
        CardInstanceId(pirate_card.instance_id),
        CardInstanceId(enemy_weathered.instance_id),
    }


def test_clan_dimun_pirate_under_horn_only_destroys_twelve_or_higher_strength_units() -> None:
    card_registry = CARD_REGISTRY
    pirate_card = card("p1_clan_dimun_pirate_under_horn", "skellige_clan_dimun_pirate")
    active_horn = card("p1_active_ranged_commanders_horn", "neutral_commanders_horn")
    tied_twelve = card("p2_twelve_strength_olaf", "skellige_olaf")
    surviving_ten = card("p2_ten_strength_draug", "monsters_draug")
    player_two_reserve = card("p2_reserve_skirmisher", "scoiatael_vrihedd_brigade_recruit")
    state = (
        scenario("clan_dimun_pirate_under_horn")
        .player(
            PLAYER_ONE_ID,
            hand=(pirate_card,),
            board=rows(ranged=[active_horn]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(player_two_reserve,),
            board=rows(close=[tied_twelve, surviving_ten]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(pirate_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(CardInstanceId(pirate_card.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(tied_twelve.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(surviving_ten.instance_id)).zone == Zone.BATTLEFIELD
    scorch_event = next(
        event
        for event in events
        if isinstance(event, SpecialCardResolvedEvent)
        and event.card_instance_id == CardInstanceId(pirate_card.instance_id)
    )
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert set(scorch_event.discarded_card_instance_ids) == {
        CardInstanceId(pirate_card.instance_id),
        CardInstanceId(tied_twelve.instance_id),
    }
