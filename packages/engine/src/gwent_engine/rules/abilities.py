from collections.abc import Callable
from dataclasses import dataclass, replace

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import (
    AbilityKind,
    EffectSourceCategory,
    GameStatus,
    Phase,
    Row,
    Zone,
)
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import (
    CardPlayedEvent,
    CardsDrawnEvent,
    GameEvent,
    MedicResolvedEvent,
    MusterResolvedEvent,
    SpecialCardResolvedEvent,
    SpyResolvedEvent,
    UnitHornActivatedEvent,
    UnitHornSuppressedEvent,
    UnitScorchResolvedEvent,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState, RowState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.avenger import resolve_leave_battlefield_triggers
from gwent_engine.rules.effect_applicability import (
    can_target_for_medic,
    eligible_destroyable_unit_ids,
)
from gwent_engine.rules.event_builder import EventBuilder
from gwent_engine.rules.leader_effects import restore_selection_is_randomized
from gwent_engine.rules.mardroeme import apply_berserker_transformations_for_row
from gwent_engine.rules.players import (
    opponent_player_id_from_state,
    other_player_from_state,
    replace_player,
)
from gwent_engine.rules.row_effects import horn_source_for_row, row_has_active_mardroeme
from gwent_engine.rules.state_ops import (
    append_to_row,
    drawable_card_ids,
    next_player_after_non_pass_action,
    remove_from_play_source_zone,
    replace_card_instance,
    replace_card_instances,
)

type AfterUnitPlayedHandler = Callable[
    [GameState, CardInstanceId, PlayerId, "AbilityResolutionContext"],
    GameState,
]
type PlayDestinationModifier = Callable[[GameState, PlayerId], PlayerId]


@dataclass(slots=True)
class AbilityResolutionContext:
    card_registry: CardRegistry
    leader_registry: LeaderRegistry | None
    rng: SupportsRandom | None
    event_builder: EventBuilder
    medic_targets: dict[CardInstanceId, CardInstanceId]
    reserved_muster_card_ids: set[CardInstanceId]


def apply_unit_card(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    assert action.target_row is not None

    medic_targets: dict[CardInstanceId, CardInstanceId] = {}
    if action.target_card_instance_id is not None:
        medic_targets[action.card_instance_id] = action.target_card_instance_id
    if (
        action.target_card_instance_id is not None
        and action.secondary_target_card_instance_id is not None
    ):
        medic_targets[action.target_card_instance_id] = action.secondary_target_card_instance_id

    context = AbilityResolutionContext(
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
        event_builder=EventBuilder(base_event_counter=state.event_counter),
        medic_targets=medic_targets,
        reserved_muster_card_ids=set(),
    )
    next_state = _play_unit_card_instance(
        state,
        card_instance_id=action.card_instance_id,
        source_zone=Zone.HAND,
        played_by_player_id=action.player_id,
        target_row=action.target_row,
        preferred_row=action.target_row,
        context=context,
    )
    next_state = replace(
        next_state,
        current_player=next_player_after_non_pass_action(state, action.player_id),
        phase=Phase.IN_ROUND,
        status=GameStatus.IN_PROGRESS,
        event_counter=state.event_counter + len(context.event_builder.build()),
    )
    return next_state, context.event_builder.build()


def strongest_battlefield_unit_card_ids(
    state: GameState,
    card_registry: CardRegistry,
    *,
    source_category: EffectSourceCategory,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[CardInstanceId, ...]:
    from gwent_engine.rules.scoring import calculate_effective_strength

    battlefield_card_ids = tuple(
        card.instance_id for card in state.card_instances if card.zone == Zone.BATTLEFIELD
    )
    eligible_card_ids = eligible_destroyable_unit_ids(
        state,
        card_registry,
        battlefield_card_ids,
        source_category=source_category,
    )
    if not eligible_card_ids:
        return ()
    strongest_strength = max(
        calculate_effective_strength(
            state,
            card_registry,
            card_id,
            leader_registry=leader_registry,
        )
        for card_id in eligible_card_ids
    )
    return tuple(
        card.instance_id
        for card in state.card_instances
        if card.instance_id in eligible_card_ids
        and calculate_effective_strength(
            state,
            card_registry,
            card.instance_id,
            leader_registry=leader_registry,
        )
        == strongest_strength
    )


def destroy_battlefield_cards(
    state: GameState,
    destroyed_card_ids: tuple[CardInstanceId, ...],
    *,
    card_registry: CardRegistry,
    event_id_start: int,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    removed_cards = tuple(state.card(card_id) for card_id in destroyed_card_ids)
    updated_cards = {
        card_id: replace(
            state.card(card_id),
            zone=Zone.DISCARD,
            row=None,
            battlefield_side=None,
        )
        for card_id in destroyed_card_ids
    }
    updated_players = tuple(
        _destroy_player_cards(state, player, destroyed_card_ids) for player in state.players
    )
    next_state = replace(
        state,
        players=(updated_players[0], updated_players[1]),
        card_instances=replace_card_instances(state.card_instances, updated_cards),
    )
    return resolve_leave_battlefield_triggers(
        next_state,
        removed_cards,
        card_registry=card_registry,
        event_id_start=event_id_start,
        queue_for_next_round=False,
    )


def _play_unit_card_instance(
    state: GameState,
    *,
    card_instance_id: CardInstanceId,
    source_zone: Zone,
    played_by_player_id: PlayerId,
    target_row: Row | None,
    preferred_row: Row | None,
    context: AbilityResolutionContext,
) -> GameState:
    definition = context.card_registry.get(state.card(card_instance_id).definition_id)
    resolved_target_row = _resolve_target_row(
        definition,
        target_row=target_row,
        preferred_row=preferred_row,
    )
    battlefield_side = modify_play_destination(
        state,
        card_instance_id=card_instance_id,
        played_by_player_id=played_by_player_id,
        card_registry=context.card_registry,
    )
    next_state = play_card_instance(
        state,
        card_instance_id=card_instance_id,
        source_zone=source_zone,
        battlefield_side_player_id=battlefield_side,
        target_row=resolved_target_row,
        played_by_player_id=played_by_player_id,
        context=context,
    )
    return _resolve_after_unit_played(
        next_state,
        card_instance_id=card_instance_id,
        played_by_player_id=played_by_player_id,
        context=context,
    )


def play_card_instance(
    state: GameState,
    *,
    card_instance_id: CardInstanceId,
    source_zone: Zone,
    battlefield_side_player_id: PlayerId,
    target_row: Row,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    owner_id = state.card(card_instance_id).owner
    updated_players: list[PlayerState] = []
    for player in state.players:
        updated_player = player
        if player.player_id == owner_id:
            updated_player = remove_from_play_source_zone(
                updated_player,
                source_zone,
                card_instance_id,
            )
        if player.player_id == battlefield_side_player_id:
            updated_player = replace(
                updated_player,
                rows=append_to_row(updated_player.rows, target_row, card_instance_id),
            )
        updated_players.append(updated_player)

    updated_card = replace(
        state.card(card_instance_id),
        zone=Zone.BATTLEFIELD,
        row=target_row,
        battlefield_side=battlefield_side_player_id,
    )
    _append_event(
        context,
        CardPlayedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            target_row=target_row,
        ),
    )
    return replace(
        state,
        players=(updated_players[0], updated_players[1]),
        card_instances=replace_card_instance(state.card_instances, updated_card),
    )


def modify_play_destination(
    state: GameState,
    *,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    card_registry: CardRegistry,
) -> PlayerId:
    definition = card_registry.get(state.card(card_instance_id).definition_id)
    battlefield_side = played_by_player_id
    for ability_kind in definition.ability_kinds:
        modifier = PLAY_DESTINATION_MODIFIERS.get(ability_kind)
        if modifier is not None:
            battlefield_side = modifier(state, played_by_player_id)
    return battlefield_side


def _resolve_after_unit_played(
    state: GameState,
    *,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    definition = context.card_registry.get(state.card(card_instance_id).definition_id)
    next_state = state
    for ability_kind in definition.ability_kinds:
        handler = AFTER_UNIT_PLAYED_HANDLERS.get(ability_kind)
        if handler is not None:
            next_state = handler(
                next_state,
                card_instance_id,
                played_by_player_id,
                context,
            )
    return next_state


def _resolve_spy_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    player = state.player(played_by_player_id)
    drawn_card_ids = drawable_card_ids(player, 2)
    updated_player = replace(
        player,
        deck=player.deck[len(drawn_card_ids) :],
        hand=(*player.hand, *drawn_card_ids),
    )
    updated_cards = {
        drawn_card_id: replace(
            state.card(drawn_card_id),
            zone=Zone.HAND,
            row=None,
            battlefield_side=None,
        )
        for drawn_card_id in drawn_card_ids
    }
    next_state = replace(
        state,
        players=replace_player(state.players, updated_player),
        card_instances=replace_card_instances(state.card_instances, updated_cards),
    )
    if drawn_card_ids:
        _append_event(
            context,
            CardsDrawnEvent(
                event_id=_next_event_id(context),
                player_id=played_by_player_id,
                card_instance_ids=drawn_card_ids,
            ),
        )
    _append_event(
        context,
        SpyResolvedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            drawn_card_instance_ids=drawn_card_ids,
        ),
    )
    return next_state


def _resolve_medic_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    current_state = state
    resurrected_card_id: CardInstanceId | None = None
    eligible_target_ids = _eligible_medic_target_ids(
        current_state,
        card_registry=context.card_registry,
        player_id=played_by_player_id,
    )
    target_card_id = _select_medic_target_after_play(
        current_state,
        card_instance_id,
        eligible_target_ids,
        context,
    )
    if target_card_id is not None and target_card_id in eligible_target_ids:
        resurrected_card_id = target_card_id
        current_state = _play_unit_card_instance(
            current_state,
            card_instance_id=target_card_id,
            source_zone=Zone.DISCARD,
            played_by_player_id=played_by_player_id,
            target_row=None,
            preferred_row=None,
            context=context,
        )
    _append_event(
        context,
        MedicResolvedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            resurrected_card_instance_id=resurrected_card_id,
        ),
    )
    return current_state


def _select_medic_target_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    eligible_target_ids: tuple[CardInstanceId, ...],
    context: AbilityResolutionContext,
) -> CardInstanceId | None:
    if restore_selection_is_randomized(state, context.leader_registry):
        return _select_randomized_medic_target(eligible_target_ids, context)
    return _select_explicit_or_fallback_medic_target(
        card_instance_id,
        eligible_target_ids,
        context,
    )


def _select_randomized_medic_target(
    eligible_target_ids: tuple[CardInstanceId, ...],
    context: AbilityResolutionContext,
) -> CardInstanceId | None:
    if not eligible_target_ids:
        return None
    if context.rng is None:
        raise IllegalActionError("Randomized restoration requires an injected RNG.")
    return context.rng.choice(eligible_target_ids)


def _select_explicit_or_fallback_medic_target(
    card_instance_id: CardInstanceId,
    eligible_target_ids: tuple[CardInstanceId, ...],
    context: AbilityResolutionContext,
) -> CardInstanceId | None:
    target_card_id = context.medic_targets.pop(card_instance_id, None)
    if target_card_id is not None or not eligible_target_ids:
        return target_card_id
    # Internal recursive Medic chains use a deterministic first-eligible fallback
    # until the engine grows a richer multi-choice payload.
    return eligible_target_ids[0]


def _resolve_muster_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    definition = context.card_registry.get(state.card(card_instance_id).definition_id)
    muster_group = definition.resolved_musters_group
    assert muster_group is not None

    mustered_card_ids = tuple(
        deck_card_id
        for deck_card_id in state.player(played_by_player_id).deck
        if deck_card_id not in context.reserved_muster_card_ids
        if _belongs_to_muster_group(
            state,
            context.card_registry,
            deck_card_id,
            muster_group,
        )
    )
    preferred_row = state.card(card_instance_id).row
    current_state = state
    played_card_ids: list[CardInstanceId] = []
    context.reserved_muster_card_ids.update(mustered_card_ids)
    for mustered_card_id in mustered_card_ids:
        if current_state.card(mustered_card_id).zone != Zone.DECK:
            continue
        current_state = _play_unit_card_instance(
            current_state,
            card_instance_id=mustered_card_id,
            source_zone=Zone.DECK,
            played_by_player_id=played_by_player_id,
            target_row=None,
            preferred_row=preferred_row,
            context=context,
        )
        played_card_ids.append(mustered_card_id)
    context.reserved_muster_card_ids.difference_update(mustered_card_ids)
    _append_event(
        context,
        MusterResolvedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            mustered_card_instance_ids=tuple(played_card_ids),
        ),
    )
    return current_state


def _eligible_medic_target_ids(
    state: GameState,
    *,
    card_registry: CardRegistry,
    player_id: PlayerId,
) -> tuple[CardInstanceId, ...]:
    return tuple(
        card_id
        for card_id in state.player(player_id).discard
        if can_target_for_medic(
            state,
            card_registry,
            player=state.player(player_id),
            target_card_id=card_id,
        )
    )


def _resolve_unit_horn_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    card = state.card(card_instance_id)
    assert card.row is not None
    assert card.battlefield_side is not None
    active_horn_source = horn_source_for_row(
        state,
        context.card_registry,
        card.battlefield_side,
        card.row,
    )
    assert active_horn_source is not None
    if active_horn_source.source_card_instance_id == card_instance_id:
        _append_event(
            context,
            UnitHornActivatedEvent(
                event_id=_next_event_id(context),
                player_id=played_by_player_id,
                card_instance_id=card_instance_id,
                affected_row=card.row,
            ),
        )
        return state
    _append_event(
        context,
        UnitHornSuppressedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            affected_row=card.row,
            active_source_category=active_horn_source.source_category,
            active_source_card_instance_id=active_horn_source.source_card_instance_id,
            active_source_leader_id=active_horn_source.source_leader_id,
        ),
    )
    return state


