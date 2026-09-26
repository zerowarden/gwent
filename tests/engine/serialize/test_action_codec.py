from __future__ import annotations

import pytest
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.enums import Row
from gwent_engine.core.errors import SerializationError
from gwent_engine.core.ids import CardInstanceId, ChoiceId, PlayerId
from gwent_engine.serialize import action_from_id, action_to_id

_PLAYER_ONE = PlayerId("p1")
_PLAYER_TWO = PlayerId("p2")


def _actions() -> tuple[GameAction, ...]:
    return (
        StartGameAction(starting_player=_PLAYER_ONE),
        ResolveMulligansAction(
            selections=(
                MulliganSelection(player_id=_PLAYER_ONE),
                MulliganSelection(
                    player_id=_PLAYER_TWO,
                    cards_to_replace=(CardInstanceId("p2_card_a"), CardInstanceId("p2_card_b")),
                ),
            )
        ),
        PlayCardAction(
            player_id=_PLAYER_ONE,
            card_instance_id=CardInstanceId("p1_card"),
            target_row=Row.CLOSE,
            target_card_instance_id=CardInstanceId("p2_target"),
            secondary_target_card_instance_id=CardInstanceId("p2_secondary"),
        ),
        PlayCardAction(
            player_id=_PLAYER_TWO,
            card_instance_id=CardInstanceId("p2_card"),
        ),
        PassAction(player_id=_PLAYER_ONE),
        LeaveAction(player_id=_PLAYER_TWO),
        ResolveChoiceAction(
            player_id=_PLAYER_ONE,
            choice_id=ChoiceId("medic_pick"),
            selected_card_instance_ids=(CardInstanceId("p1_discard_a"),),
            selected_rows=(Row.CLOSE, Row.RANGED),
        ),
        UseLeaderAbilityAction(
            player_id=_PLAYER_TWO,
            target_row=Row.SIEGE,
            target_player=_PLAYER_ONE,
            target_card_instance_id=CardInstanceId("p1_target"),
            secondary_target_card_instance_id=CardInstanceId("p1_secondary"),
            selected_card_instance_ids=(CardInstanceId("p2_hand_a"),),
        ),
        UseLeaderAbilityAction(player_id=_PLAYER_ONE),
    )


@pytest.mark.parametrize("action", _actions())
def test_actions_round_trip_through_their_id(action: GameAction) -> None:
    action_id = action_to_id(action)

    assert action_from_id(action_id) == action
    assert action_to_id(action_from_id(action_id)) == action_id


def test_malformed_literal_is_rejected() -> None:
    with pytest.raises(SerializationError, match="not a valid payload"):
        _ = action_from_id("not an action id")


def test_unknown_action_type_is_rejected() -> None:
    action_id = repr((("type", "UnknownAction"),))

    with pytest.raises(SerializationError, match="Unknown action type"):
        _ = action_from_id(action_id)


def test_unknown_field_is_rejected_as_non_canonical() -> None:
    action_id = repr((("player_id", "p1"), ("type", "PassAction"), ("unknown", "x")))

    with pytest.raises(SerializationError, match="not canonical"):
        _ = action_from_id(action_id)


def test_missing_field_is_rejected() -> None:
    action_id = repr((("type", "PassAction"),))

    with pytest.raises(SerializationError, match="'player_id' is required"):
        _ = action_from_id(action_id)


def test_invalid_row_is_rejected() -> None:
    action_id = repr(
        (
            ("card_instance_id", "p1_card"),
            ("player_id", "p1"),
            ("secondary_target_card_instance_id", ""),
            ("target_card_instance_id", ""),
            ("target_row", "nowhere"),
            ("type", "PlayCardAction"),
        )
    )

    with pytest.raises(SerializationError, match="must be one of"):
        _ = action_from_id(action_id)


def test_unsorted_payload_is_rejected_as_non_canonical() -> None:
    action_id = repr((("type", "PassAction"), ("player_id", "p1")))

    with pytest.raises(SerializationError, match="not canonical"):
        _ = action_from_id(action_id)


def test_duplicate_keys_are_rejected() -> None:
    action_id = repr((("player_id", "p1"), ("player_id", "p2"), ("type", "PassAction")))

    with pytest.raises(SerializationError, match="duplicate key"):
        _ = action_from_id(action_id)
