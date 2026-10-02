from dataclasses import replace

import pytest
from gwent_engine.cards.models import CardDefinition
from gwent_engine.core import CardType, FactionId, Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardDefinitionId, CardInstanceId
from gwent_engine.rules.legality import (
    validate_in_round_player_can_act,
)

from tests.engine.rules.support import (
    assert_play_rejected,
    build_registry_with_extra,
    play_action,
    validate_play,
)
from tests.engine.scenario_builder import card, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
)
from tests.support import PLAYER_ONE_ID, PLAYER_TWO_ID


def test_validate_in_round_player_can_act_rejects_passed_player() -> None:
    state = (
        scenario("legality_reject_passed_player")
        .player(
            "p1",
            passed=True,
            hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="Passed players cannot act again"):
        validate_in_round_player_can_act(state, state.player(PLAYER_ONE_ID))


def test_validate_in_round_player_can_act_rejects_non_current_player() -> None:
    state = (
        scenario("legality_reject_non_current_player")
        .current_player("p2")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Only the current player may act"):
        validate_in_round_player_can_act(state, state.player(PLAYER_ONE_ID))


def test_validate_in_round_player_can_act_accepts_current_unpassed_player() -> None:
    state = (
        scenario("legality_accept_current_unpassed_player")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    validate_in_round_player_can_act(
        state,
        state.player(PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def test_validate_in_round_player_can_act_accepts_empty_hand_with_usable_leader() -> None:
    state = (
        scenario("legality_accept_empty_hand_with_leader")
        .player(
            "p1",
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
        )
        .build()
    )

    validate_in_round_player_can_act(
        state,
        state.player(PLAYER_ONE_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def test_validate_in_round_player_can_act_rejects_empty_hand_without_leader() -> None:
    state = (
        scenario("legality_reject_empty_hand_without_leader")
        .player(
            "p1",
            faction="northern_realms",
            leader_id=NORTHERN_REALMS_CLEAR_WEATHER_LEADER_ID,
            leader_used=True,
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="no available leader action"):
        validate_in_round_player_can_act(
            state,
            state.player(PLAYER_ONE_ID),
            card_registry=CARD_REGISTRY,
            leader_registry=LEADER_REGISTRY,
        )


def test_validate_play_card_legality_rejects_card_not_in_hand() -> None:
    state = scenario("legality_reject_card_not_in_hand").build()

    with pytest.raises(IllegalActionError, match="is not in player"):
        validate_play(
            state,
            play_action("missing_vanguard_in_hand", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_wrong_owner() -> None:
    borrowed_card_id = CardInstanceId("p2_vanguard_borrowed_in_hand")
    state = (
        scenario("legality_reject_wrong_owner")
        .player(
            PLAYER_ONE_ID,
            hand=[card(borrowed_card_id, "scoiatael_mahakaman_defender", owner=PLAYER_TWO_ID)],
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match="does not belong to player"):
        validate_play(
            state,
            play_action("p2_vanguard_borrowed_in_hand", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_card_not_in_hand_zone() -> None:
    misplaced_card_id = CardInstanceId("p1_vanguard_marked_as_deck")
    built_state = (
        scenario("legality_reject_card_not_in_hand_zone")
        .player(PLAYER_ONE_ID, hand=[card(misplaced_card_id, "scoiatael_mahakaman_defender")])
        .build()
    )
    state = replace(
        built_state,
        card_instances=tuple(
            replace(card_instance, zone=Zone.DECK)
            if card_instance.instance_id == misplaced_card_id
            else card_instance
            for card_instance in built_state.card_instances
        ),
    )

    with pytest.raises(IllegalActionError, match="must be in hand to be played"):
        validate_play(
            state,
            play_action("p1_vanguard_marked_as_deck", target_row=Row.CLOSE),
        )


def test_validate_play_card_legality_rejects_non_unit_non_special_cards() -> None:
    leader_card_definition = CardDefinition(
        definition_id=CardDefinitionId("synthetic_leader_card"),
        name="Synthetic Leader Card",
        faction=FactionId.NEUTRAL,
        card_type=CardType.LEADER,
        base_strength=0,
        allowed_rows=(),
    )
    state = (
        scenario("legality_reject_synthetic_leader_card")
        .player("p1", hand=[card("p1_synthetic_leader_in_hand", "synthetic_leader_card")])
        .build()
    )

    with pytest.raises(IllegalActionError, match="Only unit cards and supported special cards"):
        validate_play(
            state,
            play_action("p1_synthetic_leader_in_hand"),
            card_registry=build_registry_with_extra(leader_card_definition),
        )


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (play_action("p1_vanguard_in_hand"), "Unit cards must target a combat row."),
        (
            play_action("p1_vanguard_in_hand", target_row=Row.SIEGE),
            "cannot be played to row",
        ),
        (
            play_action(
                "p1_vanguard_in_hand",
                target_row=Row.CLOSE,
                target_card_instance_id="discard_target_archer",
            ),
            "Only Medic unit cards may target another card",
        ),
    ],
)
def test_non_medic_unit_legality_rejects_invalid_targets(
    action: PlayCardAction,
    message: str,
) -> None:
    assert_play_rejected(
        scenario_name="legality_reject_non_medic_invalid_targets",
        hand_card_instance_id="p1_vanguard_in_hand",
        hand_card_definition_id="scoiatael_mahakaman_defender",
        action=action,
        message=message,
    )


def test_non_medic_unit_legality_accepts_clean_row_play() -> None:
    state = (
        scenario("legality_accept_non_medic_clean_row_play")
        .player("p1", hand=[card("p1_vanguard_in_hand", "scoiatael_mahakaman_defender")])
        .build()
    )

    validate_play(
        state,
        play_action("p1_vanguard_in_hand", target_row=Row.CLOSE),
    )
