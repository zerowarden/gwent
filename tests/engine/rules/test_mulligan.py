import pytest
from gwent_engine.core import Phase
from gwent_engine.core.actions import MulliganSelection, ResolveMulligansAction, StartGameAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import MulliganPerformedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action

from tests.engine.support import IdentityShuffle, build_sample_game_state


def test_resolve_mulligans_replaces_cards_for_both_players_and_transitions_to_round() -> None:
    initial_state = build_sample_game_state()
    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p2")),
        rng=IdentityShuffle(),
    )
    player_one_deck_size_before = len(started_state.player(PlayerId("p1")).deck)
    player_two_deck_size_before = len(started_state.player(PlayerId("p2")).deck)

    player_two_replaced = started_state.player(PlayerId("p2")).hand[:2]
    player_one_replaced = (started_state.player(PlayerId("p1")).hand[0],)
    final_state, events = apply_action(
        started_state,
        ResolveMulligansAction(
            selections=(
                MulliganSelection(
                    player_id=PlayerId("p1"),
                    cards_to_replace=player_one_replaced,
                ),
                MulliganSelection(
                    player_id=PlayerId("p2"),
                    cards_to_replace=player_two_replaced,
                ),
            )
        ),
    )

    player_one_after = final_state.player(PlayerId("p1"))
    player_two_after = final_state.player(PlayerId("p2"))

    assert final_state.phase == Phase.IN_ROUND
    assert final_state.current_player == PlayerId("p2")
    assert len(player_one_after.hand) == 10
    assert len(player_two_after.hand) == 10
    assert len(player_one_after.deck) == player_one_deck_size_before
    assert len(player_two_after.deck) == player_two_deck_size_before
    assert player_one_after.discard == ()
    assert player_two_after.discard == ()
    assert player_one_after.deck[-1:] == player_one_replaced
    assert player_two_after.deck[-2:] == player_two_replaced
    assert player_one_replaced[0] not in player_one_after.hand
    assert player_two_replaced[0] not in player_two_after.hand
    assert player_two_replaced[1] not in player_two_after.hand
    assert final_state.card(player_one_replaced[0]).zone.value == "deck"
    assert final_state.card(player_two_replaced[0]).zone.value == "deck"
    assert final_state.card(player_two_replaced[1]).zone.value == "deck"
    assert events == (
        MulliganPerformedEvent(
            event_id=5,
            player_id=PlayerId("p1"),
            replaced_card_instance_ids=player_one_replaced,
            drawn_card_instance_ids=(started_state.player(PlayerId("p1")).deck[0],),
        ),
        MulliganPerformedEvent(
            event_id=6,
            player_id=PlayerId("p2"),
            replaced_card_instance_ids=player_two_replaced,
            drawn_card_instance_ids=(
                started_state.player(PlayerId("p2")).deck[0],
                started_state.player(PlayerId("p2")).deck[1],
            ),
        ),
    )
    assert final_state.event_counter == 6
    assert not hasattr(final_state, "mulliganed_players")


def test_resolve_mulligans_requires_mulligan_phase_and_both_players() -> None:
    initial_state = build_sample_game_state()

    with pytest.raises(IllegalActionError, match="MULLIGAN phase"):
        _ = apply_action(
            initial_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(player_id=PlayerId("p1"), cards_to_replace=()),
                    MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
                )
            ),
        )

    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p2")),
        rng=IdentityShuffle(),
    )

    with pytest.raises(IllegalActionError, match="one selection per player"):
        _ = apply_action(
            started_state,
            ResolveMulligansAction(selections=(MulliganSelection(player_id=PlayerId("p1")),)),
        )

    with pytest.raises(IllegalActionError, match="include both players exactly once"):
        _ = apply_action(
            started_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(player_id=PlayerId("p1")),
                    MulliganSelection(player_id=PlayerId("p1")),
                )
            ),
        )

    in_round_state, _ = apply_action(
        started_state,
        ResolveMulligansAction(
            selections=(
                MulliganSelection(player_id=PlayerId("p1"), cards_to_replace=()),
                MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
            )
        ),
    )

    with pytest.raises(IllegalActionError, match="MULLIGAN phase"):
        _ = apply_action(
            in_round_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(player_id=PlayerId("p1"), cards_to_replace=()),
                    MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
                )
            ),
        )


def test_resolve_mulligans_rejects_duplicate_or_excessive_card_selection() -> None:
    initial_state = build_sample_game_state()
    started_state, _ = apply_action(
        initial_state,
        StartGameAction(starting_player=PlayerId("p1")),
        rng=IdentityShuffle(),
    )
    player_one = started_state.player(PlayerId("p1"))
    duplicated_card_id = player_one.hand[0]

    with pytest.raises(IllegalActionError, match="same card twice"):
        _ = apply_action(
            started_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(
                        player_id=PlayerId("p1"),
                        cards_to_replace=(duplicated_card_id, duplicated_card_id),
                    ),
                    MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
                )
            ),
        )

    with pytest.raises(IllegalActionError, match="at most 2 cards per player"):
        _ = apply_action(
            started_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(
                        player_id=PlayerId("p1"),
                        cards_to_replace=player_one.hand[:3],
                    ),
                    MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
                )
            ),
        )

    with pytest.raises(IllegalActionError, match="is not in player"):
        _ = apply_action(
            started_state,
            ResolveMulligansAction(
                selections=(
                    MulliganSelection(
                        player_id=PlayerId("p1"),
                        cards_to_replace=(CardInstanceId("p1_card_16"),),
                    ),
                    MulliganSelection(player_id=PlayerId("p2"), cards_to_replace=()),
                )
            ),
        )
