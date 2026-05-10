from __future__ import annotations

from gwent_shared.error_translation import recover_exception

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


def is_legal_action(
    state: GameState,
    action: GameAction,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> bool:
    return recover_exception(
        lambda: _validate_action(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        ),
        IllegalActionError,
        lambda _exc: False,
    )


def _validate_action(
    state: GameState,
    action: GameAction,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> bool:
    match action:
        case StartGameAction():
            validate_start_game_action(state, action, rng=rng)
        case ResolveMulligansAction():
            validate_resolve_mulligans_action(state, action)
        case ResolveChoiceAction():
            validate_resolve_choice_action(state, action)
        case PlayCardAction():
            validate_play_card_action(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
                rng=rng,
            )
        case PassAction():
            validate_pass_action(state, action)
        case LeaveAction():
            validate_leave_action(state, action)
        case UseLeaderAbilityAction():
            validate_use_leader_ability_action(
                state,
                action,
                leader_registry=leader_registry,
                card_registry=card_registry,
                rng=rng,
            )
    return True
