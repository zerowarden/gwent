from dataclasses import replace

import pytest
from gwent_engine.core import FactionId, PassiveKind, Phase, Row, Zone
from gwent_engine.core.actions import PassAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import (
    FactionPassiveTriggeredEvent,
    MatchEndedEvent,
    NextRoundStartedEvent,
)
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.reducer import apply_action
from gwent_engine.factions.passives import resolve_round_start_passives

from ..scenario_builder import card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SCOIATAEL_RANGED_HORN_LEADER_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
    IndexedRandom,
)


def test_skellige_summons_two_random_discard_units_at_start_of_third_round() -> None:
    card_registry = CARD_REGISTRY
    base_state = (
        scenario("skellige_summons_two_from_discard")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            discard=(
                card("p1_birna_bran_discard_unit", "skellige_birna_bran"),
                card("p1_madman_lugos_discard_unit", "skellige_madman_lugos"),
                card("p1_ermion_discard_hero", "skellige_ermion"),
            ),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            board=rows(
                close=[card("p2_vrihedd_frontline_unit", "scoiatael_vrihedd_brigade_veteran")]
            ),
        )
        .build()
    )
    state = replace(base_state, round_number=3)

    next_state, events = resolve_round_start_passives(
        state,
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=1),
    )

    assert next_state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId("p1_birna_bran_discard_unit"),
    )
    assert next_state.player(PLAYER_ONE_ID).rows.close == (
        CardInstanceId("p1_madman_lugos_discard_unit"),
    )
    assert next_state.player(PLAYER_ONE_ID).rows.ranged == (
        CardInstanceId("p1_ermion_discard_hero"),
    )
    assert next_state.card(CardInstanceId("p1_madman_lugos_discard_unit")).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId("p1_madman_lugos_discard_unit")).row == Row.CLOSE
    assert next_state.card(CardInstanceId("p1_ermion_discard_hero")).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId("p1_ermion_discard_hero")).row == Row.RANGED
    assert [type(event).__name__ for event in events] == [
        "FactionPassiveTriggeredEvent",
        "FactionPassiveTriggeredEvent",
    ]
    assert isinstance(events[0], FactionPassiveTriggeredEvent)
    assert isinstance(events[1], FactionPassiveTriggeredEvent)
    assert events[0].passive_kind == PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE
    assert events[0].card_instance_id == CardInstanceId("p1_madman_lugos_discard_unit")
    assert events[1].card_instance_id == CardInstanceId("p1_ermion_discard_hero")


def test_skellige_does_not_trigger_before_third_round() -> None:
    card_registry = CARD_REGISTRY
    state = (
        scenario("skellige_no_trigger_before_round_three")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            discard=(card("p1_birna_bran_discard_unit", "skellige_birna_bran"),),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
        )
        .build()
    )

    next_state, events = resolve_round_start_passives(
        state,
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    assert next_state == state
    assert events == ()


def test_skellige_only_summons_unit_cards_from_its_own_discard() -> None:
    card_registry = CARD_REGISTRY
    state = replace(
        scenario("skellige_only_uses_own_unit_discards")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            discard=(
                card("p1_birna_bran_discard_unit", "skellige_birna_bran"),
                card("p1_clear_weather_discard_special", "neutral_clear_weather"),
            ),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
            discard=(card("p2_vrihedd_discard_unit", "scoiatael_vrihedd_brigade_veteran"),),
        )
        .build(),
        round_number=3,
    )

    next_state, events = resolve_round_start_passives(
        state,
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    assert next_state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId("p1_clear_weather_discard_special"),
    )
    assert next_state.player(PLAYER_ONE_ID).rows.close == (
        CardInstanceId("p1_birna_bran_discard_unit"),
    )
    assert next_state.player(PLAYER_TWO_ID).discard == (CardInstanceId("p2_vrihedd_discard_unit"),)
    assert next_state.card(CardInstanceId("p1_birna_bran_discard_unit")).zone == Zone.BATTLEFIELD
    assert next_state.card(CardInstanceId("p1_clear_weather_discard_special")).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId("p2_vrihedd_discard_unit")).zone == Zone.DISCARD
    assert len(events) == 1
    assert isinstance(events[0], FactionPassiveTriggeredEvent)
    assert events[0].card_instance_id == CardInstanceId("p1_birna_bran_discard_unit")


def test_skellige_requires_rng_when_eligible_discard_units_exist_on_round_three() -> None:
    card_registry = CARD_REGISTRY
    state = replace(
        scenario("skellige_requires_rng")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            discard=(card("p1_birna_bran_discard_unit", "skellige_birna_bran"),),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
        )
        .build(),
        round_number=3,
    )

    with pytest.raises(IllegalActionError, match="Skellige passive requires an injected RNG"):
        _ = resolve_round_start_passives(
            state,
            card_registry=card_registry,
            rng=None,
        )


def test_skellige_does_not_trigger_when_match_ends_after_round_two() -> None:
    card_registry = CARD_REGISTRY
    frontline_winner = card("p1_madman_lugos_frontline_unit", "skellige_madman_lugos")
    discard_birna = card("p1_birna_bran_discard_unit", "skellige_birna_bran")
    discard_ermion = card("p1_ermion_discard_hero", "skellige_ermion")
    base_state = (
        scenario("skellige_round_two_match_end")
        .player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            discard=(discard_birna, discard_ermion),
            board=rows(close=[frontline_winner]),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.SCOIATAEL,
            leader_id=SCOIATAEL_RANGED_HORN_LEADER_ID,
        )
        .current_player(PLAYER_TWO_ID)
        .build()
    )
    player_one = replace(
        base_state.player(PLAYER_ONE_ID),
        gems_remaining=2,
        has_passed=True,
    )
    player_two = replace(
        base_state.player(PLAYER_TWO_ID),
        gems_remaining=1,
        has_passed=False,
    )
    state = replace(
        base_state,
        players=(player_one, player_two),
        round_number=2,
        phase=Phase.IN_ROUND,
    )

    next_state, events = apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=card_registry,
        rng=IndexedRandom(choice_index=0),
    )

    assert next_state.phase == Phase.MATCH_ENDED
    assert next_state.player(PLAYER_ONE_ID).rows.close == ()
    assert next_state.player(PLAYER_ONE_ID).discard == (
        CardInstanceId(discard_birna.instance_id),
        CardInstanceId(discard_ermion.instance_id),
        CardInstanceId(frontline_winner.instance_id),
    )
    assert next_state.card(CardInstanceId(discard_birna.instance_id)).zone == Zone.DISCARD
    assert next_state.card(CardInstanceId(discard_ermion.instance_id)).zone == Zone.DISCARD
    assert any(isinstance(event, MatchEndedEvent) for event in events)
    assert all(not isinstance(event, NextRoundStartedEvent) for event in events)
    assert all(
        not (
            isinstance(event, FactionPassiveTriggeredEvent)
            and event.passive_kind == PassiveKind.SKELLIGE_SUMMON_TWO_FROM_DISCARD_ON_ROUND_THREE
        )
        for event in events
    )
