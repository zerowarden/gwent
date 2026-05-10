from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import (
    EffectSourceCategory,
    GameStatus,
    LeaderAbilityKind,
    LeaderAbilityMode,
    Phase,
    Zone,
)
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import CardsDrawnEvent, GameEvent, LeaderAbilityResolvedEvent
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import CardInstance, GameState, PlayerState, RowState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.abilities import destroy_battlefield_cards
from gwent_engine.rules.battlefield_effects import weather_row_for
from gwent_engine.rules.effect_applicability import eligible_destroyable_unit_ids
from gwent_engine.rules.leader_common import (
    ActiveLeaderHandler,
    is_agile_battlefield_unit,
    move_battlefield_card_to_row,
    pick_random_card_ids,
    resolve_discard_and_choose_from_deck_selection,
    selected_weather_card_in_deck,
)
from gwent_engine.rules.leader_effects import (
    enabled_leader_definition_for_player,
    leader_definition_for_player,
)
from gwent_engine.rules.players import other_player_from_pair, replace_player
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.scoring import calculate_effective_strength
from gwent_engine.rules.state_ops import (
    append_to_row,
    discard_owned_weather_cards,
    drawable_card_ids,
    next_player_after_non_pass_action,
    replace_card_instance,
    replace_card_instances,
)


def resolve_setup_passive_leader_effects(
    state: GameState,
    *,
    leader_registry: LeaderRegistry | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if leader_registry is None:
        return state, ()

    current_state, disable_events = _resolve_disable_opponent_leader_passives(
        state,
        leader_registry=leader_registry,
    )
    events: list[GameEvent] = list(disable_events)
    for player in state.players:
        owner = current_state.player(player.player_id)
        leader_definition = enabled_leader_definition_for_player(owner, leader_registry)
        if leader_definition is None or leader_definition.ability_mode != LeaderAbilityMode.PASSIVE:
            continue
        if leader_definition.ability_kind == LeaderAbilityKind.DRAW_EXTRA_OPENING_CARD:
            current_state, passive_events = _resolve_draw_extra_opening_card(
                current_state,
                owner,
                leader_definition,
            )
            events.extend(passive_events)
    return current_state, tuple(events)


def apply_use_leader_ability(
    state: GameState,
    action: UseLeaderAbilityAction,
    *,
    leader_registry: LeaderRegistry,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    player = state.player(action.player_id)
    leader_definition = leader_definition_for_player(player, leader_registry)
    handler = ACTIVE_LEADER_HANDLERS[leader_definition.ability_kind]
    next_state, events = handler(
        state,
        player,
        leader_definition,
        action,
        card_registry,
        rng,
        leader_registry,
    )
    resolved_player = next_state.player(action.player_id)
    updated_player = replace(
        resolved_player,
        leader=replace(resolved_player.leader, used=True),
    )
    final_state = replace(
        next_state,
        players=replace_player(next_state.players, updated_player),
        current_player=next_player_after_non_pass_action(next_state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(events),
    )
    return final_state, events


def _resolve_disable_opponent_leader_passives(
    state: GameState,
    *,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    disablers = tuple(
        player
        for player in state.players
        if (leader_definition := enabled_leader_definition_for_player(player, leader_registry))
        is not None
        and leader_definition.ability_kind == LeaderAbilityKind.DISABLE_OPPONENT_LEADER
    )
    if not disablers:
        return state, ()

    targets_to_disable = frozenset(
        other_player_from_pair(state.players, player.player_id).player_id for player in disablers
    )
    updated_players = tuple(
        replace(player, leader=replace(player.leader, disabled=True))
        if player.player_id in targets_to_disable
        else player
        for player in state.players
    )
    events = tuple(
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + index,
            player_id=player.player_id,
            leader_id=player.leader.leader_id,
            ability_kind=LeaderAbilityKind.DISABLE_OPPONENT_LEADER,
            ability_mode=LeaderAbilityMode.PASSIVE,
            disabled_player_id=other_player_from_pair(state.players, player.player_id).player_id,
        )
        for index, player in enumerate(disablers, start=1)
    )
    return (
        replace(
            state,
            players=(updated_players[0], updated_players[1]),
            event_counter=state.event_counter + len(events),
        ),
        events,
    )


def _resolve_draw_extra_opening_card(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    drawn_card_ids = drawable_card_ids(player, leader_definition.cards_to_draw)
    if not drawn_card_ids:
        return state, ()

    updated_player = replace(
        player,
        deck=player.deck[len(drawn_card_ids) :],
        hand=(*player.hand, *drawn_card_ids),
    )
    updated_cards = {
        card_id: replace(
            state.card(card_id),
            zone=Zone.HAND,
            row=None,
            battlefield_side=None,
        )
        for card_id in drawn_card_ids
    }
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            drawn_card_instance_ids=drawn_card_ids,
        ),
        CardsDrawnEvent(
            event_id=state.event_counter + 2,
            player_id=player.player_id,
            card_instance_ids=drawn_card_ids,
        ),
    )
    next_state = replace(
        state,
        players=replace_player(state.players, updated_player),
        card_instances=replace_card_instances(state.card_instances, updated_cards),
        event_counter=state.event_counter + len(events),
    )
    return next_state, events


def _activate_clear_weather_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, card_registry, rng, leader_registry
    cleared_weather_ids = state.battlefield_weather.all_cards()
    updated_players = tuple(
        discard_owned_weather_cards(state, current_player, cleared_weather_ids)
        for current_player in state.players
    )
    updated_cards = {
        card_id: replace(
            state.card(card_id),
            zone=Zone.DISCARD,
            row=None,
            battlefield_side=None,
        )
        for card_id in cleared_weather_ids
    }
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            discarded_card_instance_ids=cleared_weather_ids,
        ),
    )
    return (
        replace(
            state,
            players=(updated_players[0], updated_players[1]),
            card_instances=replace_card_instances(state.card_instances, updated_cards),
            weather=RowState(),
        ),
        events,
    )


