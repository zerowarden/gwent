"""Shared helpers for play-card legality tests."""

import pytest
from gwent_engine.cards.models import CardDefinition, CardRegistry
from gwent_engine.core import FactionId, Row
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState
from gwent_engine.leaders.models import LeaderRegistry
from gwent_engine.rules.legality import (
    validate_play_card_legality,
)

from tests.engine.scenario_builder import ScenarioRows, card, rows, scenario
from tests.engine.support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
)
from tests.support import PLAYER_ONE_ID


def play_action(
    card_instance_id: str,
    *,
    target_row: Row | None = None,
    target_card_instance_id: str | None = None,
) -> PlayCardAction:
    return PlayCardAction(
        player_id=PLAYER_ONE_ID,
        card_instance_id=CardInstanceId(card_instance_id),
        target_row=target_row,
        target_card_instance_id=(
            CardInstanceId(target_card_instance_id) if target_card_instance_id is not None else None
        ),
    )


def build_registry_with_extra(extra_definition: CardDefinition) -> CardRegistry:
    return CardRegistry.from_definitions((*tuple(CARD_REGISTRY), extra_definition))


def validate_play(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry = CARD_REGISTRY,
    leader_registry: LeaderRegistry = LEADER_REGISTRY,
    rng: SupportsRandom | None = None,
) -> None:
    validate_play_card_legality(
        state,
        state.player(action.player_id),
        action,
        card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def assert_play_rejected(
    *,
    scenario_name: str,
    hand_card_instance_id: str,
    hand_card_definition_id: str,
    action: PlayCardAction,
    message: str,
    board: ScenarioRows | None = None,
    faction: str | FactionId | None = None,
    leader_id: str | None = None,
    discard_card_instance_id: str | None = None,
    discard_card_definition_id: str | None = None,
    rng: SupportsRandom | None = None,
) -> None:
    discard_cards = (
        []
        if discard_card_instance_id is None or discard_card_definition_id is None
        else [card(discard_card_instance_id, discard_card_definition_id)]
    )
    state = (
        scenario(scenario_name)
        .player(
            "p1",
            faction=faction,
            leader_id=leader_id,
            hand=[card(hand_card_instance_id, hand_card_definition_id)],
            discard=discard_cards,
            board=board or rows(),
        )
        .build()
    )

    with pytest.raises(IllegalActionError, match=message):
        validate_play(state, action, rng=rng)
