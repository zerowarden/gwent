from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import GameEvent
from gwent_engine.core.invariants import check_game_state_invariants
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState
from gwent_engine.core.validators import (
    validate_leave_action,
    validate_pass_action,
    validate_play_card_action,
    validate_resolve_choice_action,
    validate_resolve_mulligans_action,
    validate_start_game_action,
    validate_use_leader_ability_action,
)
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.forfeit import apply_leave
from gwent_engine.rules.game_setup import apply_mulligan, apply_start_game
from gwent_engine.rules.leader_abilities import apply_use_leader_ability
from gwent_engine.rules.pending_choices import (
    maybe_create_pending_choice_for_leader,
    maybe_create_pending_choice_for_play,
    resolve_pending_choice,
)
from gwent_engine.rules.trigger_resolution import resolve_post_action_transitions
from gwent_engine.rules.turn_flow import apply_pass, apply_play_card


def apply_action(
    state: GameState,
    action: GameAction,
    *,
    rng: SupportsRandom | None = None,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    next_state, events, _ = apply_action_with_intermediate_state(
        state,
        action,
        rng=rng,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )
    return next_state, events


def apply_action_with_intermediate_state(
    state: GameState,
    action: GameAction,
    *,
    rng: SupportsRandom | None = None,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
) -> tuple[GameState, tuple[GameEvent, ...], GameState]:
    if state.pending_choice is not None and not isinstance(action, LeaveAction):
        next_state, events = _resolve_pending_choice(
            state,
            action,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    else:
        next_state, events = _dispatch_action(
            state,
            action,
            rng=rng,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    intermediate_state = next_state
    if next_state.pending_choice is None:
        next_state, triggered_events = resolve_post_action_transitions(
            next_state,
            card_registry=card_registry,
            rng=rng,
            leader_registry=leader_registry,
        )
        events = events + triggered_events
    check_game_state_invariants(next_state, card_registry=card_registry)
    return next_state, events, intermediate_state


def _resolve_pending_choice(
    state: GameState,
    action: GameAction,
    *,
    rng: SupportsRandom | None,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if not isinstance(action, ResolveChoiceAction):
        raise IllegalActionError(
            "A pending choice must be resolved before any other action is legal."
        )
    validate_resolve_choice_action(state, action)
    return resolve_pending_choice(
        state,
        action,
        rng=rng,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )


def _dispatch_action(
    state: GameState,
    action: GameAction,
    *,
    rng: SupportsRandom | None,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    match action:
        case ResolveChoiceAction():
            raise IllegalActionError("ResolveChoiceAction requires a pending choice.")
        case StartGameAction():
            validate_start_game_action(state, action, rng=rng)
            return apply_start_game(
                state,
                action,
                rng=rng,
                leader_registry=leader_registry,
            )
        case ResolveMulligansAction():
            validate_resolve_mulligans_action(state, action)
            return apply_mulligan(state, action)
        case PlayCardAction():
            validate_play_card_action(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
                rng=rng,
            )
            assert card_registry is not None
            pending_choice = maybe_create_pending_choice_for_play(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
            if pending_choice is not None:
                return replace(state, pending_choice=pending_choice), ()
            return apply_play_card(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
                rng=rng,
            )
        case PassAction():
            validate_pass_action(state, action)
            return apply_pass(state, action)
        case LeaveAction():
            validate_leave_action(state, action)
            return apply_leave(state, action)
        case UseLeaderAbilityAction():
            validate_use_leader_ability_action(
                state,
                action,
                leader_registry=leader_registry,
                card_registry=card_registry,
                rng=rng,
            )
            assert leader_registry is not None
            assert card_registry is not None
            pending_choice = maybe_create_pending_choice_for_leader(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
            if pending_choice is not None:
                return replace(state, pending_choice=pending_choice), ()
            return apply_use_leader_ability(
                state,
                action,
                leader_registry=leader_registry,
                card_registry=card_registry,
                rng=rng,
            )
