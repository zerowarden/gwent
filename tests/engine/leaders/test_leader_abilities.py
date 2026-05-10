from dataclasses import replace

import pytest
from gwent_engine.core import FactionId, LeaderAbilityKind, Row, Zone
from gwent_engine.core.actions import ResolveChoiceAction, StartGameAction, UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_row_score

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_ANY_WEATHER_LEADER_ID,
    MONSTERS_DISCARD_AND_CHOOSE_LEADER_ID,
    MONSTERS_RETURN_DISCARD_TO_HAND_LEADER_ID,
    NILFGAARD_RELENTLESS_LEADER_ID,
    NILFGAARD_REVEAL_HAND_LEADER_ID,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
    SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
    SCOIATAEL_DAISY_OF_THE_VALLEY_LEADER_ID,
    SCOIATAEL_DECK_ID,
    SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
    SCOIATAEL_LEADER_PASSIVES_DECK_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    SKELLIGE_SHUFFLE_DISCARDS_LEADER_ID,
    IdentityShuffle,
    build_sample_game_state,
)


def test_players_have_exactly_one_face_up_leader_state_separate_from_card_zones() -> None:
    state = scenario("leaders_are_face_up_state").build()

    assert state.players[0].leader.leader_id == SCOIATAEL_RANGED_HORN_LEADER_ID
    assert state.players[1].leader.leader_id == SCOIATAEL_RANGED_HORN_LEADER_ID
    assert SCOIATAEL_RANGED_HORN_LEADER_ID not in state.players[0].all_card_ids()
    assert SCOIATAEL_RANGED_HORN_LEADER_ID not in state.players[1].all_card_ids()