def _activate_play_weather_from_deck_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del rng, leader_registry
    chosen_card_id = selected_weather_card_in_deck(
        state,
        player,
        leader_definition,
        action,
        card_registry,
    )
    if chosen_card_id is None:
        raise IllegalActionError("Leader requires a matching weather card in deck.")
    weather_definition = card_registry.get(state.card(chosen_card_id).definition_id)
    affected_row = weather_row_for(special_ability_kind(weather_definition))
    updated_player = replace(
        player,
        deck=tuple(card_id for card_id in player.deck if card_id != chosen_card_id),
    )
    updated_card = replace(
        state.card(chosen_card_id),
        zone=Zone.WEATHER,
        row=affected_row,
        battlefield_side=None,
    )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            affected_row=affected_row,
            played_card_instance_id=chosen_card_id,
        ),
    )
    return (
        replace(
            state,
            players=replace_player(state.players, updated_player),
            card_instances=replace_card_instance(state.card_instances, updated_card),
            weather=append_to_row(state.weather, affected_row, chosen_card_id),
        ),
        events,
    )


def _activate_horn_own_row_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, card_registry, rng, leader_registry
    assert leader_definition.affected_row is not None
    updated_player = replace(
        player,
        leader=replace(player.leader, horn_row=leader_definition.affected_row),
    )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            affected_row=leader_definition.affected_row,
        ),
    )
    return replace(state, players=replace_player(state.players, updated_player)), events


def _activate_scorch_opponent_row_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, rng
    assert leader_definition.affected_row is not None
    opponent = other_player_from_pair(state.players, player.player_id)
    affected_row = leader_definition.affected_row
    opponent_row_cards = opponent.rows.cards_for(affected_row)
    row_total = sum(
        calculate_effective_strength(
            state,
            card_registry,
            card_id,
            leader_registry=leader_registry,
        )
        for card_id in opponent_row_cards
    )
    destroyed_card_ids: tuple[CardInstanceId, ...] = ()
    next_state = state
    destroy_events: tuple[GameEvent, ...] = ()
    eligible_targets = eligible_destroyable_unit_ids(
        state,
        card_registry,
        opponent_row_cards,
        source_category=EffectSourceCategory.LEADER_ABILITY,
    )
    if row_total >= leader_definition.minimum_opponent_row_total and eligible_targets:
        strongest_strength = max(
            calculate_effective_strength(
                state,
                card_registry,
                card_id,
                leader_registry=leader_registry,
            )
            for card_id in eligible_targets
        )
        destroyed_card_ids = tuple(
            card_id
            for card_id in opponent_row_cards
            if card_id in eligible_targets
            and calculate_effective_strength(
                state,
                card_registry,
                card_id,
                leader_registry=leader_registry,
            )
            == strongest_strength
        )
        if destroyed_card_ids:
            next_state, destroy_events = destroy_battlefield_cards(
                state,
                destroyed_card_ids,
                card_registry=card_registry,
                event_id_start=state.event_counter + 2,
            )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            affected_row=affected_row,
            discarded_card_instance_ids=destroyed_card_ids,
        ),
        *destroy_events,
    )
    return next_state, events


