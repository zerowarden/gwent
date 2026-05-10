from dataclasses import replace
from typing import Literal

from gwent_engine.cards import CardRegistry
from gwent_engine.core import GameStatus, Phase, Zone
from gwent_engine.core.events import (
    CardsMovedToDiscardEvent,
    GameEvent,
    MatchEndedEvent,
    NextRoundStartedEvent,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import GameState, PlayerState, RowState
from gwent_engine.rules.avenger import (
    resolve_leave_battlefield_triggers,
    resolve_pending_avenger_summons_at_round_start,
)
from gwent_engine.rules.state_ops import replace_card_instances

EMPTY_RETAINED_CARD_IDS: frozenset[CardInstanceId] = frozenset()


def cleanup_battlefield(
    state: GameState,
    *,
    card_registry: CardRegistry,
    retained_card_ids: frozenset[CardInstanceId] = EMPTY_RETAINED_CARD_IDS,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    """Move round-ended battlefield cards to discard and resolve leave effects.

    This clears every non-retained round-end card in a single deterministic pass:
    player-row units, player-row special effects, and shared weather effects.
    Retained cards stay on the battlefield, player rows are rebuilt from those ids
    only, and the shared weather zone is reset before queued leave-battlefield
    triggers such as Avenger summons are resolved.
    """
    moved_card_ids = tuple(
        card.instance_id
        for card in state.card_instances
        if card.zone in {Zone.BATTLEFIELD, Zone.WEATHER}
        and card.instance_id not in retained_card_ids
    )
    removed_cards = tuple(state.card(card_id) for card_id in moved_card_ids)
    updated_cards = {
        card_id: replace(
            state.card(card_id),
            zone=Zone.DISCARD,
            row=None,
            battlefield_side=None,
        )
        for card_id in moved_card_ids
    }
    updated_players = _cleanup_players(
        state,
        retained_card_ids,
        moved_card_ids=moved_card_ids,
    )
    event = CardsMovedToDiscardEvent(
        event_id=state.event_counter + 1,
        card_instance_ids=moved_card_ids,
    )
    base_state = replace(
        state,
        players=updated_players,
        card_instances=replace_card_instances(state.card_instances, updated_cards),
        weather=RowState(),
        event_counter=state.event_counter + 1,
    )
    next_state, avenger_events = resolve_leave_battlefield_triggers(
        base_state,
        removed_cards,
        card_registry=card_registry,
        event_id_start=state.event_counter + 2,
        queue_for_next_round=True,
    )
    next_state = replace(next_state, event_counter=state.event_counter + 1 + len(avenger_events))
    return next_state, (event, *avenger_events)


def start_next_round(
    state: GameState,
    *,
    starting_player: PlayerId,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    next_round_number = state.round_number + 1
    event = NextRoundStartedEvent(
        event_id=state.event_counter + 1,
        round_number=next_round_number,
        starting_player=starting_player,
    )
    base_state = replace(
        state,
        current_player=starting_player,
        round_starter=starting_player,
        round_number=next_round_number,
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        match_winner=None,
        event_counter=state.event_counter + 1,
    )
    next_state, avenger_events = resolve_pending_avenger_summons_at_round_start(base_state)
    next_state = replace(next_state, event_counter=state.event_counter + 1 + len(avenger_events))
    return next_state, (event, *avenger_events)


def end_match(
    state: GameState,
    *,
    winner: PlayerId | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    event = MatchEndedEvent(
        event_id=state.event_counter + 1,
        winner=winner,
    )
    next_state = replace(
        state,
        current_player=None,
        phase=Phase.MATCH_ENDED,
        status=GameStatus.MATCH_ENDED,
        match_winner=winner,
        event_counter=state.event_counter + 1,
    )
    return next_state, (event,)


def determine_match_winner(state: GameState) -> PlayerId | None | Literal[False]:
    first_player, second_player = state.players
    first_eliminated = first_player.gems_remaining == 0
    second_eliminated = second_player.gems_remaining == 0
    if not first_eliminated and not second_eliminated:
        return False
    if first_eliminated and second_eliminated:
        return None
    if first_eliminated:
        return second_player.player_id
    return first_player.player_id


def _cleanup_player(
    state: GameState,
    player: PlayerState,
    retained_card_ids: frozenset[CardInstanceId],
    *,
    moved_card_ids: tuple[CardInstanceId, ...],
    battlefield_weather_card_ids: tuple[CardInstanceId, ...],
) -> PlayerState:
    owned_moved_battlefield_cards = tuple(
        card_id
        for card_id in moved_card_ids
        if state.card(card_id).owner == player.player_id
        and state.card(card_id).battlefield_side is not None
    )
    return replace(
        player,
        leader=replace(player.leader, horn_row=None),
        discard=player.discard + owned_moved_battlefield_cards + battlefield_weather_card_ids,
        rows=RowState(
            close=tuple(card_id for card_id in player.rows.close if card_id in retained_card_ids),
            ranged=tuple(card_id for card_id in player.rows.ranged if card_id in retained_card_ids),
            siege=tuple(card_id for card_id in player.rows.siege if card_id in retained_card_ids),
        ),
        has_passed=False,
    )


def _cleanup_players(
    state: GameState,
    retained_card_ids: frozenset[CardInstanceId],
    *,
    moved_card_ids: tuple[CardInstanceId, ...],
) -> tuple[PlayerState, PlayerState]:
    cleaned_players = tuple(
        _cleanup_player(
            state,
            player,
            retained_card_ids,
            moved_card_ids=moved_card_ids,
            battlefield_weather_card_ids=_owned_battlefield_weather_cards(
                state,
                player.player_id,
            ),
        )
        for player in state.players
    )
    return cleaned_players[0], cleaned_players[1]


def _owned_battlefield_weather_cards(
    state: GameState,
    player_id: PlayerId,
) -> tuple[CardInstanceId, ...]:
    return tuple(
        card_id
        for card_id in state.battlefield_weather.all_cards()
        if state.card(card_id).owner == player_id
    )
