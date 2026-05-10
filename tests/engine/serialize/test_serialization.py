from dataclasses import replace

from gwent_engine.core import (
    AbilityKind,
    EffectSourceCategory,
    LeaderAbilityKind,
    LeaderAbilityMode,
    PassiveKind,
    Phase,
    Row,
)
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.events import (
    AvengerSummonedEvent,
    AvengerSummonQueuedEvent,
    CardPlayedEvent,
    CardsDrawnEvent,
    CardsMovedToDiscardEvent,
    CardTransformedEvent,
    FactionPassiveTriggeredEvent,
    GameStartedEvent,
    LeaderAbilityResolvedEvent,
    MatchEndedEvent,
    MedicResolvedEvent,
    MulliganPerformedEvent,
    MusterResolvedEvent,
    NextRoundStartedEvent,
    PlayerLeftEvent,
    PlayerPassedEvent,
    RoundEndedEvent,
    SpecialCardResolvedEvent,
    SpyResolvedEvent,
    StartingPlayerChosenEvent,
    UnitHornActivatedEvent,
    UnitHornSuppressedEvent,
    UnitScorchResolvedEvent,
)
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId, LeaderId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import PendingAvengerSummon
from gwent_engine.serialize import (
    event_from_dict,
    event_to_dict,
    game_state_from_dict,
    game_state_to_dict,
)

from tests.engine.scenario_builder import card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    run_scripted_round,
)


def test_game_state_serialization_roundtrip() -> None:
    final_state, _ = run_scripted_round()
    roundtrip_state = game_state_from_dict(game_state_to_dict(replace(final_state, rng_seed=123)))

    assert roundtrip_state == replace(final_state, rng_seed=123)


def test_game_state_serialization_roundtrip_with_pending_avenger_summon() -> None:
    final_state, _ = run_scripted_round()
    queued_source_card_id = final_state.player(PLAYER_ONE_ID).discard[0]
    pending_state = replace(
        final_state,
        pending_avenger_summons=(
            PendingAvengerSummon(
                source_card_instance_id=queued_source_card_id,
                summoned_definition_id=CardDefinitionId("neutral_bovine_defense_force"),
                owner=PLAYER_ONE_ID,
                battlefield_side=PLAYER_ONE_ID,
                row=Row.RANGED,
            ),
        ),
        generated_card_counter=2,
        rng_seed=321,
    )

    assert game_state_from_dict(game_state_to_dict(pending_state)) == pending_state


def test_game_state_serialization_roundtrip_with_pending_choice() -> None:
    decoy_card_id = CardInstanceId("p1_decoy_trick_card")
    frontliner_card_id = CardInstanceId("p1_vanguard_frontliner")
    pending_state, _ = apply_action(
        scenario("serialization_roundtrip_with_pending_choice")
        .player(
            PLAYER_ONE_ID,
            hand=[card(decoy_card_id, "neutral_decoy")],
            board=rows(close=[card(frontliner_card_id, "scoiatael_mahakaman_defender")]),
        )
        .build(),
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=CARD_REGISTRY,
    )

    assert pending_state.pending_choice is not None
    assert game_state_from_dict(game_state_to_dict(pending_state)) == pending_state


def test_game_state_serialization_roundtrip_with_battlefield_weather() -> None:
    weathered_state = (
        scenario("serialization_roundtrip_with_battlefield_weather")
        .weather(
            rows(
                close=[card("p1_biting_frost_weather", "neutral_biting_frost")],
                ranged=[card("p2_impenetrable_fog_weather", "neutral_impenetrable_fog")],
            )
        )
        .build()
    )

    roundtrip_state = game_state_from_dict(game_state_to_dict(weathered_state))

    assert roundtrip_state == weathered_state
    assert roundtrip_state.battlefield_weather == weathered_state.weather