def _resolve_unit_scorch_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    from gwent_engine.rules.scoring import calculate_effective_strength

    card = state.card(card_instance_id)
    assert card.row is not None
    assert card.battlefield_side is not None
    opponent = other_player_from_state(state, card.battlefield_side)
    affected_row = card.row
    opponent_row_cards = opponent.rows.cards_for(affected_row)
    row_total = sum(
        calculate_effective_strength(
            state,
            context.card_registry,
            row_card_id,
            leader_registry=context.leader_registry,
        )
        for row_card_id in opponent_row_cards
    )
    destroyed_card_ids: tuple[CardInstanceId, ...] = ()
    next_state = state
    eligible_targets = eligible_destroyable_unit_ids(
        state,
        context.card_registry,
        opponent_row_cards,
        source_category=EffectSourceCategory.UNIT_ABILITY,
    )
    if row_total >= 10 and eligible_targets:
        strongest_strength = max(
            calculate_effective_strength(
                state,
                context.card_registry,
                row_card_id,
                leader_registry=context.leader_registry,
            )
            for row_card_id in eligible_targets
        )
        destroyed_card_ids = tuple(
            row_card_id
            for row_card_id in opponent_row_cards
            if row_card_id in eligible_targets
            and calculate_effective_strength(
                state,
                context.card_registry,
                row_card_id,
                leader_registry=context.leader_registry,
            )
            == strongest_strength
        )
        if destroyed_card_ids:
            next_state, destroy_events = destroy_battlefield_cards(
                state,
                destroyed_card_ids,
                card_registry=context.card_registry,
                event_id_start=_next_event_id(context),
            )
            for event in destroy_events:
                _append_event(context, event)
    _append_event(
        context,
        UnitScorchResolvedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            affected_row=affected_row,
            destroyed_card_instance_ids=destroyed_card_ids,
        ),
    )
    return next_state


