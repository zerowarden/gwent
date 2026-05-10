from dataclasses import replace

import pytest
from gwent_engine.core import FactionId, LeaderAbilityKind, Row, Zone
from gwent_engine.core.actions import PlayCardAction, StartGameAction, UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import LeaderAbilityResolvedEvent, MedicResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.rules.scoring import calculate_effective_strength

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    MONSTERS_DOUBLE_SPY_LEADER_ID,
    NILFGAARD_DECK_ID,
    NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
    NILFGAARD_WHITE_FLAME_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_LEADER_PASSIVES_DECK_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
    IdentityShuffle,
    IndexedRandom,
    build_sample_game_state,
)


def test_white_flame_disables_opponent_passive_leader_before_setup() -> None:
    leader_registry = LEADER_REGISTRY
    base_state = build_sample_game_state(
        player_one_deck_id=NILFGAARD_DECK_ID,
        player_two_deck_id=SCOIATAEL_LEADER_PASSIVES_DECK_ID,
    )
    white_flame_state = replace(
        base_state,
        players=(
            replace(
                base_state.players[0],
                leader=replace(
                    base_state.players[0].leader,
                    leader_id=NILFGAARD_WHITE_FLAME_LEADER_ID,
                ),
            ),
            base_state.players[1],
        ),
    )

    next_state, events = apply_action(
        white_flame_state,
        StartGameAction(starting_player=PLAYER_ONE_ID),
        rng=IdentityShuffle(),
        leader_registry=leader_registry,
    )

    assert next_state.player(PLAYER_TWO_ID).leader.disabled is True
    assert len(next_state.player(PLAYER_TWO_ID).hand) == 10
    assert not any(
        isinstance(event, LeaderAbilityResolvedEvent)
        and event.player_id == PLAYER_TWO_ID
        and event.ability_kind == LeaderAbilityKind.DRAW_EXTRA_OPENING_CARD
        for event in events
    )
    disable_event = next(
        event
        for event in events
        if isinstance(event, LeaderAbilityResolvedEvent)
        and event.ability_kind == LeaderAbilityKind.DISABLE_OPPONENT_LEADER
    )
    assert disable_event.disabled_player_id == PLAYER_TWO_ID


def test_disabled_leaders_cannot_use_active_abilities() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    state = (
        scenario("disabled_leader_cannot_use_ability")
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
        )
        .current_player(PLAYER_TWO_ID)
        .build()
    )
    disabled_state = replace(
        state,
        players=(
            state.players[0],
            replace(
                state.players[1],
                leader=replace(state.players[1].leader, disabled=True),
            ),
        ),
    )

    with pytest.raises(
        IllegalActionError,
        match="Disabled leaders cannot use their active ability",
    ):
        _ = apply_action(
            disabled_state,
            UseLeaderAbilityAction(player_id=PLAYER_TWO_ID),
            card_registry=card_registry,
            leader_registry=leader_registry,
        )


def test_double_spy_strength_global_applies_to_both_players() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    player_one_spy = card(
        "p1_spy_infiltrator_on_opponent_side",
        "northern_realms_prince_stennis",
        owner=PLAYER_ONE_ID,
    )
    player_two_spy = card(
        "p2_spy_infiltrator_on_opponent_side",
        "northern_realms_prince_stennis",
        owner=PLAYER_TWO_ID,
    )
    state = (
        scenario("double_spy_strength_global")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.MONSTERS,
            leader_id=MONSTERS_DOUBLE_SPY_LEADER_ID,
            board=rows(close=[player_two_spy]),
        )
        .player(
            PLAYER_TWO_ID,
            board=rows(close=[player_one_spy]),
        )
        .build()
    )

    assert (
        calculate_effective_strength(
            state,
            card_registry,
            CardInstanceId(player_one_spy.instance_id),
            leader_registry=leader_registry,
        )
        == 10
    )
    assert (
        calculate_effective_strength(
            state,
            card_registry,
            CardInstanceId(player_two_spy.instance_id),
            leader_registry=leader_registry,
        )
        == 10
    )


def test_randomize_restore_to_battlefield_selection_makes_medic_target_optional() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    medic_card = card("p1_hand_field_surgeon_medic", "scoiatael_havekar_healer")
    first_discard = card("p1_discard_vanguard_candidate", "scoiatael_mahakaman_defender")
    second_discard = card("p1_discard_archer_candidate", "scoiatael_dol_blathanna_archer")
    opponent_hand = card("p2_hand_reserve_vanguard_unit", "scoiatael_mahakaman_defender")
    state = (
        scenario("randomize_restore_medic_target_optional")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RANDOMIZE_RESTORE_LEADER_ID,
            hand=(medic_card,),
            discard=(first_discard, second_discard),
        )
        .player(PLAYER_TWO_ID, hand=(opponent_hand,))
        .current_player(PLAYER_ONE_ID)
        .build()
    )

    next_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId(medic_card.instance_id),
            target_row=Row.RANGED,
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=IndexedRandom(choice_index=1),
    )

    assert next_state.card(CardInstanceId(second_discard.instance_id)).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId(second_discard.instance_id)).row == Row.RANGED
    medic_event = next(event for event in events if isinstance(event, MedicResolvedEvent))
    assert medic_event.resurrected_card_instance_id == CardInstanceId(second_discard.instance_id)


def test_king_bran_halves_weather_penalty_using_round_up_policy() -> None:
    card_registry = CARD_REGISTRY
    leader_registry = LEADER_REGISTRY
    bran_unit = card("p1_close_griffin_under_weather", "monsters_griffin")
    normal_unit = card("p2_close_griffin_under_weather", "monsters_griffin")
    frost = card("neutral_biting_frost_weather_effect", "neutral_biting_frost")
    state = (
        scenario("king_bran_weather_round_up")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            board=rows(close=[bran_unit]),
        )
        .player(PLAYER_TWO_ID, board=rows(close=[normal_unit]))
        .weather(rows(close=[frost]))
        .build()
    )

    assert (
        calculate_effective_strength(
            state,
            card_registry,
            CardInstanceId(bran_unit.instance_id),
            leader_registry=leader_registry,
        )
        == 3
    )
    assert (
        calculate_effective_strength(
            state,
            card_registry,
            CardInstanceId(normal_unit.instance_id),
            leader_registry=leader_registry,
        )
        == 1
    )
