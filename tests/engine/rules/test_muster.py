from gwent_engine.core import Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import MusterResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from ..scenario_builder import card, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
)


def test_muster_pulls_matching_cards_from_deck_in_deck_order_without_duplication() -> None:
    card_registry = CARD_REGISTRY
    hand_muster_card_id = CardInstanceId("p1_hand_warband_fighter")
    deck_muster_first_id = CardInstanceId("p1_deck_warband_first")
    deck_generic_archer_id = CardInstanceId("p1_deck_generic_archer")
    deck_muster_second_id = CardInstanceId("p1_deck_warband_second")
    state = (
        scenario("muster_pulls_matching_cards")
        .player(
            PLAYER_ONE_ID,
            hand=(card(hand_muster_card_id, "scoiatael_dwarven_skirmisher"),),
            deck=(
                card(deck_muster_first_id, "scoiatael_dwarven_skirmisher"),
                card(deck_generic_archer_id, "scoiatael_dol_blathanna_archer"),
                card(deck_muster_second_id, "scoiatael_dwarven_skirmisher"),
            ),
        )
        .player(
            "p2",
            hand=(card("p2_reserve_vanguard", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=hand_muster_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (
        hand_muster_card_id,
        deck_muster_first_id,
        deck_muster_second_id,
    )
    assert next_state.player(PLAYER_ONE_ID).deck == (deck_generic_archer_id,)
    assert len(set(next_state.player(PLAYER_ONE_ID).rows.close)) == 3

    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == hand_muster_card_id
    )
    assert resolved_event.mustered_card_instance_ids == (
        deck_muster_first_id,
        deck_muster_second_id,
    )


def test_muster_with_no_matching_cards_leaves_deck_unchanged_and_emits_empty_resolution() -> None:
    card_registry = CARD_REGISTRY
    lone_muster_card_id = CardInstanceId("p1_lone_ghoul_muster_unit")
    deck_generic_archer_id = CardInstanceId("p1_generic_archer_without_muster")
    state = (
        scenario("muster_without_matches")
        .player(
            PLAYER_ONE_ID,
            hand=(card(lone_muster_card_id, "monsters_ghoul"),),
            deck=(card(deck_generic_archer_id, "scoiatael_dol_blathanna_archer"),),
        )
        .player(
            "p2",
            hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=lone_muster_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (lone_muster_card_id,)
    assert next_state.player(PLAYER_ONE_ID).deck == (deck_generic_archer_id,)
    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == lone_muster_card_id
    )
    assert resolved_event.mustered_card_instance_ids == ()


def test_one_way_muster_trigger_pulls_member_cards_from_deck() -> None:
    card_registry = CARD_REGISTRY
    cerys_id = CardInstanceId("p1_cerys")
    maiden_a_id = CardInstanceId("p1_shield_maiden_a")
    maiden_b_id = CardInstanceId("p1_shield_maiden_b")
    state = (
        scenario("one_way_muster_trigger")
        .player(
            PLAYER_ONE_ID,
            hand=(card(cerys_id, "skellige_cerys"),),
            deck=(
                card(maiden_a_id, "skellige_clan_drummond_shield_maiden"),
                card(maiden_b_id, "skellige_clan_drummond_shield_maiden"),
            ),
        )
        .player(
            "p2",
            hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=cerys_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (cerys_id, maiden_a_id, maiden_b_id)
    assert next_state.player(PLAYER_ONE_ID).deck == ()
    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == cerys_id
    )
    assert resolved_event.mustered_card_instance_ids == (maiden_a_id, maiden_b_id)


def test_one_way_muster_members_do_not_self_trigger() -> None:
    card_registry = CARD_REGISTRY
    maiden_id = CardInstanceId("p1_shield_maiden_hand")
    deck_maiden_id = CardInstanceId("p1_shield_maiden_deck")
    state = (
        scenario("one_way_muster_member_does_not_self_trigger")
        .player(
            PLAYER_ONE_ID,
            hand=(card(maiden_id, "skellige_clan_drummond_shield_maiden"),),
            deck=(card(deck_maiden_id, "skellige_clan_drummond_shield_maiden"),),
        )
        .player(
            "p2",
            hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),),
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=maiden_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (maiden_id,)
    assert next_state.player(PLAYER_ONE_ID).deck == (deck_maiden_id,)
    assert all(
        not isinstance(event, MusterResolvedEvent) or event.card_instance_id != maiden_id
        for event in events
    )
