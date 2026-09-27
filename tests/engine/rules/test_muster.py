from gwent_engine.core import Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import MusterResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_row_score

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
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


def test_muster_plays_matching_cards_from_hand_and_deck() -> None:
    played_id = CardInstanceId("p1_crone_brewess")
    hand_match_id = CardInstanceId("p1_crone_weavess")
    hand_unrelated_id = CardInstanceId("p1_ghoul")
    deck_match_id = CardInstanceId("p1_crone_whispess")
    deck_unrelated_id = CardInstanceId("p1_arachas")
    opponent_match_id = CardInstanceId("p2_crone_weavess")
    state = (
        scenario("muster_from_hand_and_deck")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(played_id, "monsters_crone_brewess"),
                card(hand_match_id, "monsters_crone_weavess"),
                card(hand_unrelated_id, "monsters_ghoul"),
            ),
            deck=(
                card(deck_match_id, "monsters_crone_whispess"),
                card(deck_unrelated_id, "monsters_arachas"),
            ),
        )
        .player("p2", hand=(card(opponent_match_id, "monsters_crone_weavess"),))
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=played_id, target_row=Row.CLOSE),
        card_registry=CARD_REGISTRY,
    )

    player = next_state.player(PLAYER_ONE_ID)
    assert player.hand == (hand_unrelated_id,)
    assert player.deck == (deck_unrelated_id,)
    assert player.rows.close == (played_id, hand_match_id, deck_match_id)
    assert next_state.player(PLAYER_TWO_ID).hand == (opponent_match_id,)
    assert next_state.card(hand_match_id).zone == Zone.BATTLEFIELD
    assert next_state.card(deck_match_id).zone == Zone.BATTLEFIELD
    assert next_state.card(hand_match_id).battlefield_side == PLAYER_ONE_ID
    assert next_state.card(deck_match_id).battlefield_side == PLAYER_ONE_ID
    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == played_id
    )
    assert resolved_event.mustered_card_instance_ids == (hand_match_id, deck_match_id)


def test_muster_plays_all_matching_cards_already_in_hand() -> None:
    played_id = CardInstanceId("p1_crone_brewess")
    match_one_id = CardInstanceId("p1_crone_weavess")
    match_two_id = CardInstanceId("p1_crone_whispess")
    state = (
        scenario("muster_all_crones_in_hand")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(played_id, "monsters_crone_brewess"),
                card(match_one_id, "monsters_crone_weavess"),
                card(match_two_id, "monsters_crone_whispess"),
            ),
        )
        .player("p2", hand=(card("p2_reserve_defender", "scoiatael_mahakaman_defender"),))
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=played_id, target_row=Row.CLOSE),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).hand == ()
    assert next_state.player(PLAYER_ONE_ID).rows.close == (played_id, match_one_id, match_two_id)
    assert len(set(next_state.player(PLAYER_ONE_ID).rows.close)) == 3
    resolved_events = [event for event in events if isinstance(event, MusterResolvedEvent)]
    assert next(
        event.mustered_card_instance_ids
        for event in resolved_events
        if event.card_instance_id == played_id
    ) == (match_one_id, match_two_id)
    assert all(
        not event.mustered_card_instance_ids
        for event in resolved_events
        if event.card_instance_id != played_id
    )


def test_light_longship_musters_into_ranged_row_at_four_strength_each() -> None:
    played_id = CardInstanceId("p1_played_light_longship")
    hand_match_id = CardInstanceId("p1_hand_light_longship")
    deck_match_id = CardInstanceId("p1_deck_light_longship")
    state = (
        scenario("light_longship_ranged_muster")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(played_id, "skellige_light_longship"),
                card(hand_match_id, "skellige_light_longship"),
            ],
            deck=[card(deck_match_id, "skellige_light_longship")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=played_id, target_row=Row.RANGED),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        played_id,
        hand_match_id,
        deck_match_id,
    )
    assert next_state.player(PLAYER_ONE_ID).rows.siege == ()
    assert calculate_row_score(next_state, CARD_REGISTRY, PLAYER_ONE_ID, Row.RANGED) == 12