def test_active_clear_weather_leader_consumes_turn_and_cannot_be_used_twice() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p2_biting_frost_weather", "neutral_biting_frost", owner=PLAYER_TWO_ID)
    reserve = card("p2_reserve_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    state = (
        scenario("clear_weather_leader_consumes_turn")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NORTHERN_REALMS,
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            hand=(reserve,),
        )
        .weather(rows(close=[frost]))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.used is True
    assert next_state.current_player == PLAYER_TWO_ID
    assert next_state.weather.close == ()
    assert next_state.weather.ranged == ()
    assert next_state.weather.siege == ()
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == (CardInstanceId(frost.instance_id),)

    with pytest.raises(IllegalActionError, match="at most once per battle"):
        _ = apply_action(
            replace(next_state, current_player=PLAYER_ONE_ID),
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


def test_specific_weather_from_deck_leader_auto_plays_matching_weather_card() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p1_deck_biting_frost_weather", "neutral_biting_frost")
    reserve = card("p1_deck_reserve_vanguard_unit", "scoiatael_mahakaman_defender")
    opponent_hand = card("p2_hand_reserve_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    state = (
        scenario("specific_weather_from_deck_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_FROST_FROM_DECK_LEADER_ID,
            deck=(frost, reserve),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).deck == (CardInstanceId(reserve.instance_id),)
    assert next_state.weather.close == (CardInstanceId(frost.instance_id),)
    assert next_state.card(CardInstanceId(frost.instance_id)).zone == Zone.WEATHER
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.played_card_instance_id == CardInstanceId(frost.instance_id)
    assert leader_event.affected_row == Row.CLOSE


def test_any_weather_leader_requires_explicit_choice_with_multiple_weather_cards() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    frost = card("p1_deck_biting_frost_weather", "neutral_biting_frost")
    fog = card("p1_deck_impenetrable_fog_weather", "neutral_impenetrable_fog")
    reserve = card("p1_deck_reserve_griffin_unit", "monsters_griffin")
    opponent_hand = card("p2_hand_reserve_archer_unit", "scoiatael_dol_blathanna_archer")
    state = (
        scenario("any_weather_leader_requires_choice")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_ANY_WEATHER_LEADER_ID,
            deck=(frost, fog, reserve),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    with pytest.raises(IllegalActionError, match="choose which weather card"):
        _ = apply_action(
            state,
            UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    next_state, events = apply_action(
        state,
        UseLeaderAbilityAction(
            player_id=PLAYER_ONE_ID,
            target_card_instance_id=CardInstanceId(fog.instance_id),
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).deck == (
        CardInstanceId(frost.instance_id),
        CardInstanceId(reserve.instance_id),
    )
    assert next_state.weather.ranged == (CardInstanceId(fog.instance_id),)
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.played_card_instance_id == CardInstanceId(fog.instance_id)
    assert leader_event.affected_row == Row.RANGED


def test_horn_own_row_leader_marks_leader_horn_row_and_doubles_row_score() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    ranged_archer = card("p1_ranged_archer_unit", "scoiatael_dol_blathanna_archer")
    ranged_skirmisher = card("p1_ranged_skirmisher_unit", "scoiatael_vrihedd_brigade_recruit")
    opponent_hand = card("p2_hand_reserve_vanguard_unit", "scoiatael_mahakaman_defender")
    state = (
        scenario("horn_own_row_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            board=rows(ranged=[ranged_archer, ranged_skirmisher]),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, _ = apply_action(
        state,
        UseLeaderAbilityAction(player_id=PLAYER_ONE_ID),
        card_registry=card_registry,
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_ONE_ID).leader.horn_row == Row.RANGED
    assert (
        calculate_row_score(
            next_state,
            card_registry,
            PLAYER_ONE_ID,
            Row.RANGED,
            leader_registry=leader_registry,
        )
        == 16
    )


def test_row_scorch_leader_respects_hero_immunity() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    hero = card("p2_close_hero_imlerith", "monsters_imlerith")
    first_close = card("p2_close_vanguard_alpha", "scoiatael_mahakaman_defender")
    second_close = card("p2_close_vanguard_beta", "scoiatael_mahakaman_defender")
    opponent_hand = card("p2_hand_reserve_archer_unit", "scoiatael_dol_blathanna_archer")
    state = (
        scenario("row_scorch_leader_respects_hero_immunity")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_CLOSE_SCORCH_LEADER_ID,
        )
        .player(
            PLAYER_TWO_ID,
            hand=(opponent_hand,),
            board=rows(close=[hero, first_close, second_close]),
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

    assert next_state.card(CardInstanceId(hero.instance_id)).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId(first_close.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(second_close.instance_id)).zone == Zone.DISCARD
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.discarded_card_instance_ids == (
        CardInstanceId(first_close.instance_id),
        CardInstanceId(second_close.instance_id),
    )


def test_discard_and_choose_from_deck_leader_resolves_through_pending_choice() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    discarded_griffin = card("p1_hand_griffin_to_discard", "monsters_griffin")
    discarded_ghoul = card("p1_hand_ghoul_to_discard", "monsters_ghoul")
    kept_gargoyle = card("p1_hand_gargoyle_to_keep", "monsters_gargoyle")
    chosen_foglet = card("p1_deck_foglet_to_draw", "monsters_foglet")
    reserve_griffin = card("p1_deck_reserve_griffin", "monsters_griffin")
    state = (
        scenario("discard_and_choose_from_deck_leader")
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
        scenario("discard_and_choose_no_discard_target")
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
    assert next_state.player(PLAYER_ONE_ID).hand == ()
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
        scenario("discard_and_choose_wrong_zone_composition")
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
        scenario("return_card_from_own_discard")
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

    assert next_state.player(PLAYER_ONE_ID).hand == (CardInstanceId(target_card.instance_id),)
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
        scenario("return_leader_excludes_hero")
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
        scenario("return_leader_noop_with_only_hero")
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
    assert next_state.player(PLAYER_ONE_ID).hand == ()
    assert next_state.player(PLAYER_ONE_ID).discard == (CardInstanceId(hero_card.instance_id),)
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in events)


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
        scenario("reveal_random_opponent_hand_cards")
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
        rng=IdentityShuffle(),
    )

    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.revealed_card_instance_ids == tuple(
        CardInstanceId(card_spec.instance_id) for card_spec in opponent_hand[:3]
    )


def test_take_card_from_opponent_discard_to_hand_leader_transfers_ownership() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    stolen_card = card(
        "p2_discard_vanguard_to_steal",
        "scoiatael_mahakaman_defender",
        owner=PLAYER_TWO_ID,
    )
    state = (
        scenario("take_card_from_opponent_discard")
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

    assert next_state.player(PLAYER_ONE_ID).hand == (CardInstanceId(stolen_card.instance_id),)
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
        scenario("take_discard_leader_excludes_hero")
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
        scenario("take_discard_leader_noop_with_only_hero")
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
    assert next_state.player(PLAYER_ONE_ID).hand == ()
    assert next_state.player(PLAYER_TWO_ID).discard == (CardInstanceId(hero_card.instance_id),)
    assert any(isinstance(event, LeaderAbilityResolvedEvent) for event in events)


def test_optimize_agile_rows_leader_moves_all_battlefield_agile_units_and_keeps_ties() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    moving_agile = card("p1_agile_outrider_to_optimize", "scoiatael_barclay_els")
    tied_agile = card("p2_agile_outrider_keep_current_row", "scoiatael_barclay_els")
    ranged_horn = card("p1_ranged_commanders_horn", "neutral_commanders_horn")
    opponent_hand = card("p2_hand_reserve_ballista_unit", "northern_realms_ballista")
    state = (
        scenario("optimize_agile_rows_leader")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_AGILE_OPTIMIZER_LEADER_ID,
            board=rows(close=[moving_agile], ranged=[ranged_horn]),
        )
        .player(
            PLAYER_TWO_ID,
            hand=(opponent_hand,),
            board=rows(ranged=[tied_agile]),
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

    assert next_state.card(CardInstanceId(moving_agile.instance_id)).row == Row.RANGED
    assert next_state.card(CardInstanceId(tied_agile.instance_id)).row == Row.RANGED
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        CardInstanceId(ranged_horn.instance_id),
        CardInstanceId(moving_agile.instance_id),
    )
    leader_event = next(event for event in events if isinstance(event, LeaderAbilityResolvedEvent))
    assert leader_event.moved_card_instance_ids == (CardInstanceId(moving_agile.instance_id),)


def test_shuffle_all_discards_into_decks_leader_moves_both_discards_back_into_decks() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    player_one_deck_card = card("p1_existing_deck_griffin", "monsters_griffin")
    player_one_discard_card = card("p1_discard_ghoul_to_shuffle", "monsters_ghoul")
    player_two_deck_card = card("p2_existing_deck_archer", "scoiatael_dol_blathanna_archer")
    player_two_discard_card = card("p2_discard_ballista_to_shuffle", "northern_realms_ballista")
    state = (
        scenario("shuffle_all_discards_into_decks")
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
        rng=IdentityShuffle(),
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
        rng=IdentityShuffle(),
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
