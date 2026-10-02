"""Round-continuation policy: which players can still act in the current round.

An empty hand does not by itself end a player's round. In Gwent a leader ability
constitutes a turn, so a player with no cards can still act while they have an
unused, enabled, active leader whose prerequisites are available. A player is
only done for the round when they have passed or cannot take any legal action.
"""

from __future__ import annotations

from dataclasses import replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import LeaderAbilityKind, LeaderAbilityMode, Phase
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.choice_targets import leader_requires_pending_choice
from gwent_engine.rules.leader_common import (
    deck_card_matches_weather_selection,
    leader_definition_for_player,
    leader_pending_choice_targets,
)
from gwent_engine.rules.leader_validation import validate_leader_ability_availability
from gwent_engine.rules.players import other_player_from_state


def can_continue_round(
    state: GameState,
    player_id: PlayerId,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None = None,
) -> bool:
    """Whether the player still has a legal action available this round."""
    player = state.player(player_id)
    if player.has_passed:
        return False
    pending_choice = state.pending_choice
    if pending_choice is not None and pending_choice.player_id == player_id:
        return True
    if player.hand:
        return True
    if card_registry is None or leader_registry is None:
        return False
    return has_legal_leader_action(
        state,
        player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def has_legal_leader_action(
    state: GameState,
    player_id: PlayerId,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
    rng: SupportsRandom | None = None,
) -> bool:
    """Whether the player can activate their leader according to leader legality."""
    player = state.player(player_id)
    if player.leader.used or player.leader.disabled:
        return False
    definition = leader_definition_for_player(player, leader_registry)
    if definition.ability_mode != LeaderAbilityMode.ACTIVE:
        return False
    if leader_requires_pending_choice(definition.ability_kind):
        targets = leader_pending_choice_targets(
            state,
            player,
            card_registry=card_registry,
            ability_kind=definition.ability_kind,
            hand_discard_count=definition.hand_discard_count,
            deck_pick_count=definition.deck_pick_count,
        )
        return targets is not None and bool(targets.legal_target_ids)
    for action in _leader_action_candidates(
        state,
        player,
        definition,
        card_registry=card_registry,
    ):
        try:
            validate_leader_ability_availability(
                state,
                player,
                action,
                leader_registry=leader_registry,
                card_registry=card_registry,
                rng=rng,
            )
        except IllegalActionError:
            continue
        return True
    return False


def advance_turn_after_action(
    state: GameState,
    acting_player_id: PlayerId,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None = None,
) -> GameState:
    opponent = other_player_from_state(state, acting_player_id)
    return assign_round_priority(
        state,
        opponent.player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def assign_round_priority(
    state: GameState,
    preferred_player_id: PlayerId,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None = None,
) -> GameState:
    if can_continue_round(
        state,
        preferred_player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    ):
        return replace(state, current_player=preferred_player_id, phase=Phase.IN_ROUND)
    alternate = other_player_from_state(state, preferred_player_id)
    if can_continue_round(
        state,
        alternate.player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    ):
        return replace(state, current_player=alternate.player_id, phase=Phase.IN_ROUND)
    return replace(state, current_player=None, phase=Phase.ROUND_RESOLUTION)


def _leader_action_candidates(
    state: GameState,
    player: PlayerState,
    definition: LeaderDefinition,
    *,
    card_registry: CardRegistry,
) -> tuple[UseLeaderAbilityAction, ...]:
    base_action = UseLeaderAbilityAction(player_id=player.player_id)
    if definition.ability_kind != LeaderAbilityKind.PLAY_WEATHER_FROM_DECK:
        return (base_action,)
    return (
        base_action,
        *(
            UseLeaderAbilityAction(
                player_id=player.player_id,
                target_card_instance_id=card_id,
            )
            for card_id in player.deck
            if deck_card_matches_weather_selection(
                state,
                card_registry,
                card_id=card_id,
                leader_definition=definition,
            )
        ),
    )