def _resolve_global_unit_scorch_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    destroyed_card_ids = strongest_battlefield_unit_card_ids(
        state,
        context.card_registry,
        source_category=EffectSourceCategory.UNIT_ABILITY,
        leader_registry=context.leader_registry,
    )
    next_state = state
    if destroyed_card_ids:
        next_state, destroy_events = destroy_battlefield_cards(
            state,
            destroyed_card_ids,
            card_registry=context.card_registry,
            event_id_start=_next_event_id(context),
        )
        for event in destroy_events:
            _append_event(context, event)
    _append_event(
        context,
        SpecialCardResolvedEvent(
            event_id=_next_event_id(context),
            player_id=played_by_player_id,
            card_instance_id=card_instance_id,
            ability_kind=AbilityKind.SCORCH,
            discarded_card_instance_ids=destroyed_card_ids,
        ),
    )
    return next_state


def _resolve_berserker_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    del played_by_player_id
    card = state.card(card_instance_id)
    if card.row is None or card.battlefield_side is None:
        return state
    if not row_has_active_mardroeme(
        state,
        context.card_registry,
        card.battlefield_side,
        card.row,
    ):
        return state
    next_state, transform_events = apply_berserker_transformations_for_row(
        state,
        card_registry=context.card_registry,
        battlefield_side=card.battlefield_side,
        row=card.row,
        event_id_start=_next_event_id(context),
    )
    for event in transform_events:
        _append_event(context, event)
    return next_state


