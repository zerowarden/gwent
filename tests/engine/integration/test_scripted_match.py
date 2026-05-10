from gwent_engine.core.events import (
    CardPlayedEvent,
    CardsMovedToDiscardEvent,
    GameStartedEvent,
    MulliganPerformedEvent,
    NextRoundStartedEvent,
    PlayerPassedEvent,
    RoundEndedEvent,
    StartingPlayerChosenEvent,
)

from tests.engine.support import PLAYER_ONE_ID, PLAYER_TWO_ID, run_scripted_round


def test_deterministic_scripted_match_has_expected_events_and_final_state() -> None:
    final_state, events = run_scripted_round()
    assert len(events) == 14
    assert isinstance(events[0], StartingPlayerChosenEvent)
    assert isinstance(events[1], GameStartedEvent)
    assert isinstance(events[4], MulliganPerformedEvent)
    assert isinstance(events[5], MulliganPerformedEvent)
    assert [type(event) for event in events[6:9]] == [
        CardPlayedEvent,
        CardPlayedEvent,
        CardPlayedEvent,
    ]
    assert [type(event) for event in events[9:11]] == [PlayerPassedEvent, PlayerPassedEvent]
    assert isinstance(events[11], RoundEndedEvent)
    assert isinstance(events[12], CardsMovedToDiscardEvent)
    assert isinstance(events[13], NextRoundStartedEvent)

    round_ended_event = events[11]
    player_scores = dict(round_ended_event.player_scores)
    assert round_ended_event.winner == "p1"
    assert player_scores[PLAYER_ONE_ID] > player_scores[PLAYER_TWO_ID]

    assert final_state.phase.value == "in_round"
    assert final_state.status.value == "in_progress"
    assert final_state.round_number == 2
    assert final_state.current_player == PLAYER_ONE_ID
    assert final_state.starting_player == PLAYER_ONE_ID
    assert final_state.round_starter == PLAYER_ONE_ID
    assert final_state.match_winner is None
    assert final_state.event_counter == len(events)
    assert final_state.pending_choice is None
    assert final_state.weather.all_cards() == ()
    assert final_state.player(PLAYER_ONE_ID).round_wins == 1
    assert final_state.player(PLAYER_TWO_ID).round_wins == 0
    assert final_state.player(PLAYER_ONE_ID).rows.all_cards() == ()
    assert final_state.player(PLAYER_TWO_ID).rows.all_cards() == ()
    assert len(final_state.player(PLAYER_ONE_ID).discard) == 2
    assert len(final_state.player(PLAYER_TWO_ID).discard) == 1
