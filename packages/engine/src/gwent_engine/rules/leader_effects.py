"""Shared helpers for enabled leader definitions and passive leader modifiers."""

from gwent_engine.core import LeaderAbilityKind, LeaderAbilityMode
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry


def leader_definition_for_player(
    player: PlayerState,
    leader_registry: LeaderRegistry,
) -> LeaderDefinition:
    return leader_registry.get(player.leader.leader_id)


def enabled_leader_definition_for_player(
    player: PlayerState,
    leader_registry: LeaderRegistry | None,
) -> LeaderDefinition | None:
    if leader_registry is None or player.leader.disabled:
        return None
    return leader_definition_for_player(player, leader_registry)


def enabled_passive_leader_definitions(
    state: GameState,
    leader_registry: LeaderRegistry | None,
) -> tuple[LeaderDefinition, ...]:
    if leader_registry is None:
        return ()
    return tuple(
        leader_definition
        for player in state.players
        if (leader_definition := enabled_leader_definition_for_player(player, leader_registry))
        is not None
        and leader_definition.ability_mode == LeaderAbilityMode.PASSIVE
    )


def any_enabled_passive_leader_has_ability(
    state: GameState,
    leader_registry: LeaderRegistry | None,
    ability_kind: LeaderAbilityKind,
) -> bool:
    return any(
        leader_definition.ability_kind == ability_kind
        for leader_definition in enabled_passive_leader_definitions(state, leader_registry)
    )


def restore_selection_is_randomized(
    state: GameState,
    leader_registry: LeaderRegistry | None,
) -> bool:
    return any_enabled_passive_leader_has_ability(
        state,
        leader_registry,
        LeaderAbilityKind.RANDOMIZE_RESTORE_TO_BATTLEFIELD_SELECTION,
    )


def player_has_enabled_passive_leader_ability(
    state: GameState,
    leader_registry: LeaderRegistry | None,
    player_id: PlayerId,
    ability_kind: LeaderAbilityKind,
) -> bool:
    player = state.player(player_id)
    leader_definition = enabled_leader_definition_for_player(player, leader_registry)
    return leader_definition is not None and leader_definition.ability_kind == ability_kind
