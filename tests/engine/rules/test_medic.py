from gwent_engine.core import ChoiceSourceKind, Row, Zone
from gwent_engine.core.actions import PlayCardAction, ResolveChoiceAction
from gwent_engine.core.events import MedicResolvedEvent, MusterResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import CARD_REGISTRY


def test_playing_medic_creates_pending_choice_with_only_valid_discard_units() -> None:
    card_registry = CARD_REGISTRY
    medic_card_id = CardInstanceId("p1_field_surgeon")
    valid_discard_unit_card_id = CardInstanceId("p1_discard_vanguard_skirmisher")
    hero_discard_card_id = CardInstanceId("p1_discard_hero_iorveth")
    special_discard_card_id = CardInstanceId("p1_discard_clear_weather")
    state = (
        scenario("playing_medic_creates_pending_choice")
        .player(
            PLAYER_ONE_ID,
            hand=[card(medic_card_id, "scoiatael_havekar_healer")],
            discard=[
                card(valid_discard_unit_card_id, "scoiatael_mahakaman_defender"),
                card(hero_discard_card_id, "neutral_geralt"),
                card(special_discard_card_id, "neutral_clear_weather"),
            ],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=medic_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert events == ()
    assert next_state.pending_choice is not None
    assert next_state.pending_choice.source_kind == ChoiceSourceKind.MEDIC
    assert next_state.pending_choice.source_card_instance_id == medic_card_id
    assert next_state.pending_choice.source_row == Row.RANGED
    assert next_state.pending_choice.legal_target_card_instance_ids == (valid_discard_unit_card_id,)
    assert next_state.current_player == PLAYER_ONE_ID
    assert next_state.card(medic_card_id).zone == Zone.HAND


def test_resolving_medic_choice_plays_the_unit_and_resurrects_the_selected_target() -> None:
    card_registry = CARD_REGISTRY
    medic_card_id = CardInstanceId("p1_field_surgeon")
    resurrected_card_id = CardInstanceId("p1_discard_vanguard_skirmisher")
    reserve_opponent_card_id = CardInstanceId("p2_reserve_vanguard")
    state = (
        scenario("resolving_medic_choice_plays_unit_and_resurrects_target")
        .player(
            PLAYER_ONE_ID,
            hand=[card(medic_card_id, "scoiatael_havekar_healer")],
            discard=[card(resurrected_card_id, "scoiatael_mahakaman_defender")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_opponent_card_id, "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    pending_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=medic_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )
    assert pending_state.pending_choice is not None

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(resurrected_card_id,),
        ),
        card_registry=card_registry,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (medic_card_id,)
    assert next_state.player(PLAYER_ONE_ID).rows.close == (resurrected_card_id,)
    assert next_state.player(PLAYER_ONE_ID).discard == ()
    assert next_state.card(resurrected_card_id).zone == Zone.BATTLEFIELD
    assert next_state.card(resurrected_card_id).battlefield_side == PLAYER_ONE_ID
    assert next_state.current_player == PLAYER_TWO_ID
    assert isinstance(events[-1], MedicResolvedEvent)
    assert events[-1].resurrected_card_instance_id == resurrected_card_id


def test_medic_resurrected_card_resolves_its_own_on_play_effects_after_choice_resolution() -> None:
    card_registry = CARD_REGISTRY
    medic_card_id = CardInstanceId("p1_field_surgeon")
    discard_muster_card_id = CardInstanceId("p1_discard_warband_fighter")
    deck_muster_first_id = CardInstanceId("p1_deck_warband_first")
    deck_muster_second_id = CardInstanceId("p1_deck_warband_second")
    remaining_deck_card_id = CardInstanceId("p1_deck_agile_outrider")
    reserve_opponent_card_id = CardInstanceId("p2_reserve_vanguard")
    state = (
        scenario("medic_resurrected_card_resolves_own_on_play_effects")
        .player(
            PLAYER_ONE_ID,
            hand=[card(medic_card_id, "scoiatael_havekar_healer")],
            deck=[
                card(deck_muster_first_id, "scoiatael_dwarven_skirmisher"),
                card(deck_muster_second_id, "scoiatael_dwarven_skirmisher"),
                card(remaining_deck_card_id, "scoiatael_barclay_els"),
            ],
            discard=[card(discard_muster_card_id, "scoiatael_dwarven_skirmisher")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card(reserve_opponent_card_id, "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    pending_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=medic_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )
    assert pending_state.pending_choice is not None

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(discard_muster_card_id,),
        ),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (medic_card_id,)
    assert next_state.player(PLAYER_ONE_ID).rows.close == (
        discard_muster_card_id,
        deck_muster_first_id,
        deck_muster_second_id,
    )
    assert next_state.player(PLAYER_ONE_ID).deck == (remaining_deck_card_id,)
    resolved_muster_events = [
        event
        for event in events
        if isinstance(event, MusterResolvedEvent)
        and event.card_instance_id == discard_muster_card_id
    ]
    assert resolved_muster_events[0].mustered_card_instance_ids == (
        deck_muster_first_id,
        deck_muster_second_id,
    )


def test_medic_without_discard_target_is_played_without_resurrection() -> None:
    medic_id = CardInstanceId("p1_medic")
    state = (
        scenario("medic_without_discard_target")
        .player(PLAYER_ONE_ID, hand=[card(medic_id, "scoiatael_havekar_healer")])
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=medic_id, target_row=Row.RANGED),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (medic_id,)
    assert next_state.current_player == PLAYER_TWO_ID
    assert isinstance(events[-1], MedicResolvedEvent)
    assert events[-1].resurrected_card_instance_id is None


def test_resurrected_medic_waits_for_player_choice_even_with_empty_hand() -> None:
    hand_medic_id = CardInstanceId("p1_hand_medic")
    discard_medic_id = CardInstanceId("p1_discard_medic")
    first_unit_id = CardInstanceId("p1_first_unit")
    chosen_unit_id = CardInstanceId("p1_chosen_unit")
    state = (
        scenario("resurrected_medic_player_choice")
        .player(
            PLAYER_ONE_ID,
            hand=[card(hand_medic_id, "scoiatael_havekar_healer")],
            discard=[
                card(discard_medic_id, "scoiatael_havekar_healer"),
                card(first_unit_id, "scoiatael_mahakaman_defender"),
                card(chosen_unit_id, "scoiatael_dol_blathanna_archer"),
            ],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    first_choice_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=hand_medic_id,
            target_row=Row.RANGED,
        ),
        card_registry=CARD_REGISTRY,
    )
    assert first_choice_state.pending_choice is not None
    nested_choice_state, first_events = apply_action(
        first_choice_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=first_choice_state.pending_choice.choice_id,
            selected_card_instance_ids=(discard_medic_id,),
        ),
        card_registry=CARD_REGISTRY,
    )

    nested_choice = nested_choice_state.pending_choice
    assert nested_choice is not None
    assert nested_choice.source_card_instance_id == discard_medic_id
    assert nested_choice_state.card(discard_medic_id).zone == Zone.BATTLEFIELD
    assert nested_choice_state.player(PLAYER_ONE_ID).hand == ()
    assert nested_choice_state.current_player == PLAYER_ONE_ID
    assert nested_choice.legal_target_card_instance_ids == (first_unit_id, chosen_unit_id)
    assert not any(
        isinstance(event, MedicResolvedEvent) and event.card_instance_id == discard_medic_id
        for event in first_events
    )

    next_state, final_events = apply_action(
        nested_choice_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=nested_choice.choice_id,
            selected_card_instance_ids=(chosen_unit_id,),
        ),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).discard == (first_unit_id,)
    assert next_state.card(first_unit_id).zone == Zone.DISCARD
    assert next_state.card(chosen_unit_id).zone == Zone.BATTLEFIELD
    assert next_state.current_player == PLAYER_TWO_ID
    assert isinstance(final_events[-1], MedicResolvedEvent)
    assert final_events[-1].card_instance_id == discard_medic_id
    assert final_events[-1].resurrected_card_instance_id == chosen_unit_id