def test_event_serialization_roundtrip() -> None:
    events = (
        StartingPlayerChosenEvent(event_id=1, player_id=PLAYER_ONE_ID),
        GameStartedEvent(event_id=2, phase=Phase.MULLIGAN, round_number=1),
        CardsDrawnEvent(
            event_id=3,
            player_id=PLAYER_ONE_ID,
            card_instance_ids=(
                CardInstanceId("p1_card_1"),
                CardInstanceId("p1_card_2"),
            ),
        ),
        MulliganPerformedEvent(
            event_id=4,
            player_id=PLAYER_ONE_ID,
            replaced_card_instance_ids=(CardInstanceId("p1_card_1"),),
            drawn_card_instance_ids=(CardInstanceId("p1_card_11"),),
        ),
        CardPlayedEvent(
            event_id=5,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_card_2"),
            target_row=None,
        ),
        SpyResolvedEvent(
            event_id=6,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_spy_infiltrator"),
            drawn_card_instance_ids=(
                CardInstanceId("p1_drawn_agile_outrider"),
                CardInstanceId("p1_drawn_bond_vanguard"),
            ),
        ),
        MedicResolvedEvent(
            event_id=7,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_field_surgeon"),
            resurrected_card_instance_id=CardInstanceId("p1_discard_vanguard_skirmisher"),
        ),
        MusterResolvedEvent(
            event_id=8,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_hand_warband_fighter"),
            mustered_card_instance_ids=(
                CardInstanceId("p1_deck_warband_first"),
                CardInstanceId("p1_deck_warband_second"),
            ),
        ),
        CardTransformedEvent(
            event_id=9,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_berserker_frontliner"),
            previous_definition_id=CardDefinitionId("skellige_berserker"),
            new_definition_id=CardDefinitionId("skellige_transformed_vildkaarl"),
            affected_row=Row.CLOSE,
        ),
        UnitHornActivatedEvent(
            event_id=10,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_hornmaster_troubadour"),
            affected_row=Row.RANGED,
        ),
        UnitHornSuppressedEvent(
            event_id=11,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_second_hornmaster_troubadour"),
            affected_row=Row.RANGED,
            active_source_category=EffectSourceCategory.UNIT_ABILITY,
            active_source_card_instance_id=CardInstanceId("p1_hornmaster_troubadour"),
        ),
        UnitScorchResolvedEvent(
            event_id=12,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_drakeslayer_row_scorch"),
            affected_row=Row.RANGED,
            destroyed_card_instance_ids=(
                CardInstanceId("p2_ranged_vanguard_one"),
                CardInstanceId("p2_ranged_vanguard_two"),
            ),
        ),
        SpecialCardResolvedEvent(
            event_id=13,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_card_10"),
            ability_kind=AbilityKind.CLEAR_WEATHER,
            discarded_card_instance_ids=(
                CardInstanceId("p1_card_7"),
                CardInstanceId("p2_card_8"),
                CardInstanceId("p1_card_10"),
            ),
        ),
        SpecialCardResolvedEvent(
            event_id=14,
            player_id=PLAYER_ONE_ID,
            card_instance_id=CardInstanceId("p1_card_9"),
            ability_kind=AbilityKind.DECOY,
            target_card_instance_id=CardInstanceId("p1_card_1"),
        ),
        AvengerSummonQueuedEvent(
            event_id=15,
            player_id=PLAYER_ONE_ID,
            source_card_instance_id=CardInstanceId("p1_avenger_cow_source"),
            summoned_definition_id=CardDefinitionId("neutral_bovine_defense_force"),
            affected_row=Row.RANGED,
        ),
        AvengerSummonedEvent(
            event_id=16,
            player_id=PLAYER_ONE_ID,
            source_card_instance_id=CardInstanceId("p1_avenger_cow_source"),
            summoned_card_instance_id=CardInstanceId("generated_neutral_bovine_defense_force_1"),
            summoned_definition_id=CardDefinitionId("neutral_bovine_defense_force"),
            affected_row=Row.RANGED,
        ),
        LeaderAbilityResolvedEvent(
            event_id=17,
            player_id=PLAYER_ONE_ID,
            leader_id=LeaderId("northern_realms_foltest_lord_commander_of_the_north"),
            ability_kind=LeaderAbilityKind.CLEAR_WEATHER,
            ability_mode=LeaderAbilityMode.ACTIVE,
            discarded_card_instance_ids=(
                CardInstanceId("p1_weather_frost"),
                CardInstanceId("p2_weather_fog"),
            ),
        ),
        PlayerPassedEvent(event_id=18, player_id=PLAYER_TWO_ID),
        PlayerLeftEvent(event_id=19, player_id=PLAYER_ONE_ID),
        FactionPassiveTriggeredEvent(
            event_id=20,
            player_id=PLAYER_ONE_ID,
            passive_kind=PassiveKind.SCOIATAEL_CHOOSES_STARTING_PLAYER,
            chosen_player_id=PLAYER_ONE_ID,
        ),
        FactionPassiveTriggeredEvent(
            event_id=21,
            player_id=PLAYER_TWO_ID,
            passive_kind=PassiveKind.MONSTERS_KEEP_ONE_UNIT,
            card_instance_id=CardInstanceId("p2_card_9"),
        ),
        RoundEndedEvent(
            event_id=22,
            round_number=1,
            player_scores=((PLAYER_ONE_ID, 10), (PLAYER_TWO_ID, 5)),
            winner=PLAYER_ONE_ID,
        ),
        CardsMovedToDiscardEvent(
            event_id=23,
            card_instance_ids=(CardInstanceId("p1_card_2"),),
        ),
        NextRoundStartedEvent(
            event_id=24,
            round_number=2,
            starting_player=PLAYER_ONE_ID,
        ),
        MatchEndedEvent(event_id=25, winner=None),
    )

    roundtrip_events = tuple(event_from_dict(event_to_dict(event)) for event in events)

    assert roundtrip_events == events
