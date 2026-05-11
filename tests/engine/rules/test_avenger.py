from collections.abc import Callable
from dataclasses import dataclass, replace

import pytest
from gwent_engine.core import FactionId, Row, Zone
from gwent_engine.core.actions import PassAction, PlayCardAction, ResolveChoiceAction
from gwent_engine.core.events import AvengerSummonedEvent, AvengerSummonQueuedEvent, GameEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.reducer import apply_action
from gwent_engine.core.state import GameState

from ..scenario_builder import ScenarioCard, ScenarioRows, card, rows, scenario
from ..support import (
    CARD_REGISTRY,
    LEADER_REGISTRY,
    NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
    PLAYER_ONE_ID,
    PLAYER_TWO_ID,
    SKELLIGE_KING_BRAN_LEADER_ID,
)

AVENGER_CASES = (
    ("neutral_avenger_cow", Row.RANGED, "neutral_bovine_defense_force"),
    ("skellige_kambi", Row.CLOSE, "skellige_hemdall"),
)
AvengerRemovalRunner = Callable[
    [GameState, str, CardInstanceId],
    tuple[GameState, tuple[GameEvent, ...]],
]
AvengerHandFactory = Callable[[str], tuple[tuple[str, str], ...]]


def _empty_hand(_source_definition_id: str) -> tuple[tuple[str, str], ...]:
    return ()


@dataclass(frozen=True)
class AvengerRemoval:
    name: str
    source_id_suffix: str
    runner: AvengerRemovalRunner
    hand_cards: AvengerHandFactory = _empty_hand
    current_player: PlayerId = PLAYER_ONE_ID
    use_cleanup_turn_order: bool = False
    passed_players: tuple[bool, bool] | None = None


def _remove_avenger(
    source_definition_id: str,
    source_row: Row,
    removal: AvengerRemoval,
) -> tuple[GameState, tuple[GameEvent, ...], CardInstanceId]:
    source_card_id = CardInstanceId(f"p1_{source_definition_id}_{removal.source_id_suffix}")
    state = _build_avenger_state(
        name=f"avenger_{removal.name}_{source_definition_id}",
        source_card_id=source_card_id,
        source_definition_id=source_definition_id,
        source_row=source_row,
        hand=tuple(
            card(card_id, definition_id)
            for card_id, definition_id in removal.hand_cards(source_definition_id)
        ),
        current_player=removal.current_player,
        use_cleanup_turn_order=removal.use_cleanup_turn_order,
        passed_players=removal.passed_players,
    )
    next_state, events = removal.runner(state, source_definition_id, source_card_id)
    return next_state, events, source_card_id


def _build_avenger_state(
    *,
    name: str,
    source_card_id: CardInstanceId,
    source_definition_id: str,
    source_row: Row,
    hand: tuple[ScenarioCard, ...] = (),
    current_player: PlayerId = PLAYER_ONE_ID,
    use_cleanup_turn_order: bool = False,
    passed_players: tuple[bool, bool] | None = None,
) -> GameState:
    builder = scenario(name).current_player(current_player)
    if use_cleanup_turn_order:
        builder = builder.turn_order(starting_player=PLAYER_ONE_ID, round_starter=PLAYER_ONE_ID)
    state = (
        builder.player(
            PLAYER_ONE_ID,
            faction=FactionId.SKELLIGE,
            leader_id=SKELLIGE_KING_BRAN_LEADER_ID,
            hand=hand,
            board=_avenger_board(source_card_id, source_definition_id, source_row),
        )
        .player(
            PLAYER_TWO_ID,
            faction=FactionId.NILFGAARD,
            leader_id=NILFGAARD_RAIN_FROM_DECK_LEADER_ID,
        )
        .build()
    )
    if passed_players is None:
        return state
    player_one_passed, player_two_passed = passed_players
    return replace(
        state,
        players=(
            replace(state.player(PLAYER_ONE_ID), has_passed=player_one_passed),
            replace(state.player(PLAYER_TWO_ID), has_passed=player_two_passed),
        ),
        current_player=current_player,
    )


