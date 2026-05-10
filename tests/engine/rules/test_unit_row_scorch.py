from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import UnitScorchResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


def test_unit_row_scorch_uses_only_the_mirrored_opponent_row_and_respects_hero_immunity() -> None:
    card_registry = CARD_REGISTRY
    row_scorch_card_id = CardInstanceId("p1_drakeslayer_row_scorch")
    hero_card_id = CardInstanceId("p2_geralt_hero")
    siege_archer_card_id = CardInstanceId("p2_siege_archer")
    close_vanguard_card_id = CardInstanceId("p2_close_vanguard")
    reserve_hand_card_id = CardInstanceId("p2_reserve_skirmisher")
    state = (
        scenario("unit_row_scorch_respects_hero_immunity")
        .player(
            PLAYER_ONE_ID,
            hand=[card(row_scorch_card_id, "scoiatael_schirru")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_hand_card_id, "scoiatael_vrihedd_brigade_recruit")],
            board=rows(
                close=[card(close_vanguard_card_id, "scoiatael_mahakaman_defender")],
                siege=[
                    card(hero_card_id, "neutral_geralt"),
                    card(siege_archer_card_id, "scoiatael_dol_blathanna_archer"),
                ],
            ),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=row_scorch_card_id,
            target_row=Row.SIEGE,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(hero_card_id).zone == Zone.BATTLEFIELD
    assert next_state.card(siege_archer_card_id).zone == Zone.DISCARD
    assert next_state.card(close_vanguard_card_id).zone == Zone.BATTLEFIELD
    scorch_event = next(event for event in events if isinstance(event, UnitScorchResolvedEvent))
    assert scorch_event.destroyed_card_instance_ids == (siege_archer_card_id,)


def test_unit_row_scorch_destroys_all_tied_strongest_non_hero_units() -> None:
    card_registry = CARD_REGISTRY
    row_scorch_card_id = CardInstanceId("p1_drakeslayer_row_scorch")
    first_siege_archer_card_id = CardInstanceId("p2_first_siege_ballista")
    second_siege_archer_card_id = CardInstanceId("p2_second_siege_ballista")
    reserve_hand_card_id = CardInstanceId("p2_reserve_skirmisher")
    state = (
        scenario("unit_row_scorch_destroys_tied_strongest")
        .player(
            PLAYER_ONE_ID,
            hand=[card(row_scorch_card_id, "scoiatael_schirru")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_hand_card_id, "scoiatael_vrihedd_brigade_recruit")],
            board=rows(
                siege=[
                    card(first_siege_archer_card_id, "northern_realms_ballista"),
                    card(second_siege_archer_card_id, "northern_realms_ballista"),
                ]
            ),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=row_scorch_card_id,
            target_row=Row.SIEGE,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(first_siege_archer_card_id).zone == Zone.DISCARD
    assert next_state.card(second_siege_archer_card_id).zone == Zone.DISCARD
    scorch_event = next(event for event in events if isinstance(event, UnitScorchResolvedEvent))
    assert scorch_event.destroyed_card_instance_ids == (
        first_siege_archer_card_id,
        second_siege_archer_card_id,
    )


def test_unit_row_scorch_is_a_noop_when_the_threshold_is_not_met() -> None:
    card_registry = CARD_REGISTRY
    row_scorch_card_id = CardInstanceId("p1_drakeslayer_row_scorch")
    siege_vanguard_card_id = CardInstanceId("p2_siege_vanguard")
    reserve_hand_card_id = CardInstanceId("p2_reserve_skirmisher")
    state = (
        scenario("unit_row_scorch_threshold_noop")
        .player(
            PLAYER_ONE_ID,
            hand=[card(row_scorch_card_id, "scoiatael_schirru")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_hand_card_id, "scoiatael_vrihedd_brigade_recruit")],
            board=rows(siege=[card(siege_vanguard_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=row_scorch_card_id,
            target_row=Row.SIEGE,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(siege_vanguard_card_id).zone == Zone.BATTLEFIELD
    scorch_event = next(event for event in events if isinstance(event, UnitScorchResolvedEvent))
    assert scorch_event.destroyed_card_instance_ids == ()
