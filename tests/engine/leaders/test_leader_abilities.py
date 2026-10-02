from dataclasses import replace

from gwent_engine.core import FactionId, LeaderAbilityKind
from gwent_engine.core.actions import StartGameAction, UseLeaderAbilityAction
from gwent_engine.core.events import LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.leaders.support import leader_scenario
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_REVEAL_HAND_LEADER_ID,
    SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID,
    SCOIATAEL_DECK_ID,
    SCOIATAEL_LEADER_PASSIVES_DECK_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    SKELLIGE_SHUFFLE_DISCARDS_LEADER_ID,
    build_sample_game_state,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID, IdentityRandom


def test_players_have_exactly_one_face_up_leader_state_separate_from_card_zones() -> None:
    state = scenario("leaders_are_face_up_state").build()

    assert state.players[0].leader.leader_id == SCOIATAEL_RANGED_HORN_LEADER_ID
    assert state.players[1].leader.leader_id == SCOIATAEL_RANGED_HORN_LEADER_ID
    assert SCOIATAEL_RANGED_HORN_LEADER_ID not in state.players[0].all_card_ids()
    assert SCOIATAEL_RANGED_HORN_LEADER_ID not in state.players[1].all_card_ids()


def test_reveal_random_opponent_hand_cards_leader_is_deterministic() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    opponent_hand = (
        card("p2_hand_vanguard_reveal_one", "scoiatael_mahakaman_defender"),
        card("p2_hand_archer_reveal_two", "scoiatael_dol_blathanna_archer"),
        card("p2_hand_ballista_reveal_three", "northern_realms_ballista"),
        card("p2_hand_skirmisher_reveal_four", "scoiatael_vrihedd_brigade_recruit"),
    )
    state = (
        leader_scenario("reveal_random_opponent_hand_cards")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_REVEAL_HAND_LEADER_ID,
        )
        .player(PLAYER_TWO_ID, hand=opponent_hand)
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    _, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=IdentityRandom(),
    )

    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.revealed_card_instance_ids == tuple(
        CardInstanceId(card_spec.instance_id) for card_spec in opponent_hand[:3]
    )


def test_shuffle_all_discards_into_decks_leader_moves_both_discards_back_into_decks() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    player_one_deck_card = card("p1_existing_deck_griffin", "monsters_griffin")
    player_one_discard_card = card("p1_discard_ghoul_to_shuffle", "monsters_ghoul")
    player_two_deck_card = card("p2_existing_deck_archer", "scoiatael_dol_blathanna_archer")
    player_two_discard_card = card("p2_discard_ballista_to_shuffle", "northern_realms_ballista")
    state = (
        leader_scenario("shuffle_all_discards_into_decks")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_SHUFFLE_DISCARDS_LEADER_ID,
            deck=(player_one_deck_card,),
            discard=(player_one_discard_card,),
        )
        .player(
            PLAYER_TWO_ID,
            deck=(player_two_deck_card,),
            discard=(player_two_discard_card,),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=IdentityRandom(),
    )

    assert next_state.player(PLAYER_ONE_ID).deck == (
        CardInstanceId(player_one_deck_card.instance_id),
        CardInstanceId(player_one_discard_card.instance_id),
    )
    assert next_state.player(PLAYER_TWO_ID).deck == (
        CardInstanceId(player_two_deck_card.instance_id),
        CardInstanceId(player_two_discard_card.instance_id),
    )
    assert next_state.player(PLAYER_ONE_ID).discard == ()
    assert next_state.player(PLAYER_TWO_ID).discard == ()
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.shuffled_card_instance_ids == (
        CardInstanceId(player_one_discard_card.instance_id),
        CardInstanceId(player_two_discard_card.instance_id),
    )


def test_daisy_of_the_valley_draws_extra_opening_card_when_not_disabled() -> None:
    leader_registry = LEADER_REGISTRY
    base_state = build_sample_game_state(
        player_one_deck_id=SCOIATAEL_LEADER_PASSIVES_DECK_ID,
        player_two_deck_id=SCOIATAEL_DECK_ID,
    )
    state = replace(
        base_state,
        players=(
            replace(
                base_state.player(PLAYER_ONE_ID),
                leader=replace(
                    base_state.player(PLAYER_ONE_ID).leader,
                    leader_id=SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID,
                ),
            ),
            base_state.player(PLAYER_TWO_ID),
        ),
    )

    next_state, events = apply_action(
        state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=IdentityRandom(),
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.leader_id == (
        SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID
    )
    assert len(next_state.player(PLAYER_ONE_ID).hand) == 11
    assert len(next_state.player(PLAYER_ONE_ID).deck) == len(state.player(PLAYER_ONE_ID).deck) - 11
    assert any(
        isinstance(event, LeaderAbilityResolvedEvent)
        and event.player_id == PLAYER_ONE_ID
        and event.ability_kind == LeaderAbilityKind.DRAW_EXTRA_OPENING_CARD
        for event in events
    )
