import pytest
from gwent_engine.core import FactionId
from gwent_engine.core.actions import ResolveChoiceAction, UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action

from tests.engine.leaders.support import LEADER_RESERVE_CARD_ID, leader_scenario
from tests.engine.scenario_builder import card
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
    MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID,
    NILFGAARD_RELENTLESS_LEADER_ID,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_discard_and_choose_from_deck_leader_resolves_through_pending_choice() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    discarded_griffin = card("p1_hand_griffin_to_discard", "monsters_griffin")
    discarded_ghoul = card("p1_hand_ghoul_to_discard", "monsters_ghoul")
    kept_gargoyle = card("p1_hand_gargoyle_to_keep", "monsters_gargoyle")
    chosen_foglet = card("p1_deck_foglet_to_draw", "monsters_foglet")
    reserve_griffin = card("p1_deck_reserve_griffin", "monsters_griffin")
    state = (
        leader_scenario("discard_and_choose_from_deck_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
            hand=(discarded_griffin, discarded_ghoul, kept_gargoyle),
            deck=(chosen_foglet, reserve_griffin),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, pending_events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_events == ()
    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        CardInstanceId(discarded_griffin.instance_id),
        CardInstanceId(discarded_ghoul.instance_id),
        CardInstanceId(kept_gargoyle.instance_id),
        CardInstanceId(chosen_foglet.instance_id),
        CardInstanceId(reserve_griffin.instance_id),
    )
    assert pending_state.pending_choice.min_selections == 3
    assert pending_state.pending_choice.max_selections == 3
    assert pending_state.player(PLAYER_ONE_ID).leader.used is False

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(
                CardInstanceId(discarded_griffin.instance_id),
                CardInstanceId(discarded_ghoul.instance_id),
                CardInstanceId(chosen_foglet.instance_id),
            ),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).hand == (
        CardInstanceId(kept_gargoyle.instance_id),
        CardInstanceId(chosen_foglet.instance_id),
    )
    assert next_state.player(PLAYER_ONE_ID).deck == (CardInstanceId(reserve_griffin.instance_id),)
    assert next_state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId(discarded_griffin.instance_id),
        CardInstanceId(discarded_ghoul.instance_id),
    )
    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == (
        CardInstanceId(discarded_griffin.instance_id),
        CardInstanceId(discarded_ghoul.instance_id),
    )
    assert leader_event.drawn_card_instance_ids == (CardInstanceId(chosen_foglet.instance_id),)


