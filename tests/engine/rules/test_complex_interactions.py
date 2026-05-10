from gwent_engine.core import AbilityKind, Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_effective_strength, calculate_row_score

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import CARD_REGISTRY


## TODO: Add docstring explaining the interaction
def test_weather_bond_horn_and_morale_follow_the_documented_pipeline() -> None:
    card_registry = CARD_REGISTRY
    first_bond_card_id = CardInstanceId("p1_first_bond_vanguard")
    second_bond_card_id = CardInstanceId("p1_second_bond_vanguard")
    morale_card_id = CardInstanceId("p1_olgierd_morale_booster")
    horn_card_id = CardInstanceId("p1_commanders_horn")
    frost_card_id = CardInstanceId("p1_biting_frost")
    state = (
        scenario("weather_bond_horn_and_morale_pipeline")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card(first_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(second_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(morale_card_id, "neutral_olgierd_von_everec"),
                    card(horn_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .weather(rows(close=[card(frost_card_id, "neutral_biting_frost")]))
        .build()
    )

    assert calculate_effective_strength(state, card_registry, first_bond_card_id) == 6
    assert calculate_effective_strength(state, card_registry, second_bond_card_id) == 6
    assert calculate_effective_strength(state, card_registry, morale_card_id) == 2
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 14


def test_scorch_uses_phase9_effective_strength_when_destroying_units() -> None:
    card_registry = CARD_REGISTRY
    scorch_card_id = CardInstanceId("p1_scorch_finisher")
    first_bond_card_id = CardInstanceId("p1_first_bond_vanguard")
    second_bond_card_id = CardInstanceId("p1_second_bond_vanguard")
    morale_card_id = CardInstanceId("p1_olgierd_morale_booster")
    horn_card_id = CardInstanceId("p1_commanders_horn")
    frost_card_id = CardInstanceId("p1_biting_frost")
    opponent_archer_card_id = CardInstanceId("p2_ranged_archer")
    reserve_card_id = CardInstanceId("p2_reserve_vanguard")
    state = (
        scenario("scorch_uses_effective_strength")
        .player(
            PLAYER_ONE_ID,
            hand=[card(scorch_card_id, "neutral_scorch")],
            board=rows(
                close=[
                    card(first_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(second_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(morale_card_id, "neutral_olgierd_von_everec"),
                    card(horn_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_card_id, "scoiatael_mahakaman_defender")],
            board=rows(ranged=[card(opponent_archer_card_id, "scoiatael_dol_blathanna_archer")]),
        )
        .weather(rows(close=[card(frost_card_id, "neutral_biting_frost")]))
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=scorch_card_id,
        ),
        card_registry=card_registry,
    )

    assert next_state.card(first_bond_card_id).zone == Zone.DISCARD
    assert next_state.card(second_bond_card_id).zone == Zone.DISCARD
    assert next_state.card(opponent_archer_card_id).zone == Zone.BATTLEFIELD
    assert next_state.card(morale_card_id).zone == Zone.BATTLEFIELD
    scorch_event = next(event for event in events if isinstance(event, SpecialCardResolvedEvent))
    assert scorch_event.ability_kind == AbilityKind.SCORCH
    assert set(scorch_event.discarded_card_instance_ids) == {
        scorch_card_id,
        first_bond_card_id,
        second_bond_card_id,
    }
