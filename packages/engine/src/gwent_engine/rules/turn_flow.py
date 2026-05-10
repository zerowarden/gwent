"""Pure in-round turn-flow helpers."""

from collections.abc import Callable
from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import (
    AbilityKind,
    CardType,
    EffectSourceCategory,
    GameStatus,
    Phase,
    Zone,
)
from gwent_engine.core.actions import PassAction, PlayCardAction
from gwent_engine.core.events import (
    CardPlayedEvent,
    GameEvent,
    PlayerPassedEvent,
    SpecialCardResolvedEvent,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState, RowState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.abilities import (
    apply_unit_card,
    destroy_battlefield_cards,
    strongest_battlefield_unit_card_ids,
)
from gwent_engine.rules.avenger import resolve_leave_battlefield_triggers
from gwent_engine.rules.battlefield_effects import weather_row_for
from gwent_engine.rules.mardroeme import apply_berserker_transformations_for_row
from gwent_engine.rules.players import other_player_from_pair, replace_player
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.state_ops import (
    append_to_row,
    discard_owned_weather_cards,
    next_player_after_non_pass_action,
    replace_card_instance,
    replace_card_instances,
    replace_row_card,
)

type SpecialCardHandler = Callable[
    [
        GameState,
        PlayCardAction,
        PlayerState,
        CardRegistry,
        LeaderRegistry | None,
        SupportsRandom | None,
        AbilityKind,
    ],
    tuple[GameState, tuple[GameEvent, ...]],
]


def apply_play_card(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    player = state.player(action.player_id)
    definition = card_registry.get(state.card(action.card_instance_id).definition_id)

    if definition.card_type == CardType.UNIT:
        return apply_unit_card(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    if definition.card_type != CardType.SPECIAL:
        raise ValueError(f"Unsupported special-play card type: {definition.card_type!r}")

    ability_kind = special_ability_kind(definition)
    handler = SPECIAL_CARD_HANDLERS.get(ability_kind)
    if handler is not None:
        return handler(
            state,
            action,
            player,
            card_registry,
            leader_registry,
            rng,
            ability_kind,
        )
    raise ValueError(f"Unsupported special ability kind: {ability_kind!r}")


def apply_pass(
    state: GameState,
    action: PassAction,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    player = state.player(action.player_id)
    updated_player = replace(player, has_passed=True)
    updated_players = replace_player(state.players, updated_player)
    opponent = other_player_from_pair(updated_players, action.player_id)

    if opponent.has_passed:
        next_phase = Phase.ROUND_RESOLUTION
        next_current_player = None
    else:
        next_phase = Phase.IN_ROUND
        next_current_player = opponent.player_id

    events: tuple[GameEvent, ...] = (
        PlayerPassedEvent(
            event_id=state.event_counter + 1,
            player_id=action.player_id,
        ),
    )
    next_state = replace(
        state,
        players=updated_players,
        current_player=next_current_player,
        phase=next_phase,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_row_targeted_special_base(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    assert action.target_row is not None
    updated_player = replace(
        player,
        hand=tuple(card_id for card_id in player.hand if card_id != action.card_instance_id),
        rows=append_to_row(player.rows, action.target_row, action.card_instance_id),
    )
    updated_card = replace(
        state.card(action.card_instance_id),
        zone=Zone.BATTLEFIELD,
        row=action.target_row,
        battlefield_side=action.player_id,
    )
    events: tuple[GameEvent, ...] = (
        CardPlayedEvent(
            event_id=state.event_counter + 1,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            target_row=action.target_row,
        ),
        SpecialCardResolvedEvent(
            event_id=state.event_counter + 2,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            ability_kind=ability_kind,
            affected_row=action.target_row,
        ),
    )
    next_state = replace(
        state,
        players=replace_player(state.players, updated_player),
        card_instances=replace_card_instance(state.card_instances, updated_card),
    )
    return next_state, events


def _special_card_discard_events(
    state: GameState,
    action: PlayCardAction,
    ability_kind: AbilityKind,
    discarded_card_ids: tuple[CardInstanceId, ...],
) -> tuple[GameEvent, ...]:
    return (
        CardPlayedEvent(
            event_id=state.event_counter + 1,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            target_row=None,
        ),
        SpecialCardResolvedEvent(
            event_id=state.event_counter + 2,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            ability_kind=ability_kind,
            discarded_card_instance_ids=discarded_card_ids,
        ),
    )


def _apply_commanders_horn(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del card_registry, leader_registry, rng
    base_state, events = _apply_row_targeted_special_base(state, action, player, ability_kind)
    next_state = replace(
        base_state,
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_weather_card(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del card_registry, leader_registry, rng
    affected_row = weather_row_for(ability_kind)
    updated_player = replace(
        player,
        hand=tuple(card_id for card_id in player.hand if card_id != action.card_instance_id),
    )
    updated_card = replace(
        state.card(action.card_instance_id),
        zone=Zone.WEATHER,
        row=affected_row,
        battlefield_side=None,
    )
    events: tuple[GameEvent, ...] = (
        CardPlayedEvent(
            event_id=state.event_counter + 1,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            target_row=affected_row,
        ),
    )
    next_state = replace(
        state,
        players=replace_player(state.players, updated_player),
        card_instances=replace_card_instance(state.card_instances, updated_card),
        weather=append_to_row(state.weather, affected_row, action.card_instance_id),
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_special_mardroeme(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del leader_registry, rng
    target_row = action.target_row
    assert target_row is not None
    base_state, base_events = _apply_row_targeted_special_base(
        state,
        action,
        player,
        ability_kind,
    )
    transformed_state, transform_events = apply_berserker_transformations_for_row(
        base_state,
        card_registry=card_registry,
        battlefield_side=action.player_id,
        row=target_row,
        event_id_start=state.event_counter + len(base_events) + 1,
    )
    events = (*base_events, *transform_events)
    next_state = replace(
        transformed_state,
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_clear_weather(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del player, card_registry, leader_registry, rng
    cleared_weather_ids = state.battlefield_weather.all_cards()
    discarded_card_ids = (*cleared_weather_ids, action.card_instance_id)
    first_player, second_player = state.players
    updated_players = (
        _discard_cleared_weather_cards(
            state,
            first_player,
            played_card_id=action.card_instance_id,
            acting_player_id=action.player_id,
            cleared_weather_ids=cleared_weather_ids,
        ),
        _discard_cleared_weather_cards(
            state,
            second_player,
            played_card_id=action.card_instance_id,
            acting_player_id=action.player_id,
            cleared_weather_ids=cleared_weather_ids,
        ),
    )
    updated_cards = {
        card_id: replace(
            state.card(card_id),
            zone=Zone.DISCARD,
            row=None,
            battlefield_side=None,
        )
        for card_id in discarded_card_ids
    }
    events = _special_card_discard_events(state, action, ability_kind, discarded_card_ids)
    next_state = replace(
        state,
        players=updated_players,
        card_instances=replace_card_instances(state.card_instances, updated_cards),
        weather=RowState(),
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_scorch(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del player, rng
    killed_card_ids = strongest_battlefield_unit_card_ids(
        state,
        card_registry,
        source_category=EffectSourceCategory.SPECIAL_CARD,
        leader_registry=leader_registry,
    )
    discarded_card_ids = (*killed_card_ids, action.card_instance_id)
    scorched_state, destroy_events = destroy_battlefield_cards(
        state,
        killed_card_ids,
        card_registry=card_registry,
        event_id_start=state.event_counter + 3,
    )
    acting_player = scorched_state.player(action.player_id)
    updated_player = replace(
        acting_player,
        hand=tuple(card_id for card_id in acting_player.hand if card_id != action.card_instance_id),
        discard=(*acting_player.discard, action.card_instance_id),
    )
    updated_cards = {
        action.card_instance_id: replace(
            scorched_state.card(action.card_instance_id),
            zone=Zone.DISCARD,
            row=None,
            battlefield_side=None,
        ),
    }
    events = (
        *_special_card_discard_events(state, action, ability_kind, discarded_card_ids),
        *destroy_events,
    )
    next_state = replace(
        scorched_state,
        players=replace_player(scorched_state.players, updated_player),
        card_instances=replace_card_instances(scorched_state.card_instances, updated_cards),
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _apply_decoy(
    state: GameState,
    action: PlayCardAction,
    player: PlayerState,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
    ability_kind: AbilityKind,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del leader_registry, rng
    assert action.target_card_instance_id is not None
    target_card = state.card(action.target_card_instance_id)
    assert target_card.row is not None
    updated_player = replace(
        player,
        hand=(
            *tuple(card_id for card_id in player.hand if card_id != action.card_instance_id),
            action.target_card_instance_id,
        ),
        rows=replace_row_card(
            player.rows,
            target_card.row,
            action.target_card_instance_id,
            action.card_instance_id,
        ),
    )
    updated_target_card = replace(
        target_card,
        owner=action.player_id,
        zone=Zone.HAND,
        row=None,
        battlefield_side=None,
    )
    updated_decoy_card = replace(
        state.card(action.card_instance_id),
        zone=Zone.BATTLEFIELD,
        row=target_card.row,
        battlefield_side=action.player_id,
    )
    base_events: tuple[GameEvent, ...] = (
        CardPlayedEvent(
            event_id=state.event_counter + 1,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            target_row=target_card.row,
        ),
        SpecialCardResolvedEvent(
            event_id=state.event_counter + 2,
            player_id=action.player_id,
            card_instance_id=action.card_instance_id,
            ability_kind=ability_kind,
            affected_row=target_card.row,
            target_card_instance_id=action.target_card_instance_id,
        ),
    )
    base_state = replace(
        state,
        players=replace_player(state.players, updated_player),
        card_instances=replace_card_instances(
            state.card_instances,
            {
                action.target_card_instance_id: updated_target_card,
                action.card_instance_id: updated_decoy_card,
            },
        ),
    )
    next_state, avenger_events = resolve_leave_battlefield_triggers(
        base_state,
        (target_card,),
        card_registry=card_registry,
        event_id_start=state.event_counter + len(base_events) + 1,
        queue_for_next_round=False,
    )
    events = (*base_events, *avenger_events)
    next_state = replace(
        next_state,
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _discard_cleared_weather_cards(
    state: GameState,
    player: PlayerState,
    *,
    played_card_id: CardInstanceId,
    acting_player_id: PlayerId,
    cleared_weather_ids: tuple[CardInstanceId, ...],
) -> PlayerState:
    updated_player = discard_owned_weather_cards(state, player, cleared_weather_ids)
    hand = updated_player.hand
    discard = updated_player.discard
    if player.player_id == acting_player_id:
        hand = tuple(card_id for card_id in player.hand if card_id != played_card_id)
        discard = (*discard, played_card_id)
    return replace(updated_player, hand=hand, discard=discard)


SPECIAL_CARD_HANDLERS: dict[AbilityKind, SpecialCardHandler] = {
    AbilityKind.COMMANDERS_HORN: _apply_commanders_horn,
    AbilityKind.MARDROEME: _apply_special_mardroeme,
    AbilityKind.BITING_FROST: _apply_weather_card,
    AbilityKind.IMPENETRABLE_FOG: _apply_weather_card,
    AbilityKind.TORRENTIAL_RAIN: _apply_weather_card,
    AbilityKind.SKELLIGE_STORM: _apply_weather_card,
    AbilityKind.CLEAR_WEATHER: _apply_clear_weather,
    AbilityKind.SCORCH: _apply_scorch,
    AbilityKind.DECOY: _apply_decoy,
}