def _activate_discard_and_choose_from_deck_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del card_registry, rng, leader_registry
    if not action.selected_card_instance_ids:
        return _resolve_discard_and_choose_without_selection(state, player, leader_definition)
    discarded_card_ids, drawn_card_ids = resolve_discard_and_choose_from_deck_selection(
        player,
        leader_definition,
        action.selected_card_instance_ids,
    )
    selected_ids = set(action.selected_card_instance_ids)
    updated_player = replace(
        player,
        deck=tuple(card_id for card_id in player.deck if card_id not in selected_ids),
        hand=tuple(card_id for card_id in player.hand if card_id not in selected_ids)
        + drawn_card_ids,
        discard=player.discard + discarded_card_ids,
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
    updated_cards.update(
        {
            card_id: replace(
                state.card(card_id),
                zone=Zone.HAND,
                row=None,
                battlefield_side=None,
            )
            for card_id in drawn_card_ids
        }
    )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            discarded_card_instance_ids=discarded_card_ids,
            drawn_card_instance_ids=drawn_card_ids,
        ),
    )
    return (
        replace(
            state,
            players=replace_player(state.players, updated_player),
            card_instances=replace_card_instances(state.card_instances, updated_cards),
        ),
        events,
    )


def _resolve_discard_and_choose_without_selection(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if _leader_requires_discard_and_pick_selection(player, leader_definition):
        raise IllegalActionError(
            "Leader requires a pending discard-and-pick selection before resolving."
        )
    return (
        state,
        (
            LeaderAbilityResolvedEvent(
                event_id=state.event_counter + 1,
                player_id=player.player_id,
                leader_id=leader_definition.leader_id,
                ability_kind=leader_definition.ability_kind,
                ability_mode=leader_definition.ability_mode,
            ),
        ),
    )


def _leader_requires_discard_and_pick_selection(
    player: PlayerState,
    leader_definition: LeaderDefinition,
) -> bool:
    return (
        len(player.hand) >= leader_definition.hand_discard_count
        and len(player.deck) >= leader_definition.deck_pick_count
    )


def _activate_discard_to_hand_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del card_registry, rng, leader_registry
    if action.target_card_instance_id is None:
        return _leader_no_target_resolution(state, player, leader_definition)
    source = player
    missing_target_message = "Leader target must be a card in your own discard pile."
    if leader_definition.ability_kind == LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND:
        source = other_player_from_pair(state.players, player.player_id)
        missing_target_message = "Leader target must be a card in the opponent discard pile."
    return _move_discard_card_to_leader_hand(
        state,
        receiver=player,
        source=source,
        leader_definition=leader_definition,
        card_id=action.target_card_instance_id,
        missing_target_message=missing_target_message,
    )


def _activate_reveal_random_opponent_hand_cards_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, card_registry, leader_registry
    if rng is None:
        raise IllegalActionError("Random reveal leader abilities require an injected RNG.")
    opponent = other_player_from_pair(state.players, player.player_id)
    revealed_card_ids = pick_random_card_ids(
        opponent.hand,
        min(len(opponent.hand), leader_definition.reveal_count),
        rng=rng,
    )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            revealed_card_instance_ids=revealed_card_ids,
        ),
    )
    return state, events


def _leader_no_target_resolution(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    return (
        state,
        (
            LeaderAbilityResolvedEvent(
                event_id=state.event_counter + 1,
                player_id=player.player_id,
                leader_id=leader_definition.leader_id,
                ability_kind=leader_definition.ability_kind,
                ability_mode=leader_definition.ability_mode,
            ),
        ),
    )


def _move_discard_card_to_leader_hand(
    state: GameState,
    *,
    receiver: PlayerState,
    source: PlayerState,
    leader_definition: LeaderDefinition,
    card_id: CardInstanceId,
    missing_target_message: str,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if card_id not in source.discard:
        raise IllegalActionError(missing_target_message)

    if receiver.player_id == source.player_id:
        updated_receiver = replace(
            receiver,
            hand=(*receiver.hand, card_id),
            discard=_without_card(source.discard, card_id),
        )
        updated_players = replace_player(state.players, updated_receiver)
    else:
        updated_receiver = replace(receiver, hand=(*receiver.hand, card_id))
        updated_source = replace(
            source,
            discard=_without_card(source.discard, card_id),
        )
        updated_players = replace_player(
            replace_player(state.players, updated_receiver),
            updated_source,
        )

    updated_card = replace(
        state.card(card_id),
        owner=receiver.player_id,
        zone=Zone.HAND,
        row=None,
        battlefield_side=None,
    )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=receiver.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            target_card_instance_id=card_id,
            returned_card_instance_ids=(card_id,),
        ),
    )
    return (
        replace(
            state,
            players=updated_players,
            card_instances=replace_card_instance(state.card_instances, updated_card),
        ),
        events,
    )


