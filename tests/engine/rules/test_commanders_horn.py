import pytest
from gwent_engine.core import Row
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_row_score

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
)


def test_commanders_horn_doubles_a_row_and_is_limited_to_one_per_row() -> None:
    card_registry = CARD_REGISTRY
    first_horn_card_id = CardInstanceId("p1_horn_special")
    second_horn_card_id = CardInstanceId("p1_second_horn_special")
    state = (
        scenario("commanders_horn_doubles_row")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(first_horn_card_id, "neutral_commanders_horn"),
                card(second_horn_card_id, "neutral_commanders_horn"),
            ),
            board=rows(close=[card("p1_close_frontliner", "scoiatael_mahakaman_defender")]),
        )
        .player(
            PLAYER_TWO_ID,
            board=rows(ranged=[card("p2_ranged_archer", "scoiatael_dol_blathanna_archer")]),
        )
        .build()
    )

    state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=first_horn_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 10
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, Row.RANGED) == 4
    assert isinstance(events[1], SpecialCardResolvedEvent)
    assert events[1].affected_row == Row.CLOSE

    state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
    )

    with pytest.raises(IllegalActionError, match="more than one Commander's Horn"):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=second_horn_card_id,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )
