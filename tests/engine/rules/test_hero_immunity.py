import pytest
from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import MedicResolvedEvent, SpecialCardResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.effect_applicability import (
    can_target_for_decoy,
    can_target_for_medic,
    eligible_destroyable_unit_ids,
)
from gwent_engine.rules.scoring import calculate_effective_strength, calculate_row_score

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID, IndexedRandom


def test_hero_strength_ignores_weather_horn_morale_and_bond_effects() -> None:
    card_registry = CARD_REGISTRY
    hero_card_id = CardInstanceId("p1_imlerith_hero")
    first_bond_card_id = CardInstanceId("p1_first_bond_vanguard")
    second_bond_card_id = CardInstanceId("p1_second_bond_vanguard")
    morale_card_id = CardInstanceId("p1_standard_bearer")
    horn_card_id = CardInstanceId("p1_close_horn")
    frost_card_id = CardInstanceId("p1_biting_frost")
    state = (
        scenario("hero_strength_ignores_weather_horn_morale_and_bond_effects")
        .player(
            PLAYER_ONE_ID,
            board=rows(
                close=[
                    card(hero_card_id, "monsters_imlerith"),
                    card(first_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(second_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(morale_card_id, "northern_realms_kaedweni_siege_expert"),
                    card(horn_card_id, "neutral_commanders_horn"),
                ]
            ),
        )
        .weather(rows(close=[card(frost_card_id, "neutral_biting_frost")]))
        .build()
    )

    assert calculate_effective_strength(state, card_registry, hero_card_id) == 10
    assert calculate_effective_strength(state, card_registry, first_bond_card_id) == 6
    assert calculate_effective_strength(state, card_registry, second_bond_card_id) == 6
    assert calculate_effective_strength(state, card_registry, morale_card_id) == 2
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 24


@pytest.mark.parametrize(
    ("definition_id", "row", "weather_id"),
    (
        ("monsters_draug", Row.CLOSE, "neutral_biting_frost"),
        ("skellige_hjalmar", Row.RANGED, "neutral_impenetrable_fog"),
    ),
)
def test_reconciled_heroes_ignore_weather(
    definition_id: str,
    row: Row,
    weather_id: str,
) -> None:
    hero_card_id = CardInstanceId("hero")
    state = (
        scenario("reconciled_hero_under_weather")
        .player(PLAYER_ONE_ID, board=rows(**{row.value: [card(hero_card_id, definition_id)]}))
        .weather(rows(**{row.value: [card("weather", weather_id)]}))
        .build()
    )

    assert calculate_effective_strength(state, CARD_REGISTRY, hero_card_id) == 10


def test_special_scorch_does_not_destroy_hero_units() -> None:
    card_registry = CARD_REGISTRY
    scorch_card_id = CardInstanceId("p1_scorch_finisher")
    hero_card_id = CardInstanceId("p2_iorveth_hero")
    first_bond_card_id = CardInstanceId("p2_first_bond_vanguard")
    second_bond_card_id = CardInstanceId("p2_second_bond_vanguard")
    reserve_hand_card_id = CardInstanceId("p2_reserve_skirmisher")
    state = (
        scenario("special_scorch_does_not_destroy_hero_units")
        .current_player(PLAYER_ONE_ID)
        .player(
            PLAYER_ONE_ID,
            hand=[card(scorch_card_id, "neutral_scorch")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_hand_card_id, "scoiatael_vrihedd_brigade_recruit")],
            board=rows(
                close=[
                    card(first_bond_card_id, "northern_realms_blue_stripes_commando"),
                    card(second_bond_card_id, "northern_realms_blue_stripes_commando"),
                ],
                ranged=[card(hero_card_id, "neutral_geralt")],
            ),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=scorch_card_id),
        card_registry=card_registry,
    )

    assert next_state.card(hero_card_id).zone == Zone.BATTLEFIELD
    assert next_state.card(first_bond_card_id).zone == Zone.DISCARD
    assert next_state.card(second_bond_card_id).zone == Zone.DISCARD
    scorch_event = next(event for event in events if isinstance(event, SpecialCardResolvedEvent))
    assert set(scorch_event.discarded_card_instance_ids) == {
        scorch_card_id,
        first_bond_card_id,
        second_bond_card_id,
    }


def test_hero_cannot_be_targeted_by_decoy() -> None:
    state = (
        scenario("hero_cannot_be_targeted_by_decoy")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_decoy_tactician", "neutral_decoy")],
            board=rows(ranged=[card("p1_iorveth_hero", "neutral_geralt")]),
        )
        .build()
    )

    with pytest.raises(
        IllegalActionError,
        match="valid non-hero unit card on your battlefield",
    ):
        _ = apply_action(
            state,
            PlayCardAction(
                player_id=PLAYER_ONE_ID,
                card_instance_id=CardInstanceId("p1_decoy_tactician"),
            ),
            card_registry=CARD_REGISTRY,
        )