def _without_card(
    card_ids: tuple[CardInstanceId, ...],
    card_id_to_remove: CardInstanceId,
) -> tuple[CardInstanceId, ...]:
    return tuple(card_id for card_id in card_ids if card_id != card_id_to_remove)


def _activate_optimize_agile_rows_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, rng
    current_state = state
    moved_card_ids: list[CardInstanceId] = []
    agile_card_ids = tuple(
        card.instance_id
        for card in current_state.card_instances
        if card.zone == Zone.BATTLEFIELD
        and card.row is not None
        and is_agile_battlefield_unit(current_state, card_registry, card.instance_id)
    )
    for card_id in agile_card_ids:
        card = current_state.card(card_id)
        assert card.row is not None
        current_row = card.row
        best_row = current_row
        best_strength = calculate_effective_strength(
            current_state,
            card_registry,
            card_id,
            leader_registry=leader_registry,
        )
        for candidate_row in card_registry.get(card.definition_id).allowed_rows:
            if candidate_row == current_row:
                continue
            simulated_state = move_battlefield_card_to_row(current_state, card_id, candidate_row)
            candidate_strength = calculate_effective_strength(
                simulated_state,
                card_registry,
                card_id,
                leader_registry=leader_registry,
            )
            if candidate_strength > best_strength:
                best_strength = candidate_strength
                best_row = candidate_row
        if best_row != current_row:
            current_state = move_battlefield_card_to_row(current_state, card_id, best_row)
            moved_card_ids.append(card_id)
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            moved_card_instance_ids=tuple(moved_card_ids),
        ),
    )
    return current_state, events


def _activate_shuffle_all_discards_into_decks_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
    leader_registry: LeaderRegistry,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    del action, card_registry, leader_registry
    if rng is None:
        raise IllegalActionError("Shuffle leader abilities require an injected RNG.")
    shuffled_card_ids = tuple(
        card_id for player_state in state.players for card_id in player_state.discard
    )
    updated_players: list[PlayerState] = []
    updated_cards: dict[CardInstanceId, CardInstance] = {}
    for player_state in state.players:
        shuffled_deck = list((*player_state.deck, *player_state.discard))
        rng.shuffle(shuffled_deck)
        updated_players.append(
            replace(
                player_state,
                deck=tuple(shuffled_deck),
                discard=(),
            )
        )
        for card_id in player_state.discard:
            updated_cards[card_id] = replace(
                state.card(card_id),
                zone=Zone.DECK,
                row=None,
                battlefield_side=None,
            )
    events: tuple[GameEvent, ...] = (
        LeaderAbilityResolvedEvent(
            event_id=state.event_counter + 1,
            player_id=player.player_id,
            leader_id=leader_definition.leader_id,
            ability_kind=leader_definition.ability_kind,
            ability_mode=leader_definition.ability_mode,
            shuffled_card_instance_ids=shuffled_card_ids,
        ),
    )
    return (
        replace(
            state,
            players=(updated_players[0], updated_players[1]),
            card_instances=replace_card_instances(state.card_instances, updated_cards),
        ),
        events,
    )


ACTIVE_LEADER_HANDLERS: dict[LeaderAbilityKind, ActiveLeaderHandler] = {
    LeaderAbilityKind.CLEAR_WEATHER: _activate_clear_weather_leader,
    LeaderAbilityKind.PLAY_WEATHER_FROM_DECK: _activate_play_weather_from_deck_leader,
    LeaderAbilityKind.HORN_OWN_ROW: _activate_horn_own_row_leader,
    LeaderAbilityKind.SCORCH_OPPONENT_ROW: _activate_scorch_opponent_row_leader,
    LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK: _activate_discard_and_choose_from_deck_leader,
    LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND: _activate_discard_to_hand_leader,
    LeaderAbilityKind.REVEAL_RANDOM_OPPONENT_HAND_CARDS: (
        _activate_reveal_random_opponent_hand_cards_leader
    ),
    LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND: _activate_discard_to_hand_leader,
    LeaderAbilityKind.OPTIMIZE_AGILE_ROWS: _activate_optimize_agile_rows_leader,
    LeaderAbilityKind.SHUFFLE_ALL_DISCARDS_INTO_DECKS: (
        _activate_shuffle_all_discards_into_decks_leader
    ),
}
