from __future__ import annotations

from collections.abc import Sequence

from gwent_engine.ai.turn_actions import enumerate_candidate_actions
from gwent_engine.cards import CardRegistry
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
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import PlayerId
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


def enumerate_legal_actions(
    state: GameState,
    *,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
    rng: SupportsRandom | None = None,
    player_id: PlayerId | None = None,
) -> tuple[GameAction, ...]:
    candidate_actions = enumerate_candidate_actions(
        state,
        card_registry=card_registry,
        leader_registry=leader_registry,
        player_id=player_id,
    )
    return tuple(
        action
        for action in candidate_actions
        if is_legal_action(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    )


def is_legal_action(
    state: GameState,
    action: GameAction,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> bool:
    try:
        return _validate_action(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
    except IllegalActionError:
        return False


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
            validate_pass_action(
                state,
                action,
                card_registry=card_registry,
                leader_registry=leader_registry,
                rng=rng,
            )
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


def mulligan_selection_id(selection: MulliganSelection) -> str:
    cards = ",".join(str(card_id) for card_id in selection.cards_to_replace)
    return f"{selection.player_id}:{cards}"


def filter_non_leave_actions(legal_actions: Sequence[GameAction]) -> tuple[GameAction, ...]:
    actions = tuple(legal_actions)
    non_leave_actions = tuple(action for action in actions if not isinstance(action, LeaveAction))
    return non_leave_actions or actions
