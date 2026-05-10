import pytest
from gwent_engine.core.actions import PassAction, PlayCardAction, ResolveChoiceAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardInstanceId, ChoiceId
from gwent_engine.core.reducer import apply_action

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


def test_pending_choice_blocks_other_actions_and_rejects_invalid_resolution() -> None:
    card_registry = CARD_REGISTRY
    frontliner_card_id = CardInstanceId("p1_vanguard_frontliner")
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    reserve_opponent_card_id = CardInstanceId("p2_reserve_archer")
    state = (
        scenario("pending_choice_blocks_other_actions")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card(frontliner_card_id, "scoiatael_mahakaman_defender")]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_opponent_card_id, "scoiatael_dol_blathanna_archer")],
        )
        .build()
    )

    pending_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=card_registry,
    )

    assert events == ()
    assert pending_state.pending_choice is not None
    choice_id = pending_state.pending_choice.choice_id

    with pytest.raises(IllegalActionError, match="pending choice must be resolved"):
        _ = apply_action(
            pending_state,
            PassAction(player_id=PLAYER_ONE_ID),
            card_registry=card_registry,
        )

    with pytest.raises(IllegalActionError, match="pending-choice player"):
        _ = apply_action(
            pending_state,
            ResolveChoiceAction(
                player_id=PLAYER_TWO_ID,
                choice_id=choice_id,
                selected_card_instance_ids=(frontliner_card_id,),
            ),
            card_registry=card_registry,
        )

    with pytest.raises(IllegalActionError, match="choice_id does not match"):
        _ = apply_action(
            pending_state,
            ResolveChoiceAction(
                player_id=PLAYER_ONE_ID,
                choice_id=ChoiceId("wrong_choice_id"),
                selected_card_instance_ids=(frontliner_card_id,),
            ),
            card_registry=card_registry,
        )

    with pytest.raises(IllegalActionError, match="illegal target card"):
        _ = apply_action(
            pending_state,
            ResolveChoiceAction(
                player_id=PLAYER_ONE_ID,
                choice_id=choice_id,
                selected_card_instance_ids=(reserve_opponent_card_id,),
            ),
            card_registry=card_registry,
        )