def _resolve_unit_source_mardroeme_after_play(
    state: GameState,
    card_instance_id: CardInstanceId,
    played_by_player_id: PlayerId,
    context: AbilityResolutionContext,
) -> GameState:
    del played_by_player_id
    card = state.card(card_instance_id)
    if card.row is None or card.battlefield_side is None:
        return state
    next_state, transform_events = apply_berserker_transformations_for_row(
        state,
        card_registry=context.card_registry,
        battlefield_side=card.battlefield_side,
        row=card.row,
        event_id_start=_next_event_id(context),
    )
    for event in transform_events:
        _append_event(context, event)
    return next_state


def _belongs_to_muster_group(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    muster_group: str,
) -> bool:
    return _card_group_matches(
        state,
        card_registry,
        card_id,
        group_for_definition=lambda definition: definition.muster_group,
        group=muster_group,
    )


def _card_group_matches(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
    *,
    group_for_definition: Callable[[CardDefinition], str | None],
    group: str,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return group_for_definition(definition) == group


def _resolve_target_row(
    definition: CardDefinition,
    *,
    target_row: Row | None,
    preferred_row: Row | None,
) -> Row:
    if target_row is not None:
        return target_row
    if preferred_row is not None and preferred_row in definition.allowed_rows:
        return preferred_row
    return definition.allowed_rows[0]


def _append_event(context: AbilityResolutionContext, event: GameEvent) -> None:
    context.event_builder.append(event)


def _next_event_id(context: AbilityResolutionContext) -> int:
    return context.event_builder.next_event_id()


def _spy_destination(state: GameState, played_by_player_id: PlayerId) -> PlayerId:
    return opponent_player_id_from_state(state, played_by_player_id)


def _destroy_player_cards(
    state: GameState,
    player: PlayerState,
    destroyed_card_ids: tuple[CardInstanceId, ...],
) -> PlayerState:
    removed_row_cards = tuple(
        card_id for card_id in player.rows.all_cards() if card_id in destroyed_card_ids
    )
    owned_destroyed_cards = tuple(
        card_id for card_id in destroyed_card_ids if state.card(card_id).owner == player.player_id
    )
    return replace(
        player,
        discard=player.discard + owned_destroyed_cards,
        rows=_remove_cards_from_rows(player.rows, removed_row_cards),
    )


def _remove_cards_from_rows(
    rows: RowState,
    removed_card_ids: tuple[CardInstanceId, ...],
) -> RowState:
    removed = set(removed_card_ids)
    return RowState(
        close=tuple(card_id for card_id in rows.close if card_id not in removed),
        ranged=tuple(card_id for card_id in rows.ranged if card_id not in removed),
        siege=tuple(card_id for card_id in rows.siege if card_id not in removed),
    )


PLAY_DESTINATION_MODIFIERS: dict[AbilityKind, PlayDestinationModifier] = {
    AbilityKind.SPY: _spy_destination,
}

AFTER_UNIT_PLAYED_HANDLERS: dict[AbilityKind, AfterUnitPlayedHandler] = {
    AbilityKind.SPY: _resolve_spy_after_play,
    AbilityKind.MEDIC: _resolve_medic_after_play,
    AbilityKind.MUSTER: _resolve_muster_after_play,
    AbilityKind.SCORCH: _resolve_global_unit_scorch_after_play,
    AbilityKind.UNIT_COMMANDERS_HORN: _resolve_unit_horn_after_play,
    AbilityKind.UNIT_SCORCH_ROW: _resolve_unit_scorch_after_play,
    AbilityKind.BERSERKER: _resolve_berserker_after_play,
    AbilityKind.MARDROEME: _resolve_unit_source_mardroeme_after_play,
}