def test_light_longship_is_reduced_by_ranged_weather() -> None:
    state = (
        scenario("light_longship_under_fog")
        .player(
            PLAYER_ONE_ID,
            board=rows(ranged=[card("p1_light_longship", "skellige_light_longship")]),
        )
        .weather(rows(ranged=[card("fog", "neutral_impenetrable_fog")]))
        .build()
    )

    assert calculate_row_score(state, CARD_REGISTRY, PLAYER_ONE_ID, Row.RANGED) == 1


def test_gaunter_musters_darkness_cards_from_hand_and_deck() -> None:
    gaunter_id = CardInstanceId("p1_gaunter")
    hand_darkness_id = CardInstanceId("p1_hand_darkness")
    deck_darkness_id = CardInstanceId("p1_deck_darkness")
    state = (
        scenario("gaunter_musters_darkness")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(gaunter_id, "neutral_gaunter_o_dimm"),
                card(hand_darkness_id, "neutral_gaunter_darkness"),
            ],
            deck=[card(deck_darkness_id, "neutral_gaunter_darkness")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=gaunter_id, target_row=Row.SIEGE),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.siege == (gaunter_id,)
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        hand_darkness_id,
        deck_darkness_id,
    )
    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == gaunter_id
    )
    assert resolved_event.mustered_card_instance_ids == (hand_darkness_id, deck_darkness_id)


def test_darkness_musters_other_darkness_but_not_gaunter() -> None:
    played_id = CardInstanceId("p1_played_darkness")
    hand_match_id = CardInstanceId("p1_hand_darkness")
    deck_match_id = CardInstanceId("p1_deck_darkness")
    gaunter_id = CardInstanceId("p1_deck_gaunter")
    state = (
        scenario("darkness_does_not_muster_gaunter")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(played_id, "neutral_gaunter_darkness"),
                card(hand_match_id, "neutral_gaunter_darkness"),
            ],
            deck=[
                card(gaunter_id, "neutral_gaunter_o_dimm"),
                card(deck_match_id, "neutral_gaunter_darkness"),
            ],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=played_id, target_row=Row.RANGED),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        played_id,
        hand_match_id,
        deck_match_id,
    )
    assert next_state.player(PLAYER_ONE_ID).deck == (gaunter_id,)
    resolved_event = next(
        event
        for event in events
        if isinstance(event, MusterResolvedEvent) and event.card_instance_id == played_id
    )
    assert resolved_event.mustered_card_instance_ids == (hand_match_id, deck_match_id)


def test_vampire_katakan_has_five_strength_within_muster_package() -> None:
    katakan_id = CardInstanceId("p1_katakan")
    bruxa_id = CardInstanceId("p1_bruxa")
    state = (
        scenario("katakan_vampire_muster_strength")
        .player(
            PLAYER_ONE_ID,
            hand=[card(katakan_id, "monsters_vampire_katakan")],
            deck=[card(bruxa_id, "monsters_vampire_bruxa")],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_reserve", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        PlayCardAction(player_id=PLAYER_ONE_ID, card_instance_id=katakan_id, target_row=Row.CLOSE),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).rows.close == (katakan_id, bruxa_id)
    assert calculate_row_score(next_state, CARD_REGISTRY, PLAYER_ONE_ID, Row.CLOSE) == 9


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


def test_one_way_muster_trigger_pulls_member_cards_from_hand_and_deck() -> None:
    card_registry = CARD_REGISTRY
    cerys_id = CardInstanceId("p1_cerys")
    maiden_a_id = CardInstanceId("p1_shield_maiden_a")
    maiden_b_id = CardInstanceId("p1_shield_maiden_b")
    state = (
        scenario("one_way_muster_trigger")
        .player(
            PLAYER_ONE_ID,
            hand=(
                card(cerys_id, "skellige_cerys"),
                card(maiden_a_id, "skellige_clan_drummond_shield_maiden"),
            ),
            deck=(card(maiden_b_id, "skellige_clan_drummond_shield_maiden"),),
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
    assert next_state.player(PLAYER_ONE_ID).hand == ()
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
