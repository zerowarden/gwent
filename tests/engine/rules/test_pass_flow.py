from dataclasses import replace

import pytest
from gwent_engine.core import Phase, Row
from gwent_engine.core.actions import PassAction, PlayCardAction, UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import (
    LeaderAbilityResolvedEvent,
    NextRoundStartedEvent,
    PlayerPassedEvent,
    RoundEndedEvent,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_ANY_WEATHER_LEADER_ID,
    MONSTERS_DOUBLE_SPY_LEADER_ID,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_DECK_ID,
    build_in_round_game_state,
)


def test_pass_turn_advances_to_opponent_and_opponent_may_keep_playing() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))

    passed_state, events = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )

    assert passed_state.player(PlayerId("p1")).has_passed is True
    assert passed_state.current_player == PlayerId("p2")
    assert passed_state.phase == Phase.IN_ROUND
    assert isinstance(events[0], PlayerPassedEvent)

    player_two_card = passed_state.player(PlayerId("p2")).hand[0]
    next_state, _ = apply_action(
        passed_state,
        PlayCardAction(
            player_id=PlayerId("p2"),
            card_instance_id=player_two_card,
            target_row=Row.CLOSE,
        ),
        card_registry=card_registry,
    )

    assert next_state.current_player == PlayerId("p2")


def test_passed_player_cannot_act_again() -> None:
    state, card_registry = build_in_round_game_state(starting_player=PlayerId("p1"))
    passed_state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )
    player_one_card = state.player(PlayerId("p1")).hand[0]

    with pytest.raises(IllegalActionError, match="Passed players cannot act again"):
        _ = apply_action(
            passed_state,
            PlayCardAction(
                player_id=PlayerId("p1"),
                card_instance_id=player_one_card,
                target_row=Row.CLOSE,
            ),
            card_registry=card_registry,
        )