def test_discard_and_choose_from_deck_leader_consumes_as_noop_without_discard_target() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    only_deck_card = card("p1_deck_foglet_without_discard_target", "monsters_foglet")
    state = (
        leader_scenario("discard_and_choose_no_discard_target")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
            deck=(only_deck_card,),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert next_state.player(PLAYER_ONE_ID).hand == (LEADER_RESERVE_CARD_ID,)
    assert next_state.player(PLAYER_ONE_ID).deck == (CardInstanceId(only_deck_card.instance_id),)
    assert next_state.player(PLAYER_ONE_ID).discard == ()
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == ()
    assert leader_event.drawn_card_instance_ids == ()


def test_discard_and_choose_from_deck_leader_rejects_wrong_zone_composition() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    first_discarded = card("p1_hand_griffin_pending_discard", "monsters_griffin")
    second_discarded = card("p1_hand_ghoul_pending_discard", "monsters_ghoul")
    kept_hand = card("p1_hand_gargoyle_pending_keep", "monsters_gargoyle")
    first_deck = card("p1_deck_foglet_pending_pick", "monsters_foglet")
    second_deck = card("p1_deck_griffin_pending_reserve", "monsters_griffin")
    state = (
        leader_scenario("discard_and_choose_wrong_zone_composition")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
            hand=(first_discarded, second_discarded, kept_hand),
            deck=(first_deck, second_deck),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_state.pending_choice is not None

    with pytest.raises(
        IllegalActionError,
        match=r"Leader requires the configured number of hand discards\.",
    ):
        _ = apply_action(
            pending_state,
            ResolveChoiceAction(
                player_id=PLAYER_ONE_ID,
                choice_id=pending_state.pending_choice.choice_id,
                selected_card_instance_ids=(
                    CardInstanceId(first_discarded.instance_id),
                    CardInstanceId(first_deck.instance_id),
                    CardInstanceId(second_deck.instance_id),
                ),
            ),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


def test_return_card_from_own_discard_to_hand_leader_moves_selected_card() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    target_card = card("p1_discard_gargoyle_to_return", "monsters_gargoyle")
    state = (
        leader_scenario("return_card_from_own_discard")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID,
            discard=(target_card,),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, pending_events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_events == ()
    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        CardInstanceId(target_card.instance_id),
    )
    assert pending_state.player(PLAYER_ONE_ID).leader.used is False

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(CardInstanceId(target_card.instance_id),),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).hand == (
        LEADER_RESERVE_CARD_ID,
        CardInstanceId(target_card.instance_id),
    )
    assert next_state.player(PLAYER_ONE_ID).discard == ()
    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.returned_card_instance_ids == (CardInstanceId(target_card.instance_id),)


def test_return_card_from_own_discard_to_hand_leader_excludes_hero_targets() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero_card = card("p1_discard_geralt_illegal_return", "neutral_geralt")
    unit_card = card("p1_discard_catapult_legal_return", "northern_realms_catapult")
    state = (
        leader_scenario("return_leader_excludes_hero")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID,
            discard=(hero_card, unit_card),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        CardInstanceId(unit_card.instance_id),
    )


def test_return_leader_consumes_as_noop_when_only_hero_exists() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero_card = card("p1_discard_geralt_only_return", "neutral_geralt")
    state = (
        leader_scenario("return_leader_noop_with_only_hero")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID,
            discard=(hero_card,),
        )
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert next_state.player(PLAYER_ONE_ID).hand == (LEADER_RESERVE_CARD_ID,)
    assert next_state.player(PLAYER_ONE_ID).discard == (CardInstanceId(hero_card.instance_id),)
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in events)


def test_take_card_from_opponent_discard_to_hand_leader_transfers_ownership() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    stolen_card = card(
        "p2_discard_vanguard_to_steal",
        "scoiatael_mahakaman_defender",
        owner=PLAYER_TWO_ID,
    )
    state = (
        leader_scenario("take_card_from_opponent_discard")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RELENTLESS_LEADER_ID,
        )
        .player(PLAYER_TWO_ID, discard=(stolen_card,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, pending_events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_events == ()
    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        CardInstanceId(stolen_card.instance_id),
    )
    assert pending_state.player(PLAYER_ONE_ID).leader.used is False

    next_state, _events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(CardInstanceId(stolen_card.instance_id),),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).hand == (
        LEADER_RESERVE_CARD_ID,
        CardInstanceId(stolen_card.instance_id),
    )
    assert next_state.player(PLAYER_TWO_ID).discard == ()
    assert next_state.card(CardInstanceId(stolen_card.instance_id)).owner == PLAYER_ONE_ID
    assert next_state.player(PLAYER_ONE_ID).leader.used is True


def test_take_card_from_opponent_discard_to_hand_leader_excludes_hero_targets() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero_card = card("p2_discard_geralt_illegal_steal", "neutral_geralt", owner=PLAYER_TWO_ID)
    unit_card = card(
        "p2_discard_catapult_legal_steal",
        "northern_realms_catapult",
        owner=PLAYER_TWO_ID,
    )
    state = (
        leader_scenario("take_discard_leader_excludes_hero")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RELENTLESS_LEADER_ID,
        )
        .player(PLAYER_TWO_ID, discard=(hero_card, unit_card))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    pending_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert pending_state.pending_choice is not None
    assert pending_state.pending_choice.legal_target_card_instance_ids == (
        CardInstanceId(unit_card.instance_id),
    )


def test_take_discard_leader_consumes_as_noop_when_only_hero_exists() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero_card = card("p2_discard_geralt_only_steal", "neutral_geralt", owner=PLAYER_TWO_ID)
    state = (
        leader_scenario("take_discard_leader_noop_with_only_hero")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RELENTLESS_LEADER_ID,
        )
        .player(PLAYER_TWO_ID, discard=(hero_card,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.pending_choice is None
    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert next_state.player(PLAYER_ONE_ID).hand == (LEADER_RESERVE_CARD_ID,)
    assert next_state.player(PLAYER_TWO_ID).discard == (CardInstanceId(hero_card.instance_id),)
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in events)
