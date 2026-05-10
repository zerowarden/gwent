from gwent_engine.core import Phase, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import CardsMovedToDiscardEvent, RoundEndedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.round_resolution import determine_round_outcome
from gwent_engine.rules.scoring import calculate_player_score, calculate_row_score

from tests.engine.primitives import PLAYER_ONE_ID, PLAYER_TWO_ID
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    NILFGAARD_DECK_ID,
    SCOIATAEL_DECK_ID,
    build_in_round_game_state,
    first_hand_unit_for_row,
)


def test_row_and_total_scoring_are_correct() -> None:
    card_registry = CARD_REGISTRY
    player_one_close_card_id = CardInstanceId("p1_close_griffin")
    player_one_ranged_card_id = CardInstanceId("p1_ranged_agile_outrider")
    player_one_reserve_card_id = CardInstanceId("p1_reserve_skirmisher")
    player_two_ranged_card_id = CardInstanceId("p2_ranged_archer")
    player_two_reserve_card_id = CardInstanceId("p2_reserve_vanguard")
    state = (
        scenario("row_and_total_scoring_are_correct")
        .current_player(PLAYER_ONE_ID)
        .turn_order(starting_player=PLAYER_ONE_ID, round_starter=PLAYER_ONE_ID)
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(player_one_close_card_id, "monsters_griffin"),
                card(player_one_ranged_card_id, "scoiatael_barclay_els"),
                card(player_one_reserve_card_id, "scoiatael_vrihedd_brigade_recruit"),
            ],
        )
        .player(
            PLAYER_TWO_ID,
            hand=[
                card(player_two_ranged_card_id, "scoiatael_dol_blathanna_archer"),
                card(player_two_reserve_card_id, "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=player_one_close_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_TWO_ID,
            card_instance_id=player_two_ranged_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=player_one_ranged_card_id,
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
    )

    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.CLOSE) == 5
    assert calculate_row_score(state, card_registry, PLAYER_ONE_ID, Row.RANGED) == 6
    assert calculate_row_score(state, card_registry, PLAYER_TWO_ID, Row.RANGED) == 4
    assert calculate_player_score(state, card_registry, PLAYER_ONE_ID).total == 11
    assert calculate_player_score(state, card_registry, PLAYER_TWO_ID).total == 4


def test_round_winner_is_computed_correctly() -> None:
    card_registry = CARD_REGISTRY
    player_one_close_card_id = CardInstanceId("p1_close_griffin")
    player_two_reserve_card_id = CardInstanceId("p2_reserve_vanguard")
    state = (
        scenario("round_winner_is_computed_correctly")
        .current_player(PLAYER_ONE_ID)
        .turn_order(starting_player=PLAYER_ONE_ID, round_starter=PLAYER_ONE_ID)
        .player(PLAYER_ONE_ID, hand=[card(player_one_close_card_id, "monsters_griffin")])
        .player(
            PLAYER_TWO_ID,
            hand=[card(player_two_reserve_card_id, "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=player_one_close_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    outcome = determine_round_outcome(state, card_registry)

    assert outcome.winner == PLAYER_ONE_ID
    assert outcome.loser == PLAYER_TWO_ID


def test_board_moves_to_discard_and_next_round_starts_cleanly() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=NILFGAARD_DECK_ID,
    )
    played_card = first_hand_unit_for_row(state, card_registry, PlayerId("p1"), Row.CLOSE)
    state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PlayerId("p1"),
            card_instance_id=played_card,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )
    state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p2")),
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
        card_registry=card_registry,
    )

    player_one = next_state.player(PlayerId("p1"))
    player_two = next_state.player(PlayerId("p2"))
    assert next_state.phase == Phase.IN_ROUND
    assert next_state.round_number == 2
    assert next_state.current_player == PlayerId("p1")
    assert player_one.rows.all_cards() == ()
    assert player_two.rows.all_cards() == ()
    assert played_card in player_one.discard
    assert next_state.card(played_card).zone == Zone.DISCARD
    assert next_state.card(played_card).row is None
    assert player_one.has_passed is False
    assert player_two.has_passed is False
    assert isinstance(events[2], CardsMovedToDiscardEvent)
    assert events[2].card_instance_ids == (played_card,)


def test_draw_removes_one_gem_from_both_players() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=SCOIATAEL_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    state, _ = apply_action(state, PassAction(player_id=PlayerId("p1")))

    next_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
    )

    assert next_state.player(PlayerId("p1")).gems_remaining == 1
    assert next_state.player(PlayerId("p2")).gems_remaining == 1
    assert isinstance(events[1], RoundEndedEvent)
    assert events[1].winner is None


def test_playing_last_card_triggers_round_ended_event_automatically() -> None:
    card_registry = CARD_REGISTRY
    final_card_id = CardInstanceId("p1_final_card")
    state = (
        scenario("playing_last_card_triggers_round_end")
        .current_player(PLAYER_ONE_ID)
        .turn_order(starting_player=PLAYER_ONE_ID, round_starter=PLAYER_ONE_ID)
        .player(PLAYER_ONE_ID, hand=[card(final_card_id, "scoiatael_mahakaman_defender")])
        .player(PLAYER_TWO_ID, hand=[])
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=final_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    round_end = next(event for event in events if isinstance(event, RoundEndedEvent))

    assert round_end.round_number == 1
    assert round_end.winner == PLAYER_ONE_ID
    assert next_state.round_number == 2