def test_two_passes_resolve_round_and_start_next_round() -> None:
    state, card_registry = build_in_round_game_state(
        starting_player=PlayerId("p1"),
        player_one_deck_id=SCOIATAEL_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    first_pass_state, _ = apply_action(
        state,
        PassAction(player_id=PlayerId("p1")),
    )

    final_state, events = apply_action(
        first_pass_state,
        PassAction(player_id=PlayerId("p2")),
        card_registry=card_registry,
    )

    assert final_state.phase == Phase.IN_ROUND
    assert final_state.current_player == PlayerId("p1")
    assert isinstance(events[1], RoundEndedEvent)
    assert isinstance(events[3], NextRoundStartedEvent)


def test_empty_handed_player_with_unused_active_leader_can_still_use_it() -> None:
    state = (
        scenario("empty_hand_with_unused_active_leader")
        .player(
            PLAYER_ONE_ID,
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_first_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in events)

    # The empty-handed player may also decline and pass while the leader is available.
    passed_state, _ = apply_action(
        state,
        PassAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assert passed_state.player(PLAYER_ONE_ID).has_passed is True


def test_empty_handed_player_with_used_leader_is_done_for_the_round() -> None:
    state = (
        scenario("empty_hand_with_used_leader")
        .player(
            PLAYER_ONE_ID,
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            leader_used=True,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_first_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    for action in (
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        PassAction(player_id=PLAYER_ONE_ID),
    ):
        with pytest.raises(IllegalActionError, match="no available leader action"):
            _ = apply_action(
                state,
                action,
                card_registry=CARD_REGISTRY,
                leader_registry=LEADER_REGISTRY,
            )


def test_empty_handed_player_with_passive_leader_is_done_for_the_round() -> None:
    state = (
        scenario("empty_hand_with_passive_leader")
        .player(
            PLAYER_ONE_ID,
            faction="monsters",
            leader_id=MONSTERS_DOUBLE_SPY_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_first_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="no available leader action"):
        _ = apply_action(
            state,
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )


def test_empty_handed_player_with_disabled_leader_is_done_for_the_round() -> None:
    base_state = (
        scenario("empty_hand_with_disabled_leader")
        .player(
            PLAYER_ONE_ID,
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_first_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )
    player_one = base_state.player(PLAYER_ONE_ID)
    state = replace(
        base_state,
        players=(
            replace(player_one, leader=replace(player_one.leader, disabled=True)),
            base_state.players[1],
        ),
    )

    with pytest.raises(IllegalActionError, match="no available leader action"):
        _ = apply_action(
            state,
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )


def test_empty_handed_player_with_unavailable_leader_prerequisite_is_done() -> None:
    state = (
        scenario("empty_hand_with_unavailable_leader")
        .player(
            PLAYER_ONE_ID,
            faction="monsters",
            leader_id=MONSTERS_ANY_WEATHER_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[card("p2_first_card", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="no available leader action"):
        _ = apply_action(
            state,
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )


def test_final_card_with_opponent_passed_still_allows_leader_activation() -> None:
    final_card_id = CardInstanceId("p1_final_card")
    state = (
        scenario("final_card_then_leader")
        .player(
            PLAYER_ONE_ID,
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            hand=[card(final_card_id, "monsters_griffin")],
        )
        .player(PLAYER_TWO_ID, passed=True, hand=[card("p2_card", "scoiatael_mahakaman_defender")])
        .build()
    )

    after_play, play_events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=final_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert after_play.phase == Phase.IN_ROUND
    assert after_play.current_player == PLAYER_ONE_ID
    assert not any(isinstance(event, RoundEndedEvent) for event in play_events)

    after_leader, leader_events = apply_action(
        after_play,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert after_leader.player(PLAYER_ONE_ID).leader.used is True
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in leader_events)
    assert any(isinstance(event, RoundEndedEvent) for event in leader_events)
    assert after_leader.round_number == 2


def test_playing_last_card_gives_priority_to_opponent_with_cards() -> None:
    final_card_id = CardInstanceId("p1_final_card")
    state = (
        scenario("last_card_gives_opponent_priority")
        .player(PLAYER_ONE_ID, hand=[card(final_card_id, "monsters_griffin")])
        .player(
            PLAYER_TWO_ID,
            hand=[
                card("p2_first_card", "scoiatael_mahakaman_defender"),
                card("p2_second_card", "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )

    next_state, _ = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=final_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=CARD_REGISTRY,
    )

    assert next_state.phase == Phase.IN_ROUND
    assert next_state.current_player == PLAYER_TWO_ID
    assert next_state.player(PLAYER_ONE_ID).hand == ()


def test_play_skips_opponent_who_has_no_cards() -> None:
    first_card_id = CardInstanceId("p1_first_card")
    state = (
        scenario("skip_exhausted_opponent")
        .player(
            PLAYER_ONE_ID,
            hand=[
                card(first_card_id, "monsters_griffin"),
                card("p1_second_card", "scoiatael_mahakaman_defender"),
            ],
        )
        .player(PLAYER_TWO_ID, leader_used=True)
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=first_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert next_state.phase == Phase.IN_ROUND
    assert next_state.current_player == PLAYER_ONE_ID
    assert not any(isinstance(event, RoundEndedEvent) for event in events)


def test_passing_when_opponent_has_no_cards_resolves_round() -> None:
    state = (
        scenario("pass_against_exhausted_opponent")
        .player(PLAYER_ONE_ID, hand=[card("p1_reserve", "scoiatael_mahakaman_defender")])
        .player(PLAYER_TWO_ID, leader_used=True)
        .build()
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(isinstance(event, RoundEndedEvent) for event in events)
    assert next_state.round_number == 2
    assert next_state.current_player == PLAYER_ONE_ID


def test_round_starter_with_empty_hand_yields_priority_to_opponent() -> None:
    final_card_id = CardInstanceId("p1_round_winning_card")
    state = (
        scenario("exhausted_round_starter")
        .current_player(PLAYER_TWO_ID)
        .player(
            PLAYER_ONE_ID,
            hand=[card(final_card_id, "monsters_griffin")],
            leader_used=True,
        )
        .player(
            PLAYER_TWO_ID,
            hand=[
                card("p2_first_card", "scoiatael_mahakaman_defender"),
                card("p2_second_card", "scoiatael_mahakaman_defender"),
            ],
        )
        .build()
    )
    passed_state, _ = apply_action(state, PassAction(player_id=PLAYER_TWO_ID))

    next_state, events = apply_action(
        passed_state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=final_card_id,
            target_row=Row.CLOSE,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )

    assert any(isinstance(event, RoundEndedEvent) for event in events)
    assert next_state.phase == Phase.IN_ROUND
    assert next_state.round_number == 2
    assert next_state.round_starter == PLAYER_ONE_ID
    assert next_state.current_player == PLAYER_TWO_ID
    assert next_state.player(PLAYER_ONE_ID).hand == ()
    assert len(next_state.player(PLAYER_TWO_ID).hand) == 2
