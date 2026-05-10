import pytest
from gwent_engine.cards.models import CardDefinition
from gwent_engine.core import CardType, FactionId, Row
from gwent_engine.core.actions import PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.primitives import PLAYER_ONE_ID
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
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
