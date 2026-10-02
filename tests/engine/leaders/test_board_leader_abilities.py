from dataclasses import replace

import pytest
from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.leader_common import is_agile_battlefield_unit
from gwent_engine.rules.scoring import calculate_row_score

from tests.engine.leaders.support import leader_scenario
from tests.engine.scenario_builder import card, rows
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_ANY_WEATHER_LEADER_ID,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
    SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
    SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_active_clear_weather_leader_consumes_turn_and_cannot_be_used_twice() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p2_biting_frost_weather", "neutral_biting_frost", owner=PLAYER_TWO_ID)
    reserve = card("p2_reserve_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    state = (
        leader_scenario("clear_weather_leader_consumes_turn")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NORTHERN_REALMS,
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=(reserve,),
        )
        .weather(rows(close=[frost]))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert next_state.current_player == PLAYER_TWO_ID
    assert next_state.weather.close == ()
    assert next_state.weather.ranged == ()
    assert next_state.weather.siege == ()
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == (CardInstanceId(frost.instance_id),)

    with pytest.raises(IllegalActionError, match="at most once per battle"):
        _ = apply_action(
            replace(next_state, current_player=PLAYER_ONE_ID),
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


def test_specific_weather_from_deck_leader_auto_plays_matching_weather_card() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p1_deck_biting_frost_weather", "neutral_biting_frost")
    reserve = card("p1_deck_reserve_vanguard_unit", "scoiatael_mahakaman_defender")
    opponent_hand = card("p2_hand_reserve_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    state = (
        leader_scenario("specific_weather_from_deck_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
            deck=(frost, reserve),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).deck == (CardInstanceId(reserve.instance_id),)
    assert next_state.weather.close == (CardInstanceId(frost.instance_id),)
    assert next_state.card(CardInstanceId(frost.instance_id)).zone == Zone.WEATHER
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.played_card_instance_id == CardInstanceId(frost.instance_id)
    assert leader_event.affected_row == Row.CLOSE


def test_any_weather_leader_requires_explicit_choice_with_multiple_weather_cards() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p1_deck_biting_frost_weather", "neutral_biting_frost")
    fog = card("p1_deck_impenetrable_fog_weather", "neutral_impenetrable_fog")
    reserve = card("p1_deck_reserve_griffin_unit", "monsters_griffin")
    opponent_hand = card("p2_hand_reserve_archer_unit", "scoiatael_dol_blathanna_archer")
    state = (
        leader_scenario("any_weather_leader_requires_choice")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_ANY_WEATHER_LEADER_ID,
            deck=(frost, fog, reserve),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    with pytest.raises(IllegalActionError, match="choose which weather card"):
        _ = apply_action(
            state,
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(
            player_id=PLAYER_ONE_ID,
            target_card_instance_id=CardInstanceId(fog.instance_id),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).deck == (
        CardInstanceId(frost.instance_id),
        CardInstanceId(reserve.instance_id),
    )
    assert next_state.weather.ranged == (CardInstanceId(fog.instance_id),)
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.played_card_instance_id == CardInstanceId(fog.instance_id)
    assert leader_event.affected_row == Row.RANGED


def test_horn_own_row_leader_marks_leader_horn_row_and_doubles_row_score() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    ranged_archer = card("p1_ranged_archer_unit", "scoiatael_dol_blathanna_archer")
    ranged_skirmisher = card("p1_ranged_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    opponent_hand = card("p2_hand_reserve_vanguard_unit", "scoiatael_mahakaman_defender")
    state = (
        leader_scenario("horn_own_row_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            board=rows(ranged=[ranged_archer, ranged_skirmisher]),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.horn_row == Row.RANGED
    assert (
        calculate_row_score(
            next_state,
            card_registry,
            PLAYER_ONE_ID,
            Row.RANGED,
            leader_registry=leader_registry,
        )
        == 16
    )


def test_row_scorch_leader_respects_hero_immunity() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero = card("p2_close_hero_imlerith", "monsters_imlerith")
    first_close = card("p2_close_vanguard_alpha", "scoiatael_mahakaman_defender")
    second_close = card("p2_close_vanguard_beta", "scoiatael_mahakaman_defender")
    opponent_hand = card("p2_hand_reserve_archer_unit", "scoiatael_dol_blathanna_archer")
    state = (
        leader_scenario("row_scorch_leader_respects_hero_immunity")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=(opponent_hand,),
            board=rows(close=[hero, first_close, second_close]),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.card(CardInstanceId(hero.instance_id)).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId(first_close.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(second_close.instance_id)).zone == Zone.DISCARD
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == (
        CardInstanceId(first_close.instance_id),
        CardInstanceId(second_close.instance_id),
    )


def test_optimize_agile_rows_leader_moves_all_battlefield_agile_units_and_keeps_ties() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    moving_agile = card("p1_agile_outrider_to_optimize", "scoiatael_barclay_els")
    tied_agile = card("p2_agile_outrider_keep_current_row", "scoiatael_barclay_els")
    ranged_horn = card("p1_ranged_commanders_horn", "neutral_commanders_horn")
    opponent_hand = card("p2_hand_reserve_ballista_unit", "northern_realms_ballista")
    state = (
        leader_scenario("optimize_agile_rows_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
            board=rows(close=[moving_agile], ranged=[ranged_horn]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(opponent_hand,),
            board=rows(ranged=[tied_agile]),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.card(CardInstanceId(moving_agile.instance_id)).row == Row.RANGED
    assert next_state.card(CardInstanceId(tied_agile.instance_id)).row == Row.RANGED
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        CardInstanceId(ranged_horn.instance_id),
        CardInstanceId(moving_agile.instance_id),
    )
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.moved_card_instance_ids == (CardInstanceId(moving_agile.instance_id),)


@pytest.mark.parametrize(
    "definition_id",
    [
        "monsters_celaeno_harpy",
        "neutral_olgierd_von_everec",
        "skellige_olaf",
    ],
)
def test_hope_of_the_aen_seidhe_moves_newly_tagged_agile_units(definition_id: str) -> None:
    agile_id = CardInstanceId("p1_agile_unit")
    state = (
        leader_scenario("hope_moves_agile_unit")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
            board=rows(
                close=[card(agile_id, definition_id)],
                ranged=[card("p1_ranged_horn", "neutral_commanders_horn")],
            ),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert next_state.card(agile_id).row == Row.RANGED
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.moved_card_instance_ids == (agile_id,)


def test_hope_of_the_aen_seidhe_excludes_agile_heroes() -> None:
    kayran_id = CardInstanceId("p1_kayran")
    state = (
        leader_scenario("hope_excludes_agile_hero")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
            board=rows(close=[card(kayran_id, "monsters_kayran")]),
        )
        .build()
    )

    assert not is_agile_battlefield_unit(state, CARD_REGISTRY, kayran_id)
    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assert next_state.card(kayran_id).row == Row.CLOSE
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.moved_card_instance_ids == ()
