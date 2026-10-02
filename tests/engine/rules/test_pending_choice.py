import pytest
from gwent_engine.cards.models import CardDefinition
from gwent_engine.core import CardType, FactionId, Row
from gwent_engine.core.actions import (
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId, ChoiceId
from gwent_engine.core.reducer import apply_action

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


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


@pytest.mark.parametrize(
    ("definition_id", "instance_id"),
    (
        ("scoiatael_barclay_els", "p1_agile_outrider_one_shot"),
        ("northern_realms_prince_stennis", "p1_spy_infiltrator_one_shot"),
        ("scoiatael_dwarven_skirmisher", "p1_muster_warband_one_shot"),
        ("northern_realms_kaedweni_siege_expert", "p1_morale_bearer_one_shot"),
        ("northern_realms_blue_stripes_commando", "p1_bond_vanguard_one_shot"),
        ("neutral_dandelion", "p1_unit_horn_one_shot"),
        ("scoiatael_schirru", "p1_unit_row_scorch_one_shot"),
        ("neutral_biting_frost", "p1_biting_frost_one_shot"),
        ("neutral_clear_weather", "p1_clear_weather_one_shot"),
        ("neutral_commanders_horn", "p1_special_horn_one_shot"),
        ("neutral_scorch", "p1_special_scorch_one_shot"),
    ),
)
def test_one_shot_cards_do_not_create_pending_choice(
    definition_id: str,
    instance_id: str,
) -> None:
    card_registry = CARD_REGISTRY
    card_id = CardInstanceId(instance_id)
    definition = card_registry.get(CardDefinitionId(definition_id))
    target_row = _initial_target_row(definition)
    state = (
        scenario(f"{instance_id}_one_shot")
        .player(
            PLAYER_ONE_ID,
            hand=[card(card_id, definition_id)],
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=card_id,
            target_row=target_row,
        ),
        card_registry=card_registry,
        leader_registry=LEADER_REGISTRY,
    )

    assert next_state.pending_choice is None


def test_simple_one_shot_leader_does_not_create_pending_choice() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    state = (
        scenario("simple_one_shot_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NORTHERN_REALMS,
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            hand=[card("p1_reserve_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).leader.used is True


def _initial_target_row(definition: CardDefinition) -> Row | None:
    if definition.card_type == CardType.UNIT:
        return definition.allowed_rows[0]
    if definition.definition_id == CardDefinitionId("neutral_commanders_horn"):
        return Row.CLOSE
    return None