def _avenger_board(
    source_card_id: CardInstanceId,
    source_definition_id: str,
    source_row: Row,
) -> ScenarioRows:
    source_card = card(str(source_card_id), source_definition_id)
    if source_row == Row.CLOSE:
        return rows(close=[source_card])
    return rows(ranged=[source_card])


def _resolve_live_round_removal(
    state: GameState,
    source_definition_id: str,
    source_card_id: CardInstanceId,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    decoy_card_id = CardInstanceId(f"p1_decoy_against_{source_definition_id}")
    pending_state, events = apply_action(
        state,
        PlayCardAction(
            player_id=PLAYER_ONE_ID,
            card_instance_id=decoy_card_id,
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    assert events == ()
    assert pending_state.pending_choice is not None

    next_state, events = apply_action(
        pending_state,
        ResolveChoiceAction(
            player_id=PLAYER_ONE_ID,
            choice_id=pending_state.pending_choice.choice_id,
            selected_card_instance_ids=(source_card_id,),
        ),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )
    return next_state, events


def _resolve_cleanup_removal(
    state: GameState,
    _source_definition_id: str,
    _source_card_id: CardInstanceId,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    return apply_action(
        state,
        PassAction(player_id=PLAYER_TWO_ID),
        card_registry=CARD_REGISTRY,
        leader_registry=LEADER_REGISTRY,
    )


def _live_round_hand(source_definition_id: str) -> tuple[tuple[str, str], ...]:
    return ((f"p1_decoy_against_{source_definition_id}", "neutral_decoy"),)


LIVE_ROUND_REMOVAL = AvengerRemoval(
    name="live_round",
    source_id_suffix="live_round_source",
    runner=_resolve_live_round_removal,
    hand_cards=_live_round_hand,
)
CLEANUP_REMOVAL = AvengerRemoval(
    name="cleanup",
    source_id_suffix="cleanup_source",
    runner=_resolve_cleanup_removal,
    current_player=PLAYER_TWO_ID,
    use_cleanup_turn_order=True,
    passed_players=(True, False),
)


AVENGER_REMOVAL_CASES: tuple[tuple[AvengerRemoval, Zone, bool], ...] = (
    (LIVE_ROUND_REMOVAL, Zone.HAND, False),
    (CLEANUP_REMOVAL, Zone.DISCARD, True),
)


@pytest.mark.parametrize(
    ("source_definition_id", "source_row", "summoned_definition_id"),
    AVENGER_CASES,
)
@pytest.mark.parametrize(
    ("removal", "expected_source_zone", "expect_queued"),
    AVENGER_REMOVAL_CASES,
)
def test_avenger_card_removed_summons_expected_unit(
    source_definition_id: str,
    source_row: Row,
    summoned_definition_id: str,
    removal: AvengerRemoval,
    expected_source_zone: Zone,
    expect_queued: bool,
) -> None:
    next_state, events, source_card_id = _remove_avenger(
        source_definition_id,
        source_row,
        removal,
    )

    assert next_state.card(source_card_id).zone == expected_source_zone
    _assert_avenger_summon(
        next_state,
        events,
        source_card_id=source_card_id,
        source_row=source_row,
        summoned_definition_id=summoned_definition_id,
        expect_queued=expect_queued,
    )


def _assert_avenger_summon(
    state: GameState,
    events: tuple[GameEvent, ...],
    *,
    source_card_id: CardInstanceId,
    source_row: Row,
    summoned_definition_id: str,
    expect_queued: bool,
) -> None:
    summoned_card = next(
        card for card in state.card_instances if card.definition_id == summoned_definition_id
    )
    assert summoned_card.instance_id != source_card_id
    assert summoned_card.zone == Zone.BATTLEFIELD
    assert summoned_card.row == source_row
    assert summoned_card.battlefield_side == PLAYER_ONE_ID
    assert state.pending_avenger_summons == ()
    assert (
        any(
            isinstance(event, AvengerSummonQueuedEvent)
            and event.source_card_instance_id == source_card_id
            and event.summoned_definition_id == summoned_definition_id
            for event in events
        )
        is expect_queued
    )
    assert any(
        isinstance(event, AvengerSummonedEvent)
        and event.source_card_instance_id == source_card_id
        and event.summoned_definition_id == summoned_definition_id
        for event in events
    )
