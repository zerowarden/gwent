from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import CardPlayedEvent, CardsDrawnEvent, SpyResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_player_score

from ..scenario_builder import card, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_spy_is_played_to_opponent_side_and_draws_up_to_two_cards() -> None:
    card_registry = CARD_REGISTRY
    spy_card_id = CardInstanceId("p1_spy_infiltrator")
    first_draw_card_id = CardInstanceId("p1_drawn_agile_outrider")
    second_draw_card_id = CardInstanceId("p1_drawn_bond_vanguard")
    state = (
        scenario("spy_draws_two_cards")
        .player(
            PLAYER_ONE_ID,
            hand=(card(spy_card_id, "northern_realms_prince_stennis"),),
            deck=(
                card(first_draw_card_id, "scoiatael_barclay_els"),
                card(second_draw_card_id, "northern_realms_blue_stripes_commando"),
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_vanguard", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=spy_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    played_spy = next_state.card(spy_card_id)
    assert next_state.player(PLAYER_TWO_ID).rows.close == (spy_card_id,)
    assert next_state.player(PLAYER_ONE_ID).hand == (first_draw_card_id, second_draw_card_id)
    assert next_state.player(PLAYER_ONE_ID).deck == ()
    assert played_spy.zone == Zone.BATTLEFIELD
    assert played_spy.row == Row.CLOSE
    assert played_spy.battlefield_side == PLAYER_TWO_ID
    assert calculate_player_score(next_state, card_registry, PLAYER_TWO_ID).total == 5
    assert isinstance(events[0], CardPlayedEvent)
    assert isinstance(events[1], CardsDrawnEvent)
    assert isinstance(events[2], SpyResolvedEvent)


def test_spy_returns_to_owner_discard_after_round_cleanup() -> None:
    card_registry = CARD_REGISTRY
    spy_card_id = CardInstanceId("p1_spy_infiltrator")
    state = (
        scenario("spy_returns_to_owner_discard")
        .player(
            PLAYER_ONE_ID,
            hand=(card(spy_card_id, "northern_realms_prince_stennis"),),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_vanguard", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=spy_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )

    assert spy_card_id in state.player(PLAYER_ONE_ID).discard
    assert spy_card_id not in state.player(PLAYER_TWO_ID).discard


def test_spy_draw_respects_max_hand_size() -> None:
    card_registry = CARD_REGISTRY
    spy_card_id = CardInstanceId("p1_spy_prince_stennis")
    draw_card_id = CardInstanceId("p1_drawn_blue_stripes_commando")
    blocked_draw_card_id = CardInstanceId("p1_undrawn_trebuchet_reserve")
    state = (
        scenario("spy_draw_respects_max_hand_size")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(spy_card_id, "northern_realms_prince_stennis"),
                *tuple(
                    card(
                        f"p1_hand_reserve_{index}",
                        "scoiatael_mahakaman_defender",
                    )
                    for index in range(1, 17)
                ),
            ),
            deck=(
                card(draw_card_id, "northern_realms_blue_stripes_commando"),
                card(blocked_draw_card_id, "northern_realms_trebuchet"),
            ),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=spy_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert len(next_state.player(PLAYER_ONE_ID).hand) == 17
    assert draw_card_id in next_state.player(PLAYER_ONE_ID).hand
    assert blocked_draw_card_id not in next_state.player(PLAYER_ONE_ID).hand
    assert next_state.player(PLAYER_ONE_ID).deck == (blocked_draw_card_id,)
    assert isinstance(events[1], CardsDrawnEvent)
    assert events[1].card_instance_ids == (draw_card_id,)
    assert isinstance(events[2], SpyResolvedEvent)
    assert events[2].drawn_card_instance_ids == (draw_card_id,)