def test_hero_cannot_be_targeted_by_medic() -> None:
    state = (
        scenario("hero_cannot_be_targeted_by_medic")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_field_surgeon", "scoiatael_havekar_healer")],
            discard=[card("p1_discarded_iorveth_hero", "neutral_geralt")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve_unit", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_field_surgeon"),
            target_row=Row.RANGED,
        ),
        card_registry=CARD_REGISTRY,
    )
    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (CardInstanceId("p1_field_surgeon"),)
    assert next_state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId("p1_discarded_iorveth_hero"),
    )
    assert isinstance(events[-1], MedicResolvedEvent)
    assert events[-1].resurrected_card_instance_id is None


def test_ves_is_affected_and_targetable_as_an_ordinary_unit() -> None:
    battlefield_ves_id = CardInstanceId("p1_battlefield_ves")
    discarded_ves_id = CardInstanceId("p1_discarded_ves")
    state = (
        scenario("ves_is_not_a_hero")
        .player(
            PLAYER_ONE_ID,
            hand=[card("p1_reserve", "scoiatael_mahakaman_defender")],
            discard=[card(discarded_ves_id, "northern_realms_ves")],
            board=rows(close=[card(battlefield_ves_id, "northern_realms_ves")]),
        )
        .weather(rows(close=[card("frost", "neutral_biting_frost")]))
        .build()
    )
    player = state.player(PLAYER_ONE_ID)

    assert calculate_effective_strength(state, CARD_REGISTRY, battlefield_ves_id) == 1
    assert can_target_for_decoy(
        state, CARD_REGISTRY, player=player, target_card_id=battlefield_ves_id
    )
    assert can_target_for_medic(
        state, CARD_REGISTRY, player=player, target_card_id=discarded_ves_id
    )
    assert eligible_destroyable_unit_ids(state, CARD_REGISTRY, (battlefield_ves_id,)) == (
        battlefield_ves_id,
    )


def test_monsters_passive_discards_heroes_and_opposing_units() -> None:
    card_registry = CARD_REGISTRY
    hero_card_id = CardInstanceId("p1_imlerith_hero")
    opponent_unit_card_id = CardInstanceId("p2_frontline_vanguard")
    state = (
        scenario("monsters_passive_discards_heroes_and_opposing_units")
        .current_player(PLAYER_ONE_ID)
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
            hand=[card("p1_reserve_card", "scoiatael_mahakaman_defender")],
            board=rows(close=[card(hero_card_id, "monsters_imlerith")]),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            passed=True,
            board=rows(close=[card(opponent_unit_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_ONE_ID),
        rng=IndexedRandom(choice_index=0),
        card_registry=card_registry,
    )

    assert next_state.card(hero_card_id).zone == Zone.DISCARD
    assert next_state.card(opponent_unit_card_id).zone == Zone.DISCARD
    assert next_state.player(PLAYER_ONE_ID).rows.all_cards() == ()
    assert next_state.player(PLAYER_TWO_ID).rows.all_cards() == ()
