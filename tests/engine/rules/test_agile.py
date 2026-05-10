import pytest
from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_agile_unit_may_be_played_to_close_or_ranged_row() -> None:
    card_registry = CARD_REGISTRY

    for target_row in (Row.CLOSE, Row.RANGED):
        agile_card_id = CardInstanceId("p1_agile_outrider")
        state = (
            scenario(f"agile_unit_{target_row.value}")
            .player(PLAYER_ONE_ID, hand=(card(agile_card_id, "scoiatael_barclay_els"),))
            .player(
                PLAYER_TWO_ID,
                hand=(card("p2_reserve_vanguard", "scoiatael_mahakaman_defender"),),
            )
            .build()
        )

        next_state, _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=agile_card_id,
                target_row=target_row,
            ),
            card_registry=card_registry,
        )

        played_card = next_state.card(agile_card_id)
        assert next_state.player(PLAYER_ONE_ID).rows.cards_for(target_row) == (agile_card_id,)
        assert played_card.zone == Zone.BATTLEFIELD
        assert played_card.row == target_row
        assert played_card.battlefield_side == PLAYER_ONE_ID


def test_agile_unit_may_not_be_played_to_siege() -> None:
    agile_card_id = CardInstanceId("p1_agile_outrider")
    state = (
        scenario("agile_unit_may_not_be_played_to_siege")
        .player(PLAYER_ONE_ID, hand=(card(agile_card_id, "scoiatael_barclay_els"),))
        .player(
            PLAYER_TWO_ID,
            hand=(card("p2_reserve_vanguard", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="cannot be played to row"):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=agile_card_id,
                target_row=Row.SIEGE,
            ),
            card_registry=CARD_REGISTRY,
        )


def test_agile_unit_cleans_up_like_a_normal_unit() -> None:
    card_registry = CARD_REGISTRY
    agile_card_id = CardInstanceId("p1_agile_outrider")
    state = (
        scenario("agile_unit_cleans_up_normally")
        .player(PLAYER_ONE_ID, hand=(card(agile_card_id, "scoiatael_barclay_els"),))
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
            card_instance_id=agile_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )
    next_state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
    )

    assert agile_card_id in next_state.player(PLAYER_ONE_ID).discard
    assert next_state.player(PLAYER_ONE_ID).rows.all_cards() == ()
