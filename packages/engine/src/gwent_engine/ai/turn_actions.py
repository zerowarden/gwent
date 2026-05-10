from __future__ import annotations

from collections.abc import Iterable

from gwent_engine.ai.action_ids import action_sort_key
from gwent_engine.ai.mulligan_actions import enumerate_joint_mulligan_actions
from gwent_engine.ai.pending_choice_actions import enumerate_pending_choice_actions
from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import (
    AbilityKind,
    CardType,
    LeaderAbilityKind,
    LeaderSelectionMode,
    Phase,
)
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    PassAction,
    PlayCardAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.battlefield_effects import is_weather_ability
from gwent_engine.rules.leader_effects import leader_definition_for_player
from gwent_engine.rules.row_effects import special_ability_kind

ROW_TARGETED_SPECIAL_ABILITIES = frozenset(
    {
        AbilityKind.COMMANDERS_HORN,
        AbilityKind.MARDROEME,
    }
)

UNTARGETED_SPECIAL_ABILITIES = frozenset(
    {
        AbilityKind.CLEAR_WEATHER,
        AbilityKind.SCORCH,
        AbilityKind.DECOY,
    }
)


def enumerate_candidate_actions(
    state: GameState,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    if state.pending_choice is not None:
        return _enumerate_pending_choice_candidates(state, player_id=player_id)
    return _enumerate_phase_candidates(
        state,
        card_registry=card_registry,
        leader_registry=leader_registry,
        player_id=player_id,
    )


def _enumerate_pending_choice_candidates(
    state: GameState,
    *,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    if state.pending_choice is None:
        return ()
    if player_id is not None and player_id != state.pending_choice.player_id:
        return ()
    return enumerate_pending_choice_actions(state.pending_choice)


def _enumerate_phase_candidates(
    state: GameState,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    match state.phase:
        case Phase.NOT_STARTED:
            actions = enumerate_start_actions(state, player_id=player_id)
        case Phase.MULLIGAN:
            actions = _enumerate_mulligan_candidates(state, player_id=player_id)
        case Phase.IN_ROUND:
            actions = _enumerate_in_round_candidates(
                state,
                card_registry=card_registry,
                leader_registry=leader_registry,
                player_id=player_id,
            )
        case _:
            actions = ()
    return actions


def enumerate_start_actions(
    state: GameState,
    *,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    player_ids = tuple(sorted(state.player_ids(), key=str))
    if player_id is not None and player_id not in player_ids:
        return ()
    if player_id is not None:
        return _start_actions_for_player(player_id)
    actions: list[GameAction] = [StartGameAction(starting_player=current) for current in player_ids]
    actions.extend(LeaveAction(player_id=current) for current in player_ids)
    return _finalize_actions(actions)


def _start_actions_for_player(player_id: PlayerId) -> tuple[GameAction, ...]:
    return _finalize_actions(
        (
            StartGameAction(starting_player=player_id),
            LeaveAction(player_id=player_id),
        )
    )


def _enumerate_mulligan_candidates(
    state: GameState,
    *,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    player_ids = state.player_ids()
    if player_id is not None and player_id not in player_ids:
        return ()
    if player_id is not None:
        return _finalize_actions((LeaveAction(player_id=player_id),))
    actions: list[GameAction] = list(enumerate_joint_mulligan_actions(state))
    actions.extend(LeaveAction(player_id=player.player_id) for player in state.players)
    return _finalize_actions(actions)


def _enumerate_in_round_candidates(
    state: GameState,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    player_id: PlayerId | None,
) -> tuple[GameAction, ...]:
    acting_player_id = _acting_player_for_request(state, player_id)
    if acting_player_id is None:
        return ()
    actor = state.player(acting_player_id)
    actions: list[GameAction] = []
    actions.extend(
        enumerate_play_card_actions(
            state,
            actor,
            card_registry=card_registry,
        )
    )
    actions.extend(
        enumerate_use_leader_actions(
            state,
            actor,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    )
    actions.append(PassAction(player_id=acting_player_id))
    actions.append(LeaveAction(player_id=acting_player_id))
    return _finalize_actions(actions)


def _acting_player_for_request(
    state: GameState,
    player_id: PlayerId | None,
) -> PlayerId | None:
    if state.current_player is None:
        return None
    if player_id is not None and player_id != state.current_player:
        return None
    return state.current_player


def enumerate_play_card_actions(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry | None,
) -> tuple[PlayCardAction, ...]:
    if card_registry is None:
        return ()
    actions: list[PlayCardAction] = []
    for card_id in player.hand:
        card = state.card(card_id)
        definition = card_registry.get(card.definition_id)
        actions.extend(_play_actions_for_card(player.player_id, card_id, definition))
    return tuple(actions)


def enumerate_use_leader_actions(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
) -> tuple[UseLeaderAbilityAction, ...]:
    if not _leader_action_available(player, card_registry, leader_registry):
        return ()
    assert card_registry is not None
    assert leader_registry is not None
    leader_definition = leader_definition_for_player(player, leader_registry)
    if leader_definition.ability_kind == LeaderAbilityKind.PLAY_WEATHER_FROM_DECK:
        return enumerate_play_weather_from_deck_actions(
            state,
            player,
            leader_definition,
            card_registry=card_registry,
        )
    return (UseLeaderAbilityAction(player_id=player.player_id),)


def _leader_action_available(
    player: PlayerState,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
) -> bool:
    return (
        card_registry is not None
        and leader_registry is not None
        and not player.leader.disabled
        and not player.leader.used
    )


def enumerate_play_weather_from_deck_actions(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    *,
    card_registry: CardRegistry,
) -> tuple[UseLeaderAbilityAction, ...]:
    matching_card_ids = tuple(
        card_id
        for card_id in player.deck
        if leader_weather_card_matches(
            state,
            card_registry,
            card_id=card_id,
            leader_definition=leader_definition,
        )
    )
    if not matching_card_ids:
        return (UseLeaderAbilityAction(player_id=player.player_id),)
    if leader_definition.selection_mode == LeaderSelectionMode.CHOOSE or len(matching_card_ids) > 1:
        return tuple(
            UseLeaderAbilityAction(
                player_id=player.player_id,
                target_card_instance_id=card_id,
            )
            for card_id in matching_card_ids
        )
    first_card_id = next(iter(matching_card_ids))
    return (
        UseLeaderAbilityAction(
            player_id=player.player_id,
            target_card_instance_id=first_card_id,
        ),
    )


def leader_weather_card_matches(
    state: GameState,
    card_registry: CardRegistry,
    *,
    card_id: CardInstanceId,
    leader_definition: LeaderDefinition,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    if definition.card_type != CardType.SPECIAL:
        return False
    ability_kind = special_ability_kind(definition)
    if leader_definition.selection_mode == LeaderSelectionMode.CHOOSE:
        return is_weather_ability(ability_kind)
    return ability_kind == leader_definition.weather_ability_kind


def _play_actions_for_card(
    player_id: PlayerId,
    card_id: CardInstanceId,
    definition: CardDefinition,
) -> tuple[PlayCardAction, ...]:
    if _card_requires_row_target(definition):
        return tuple(
            PlayCardAction(
                player_id=player_id,
                card_instance_id=card_id,
                target_row=row,
            )
            for row in definition.allowed_rows
        )
    if _card_is_untargeted_playable_special(definition):
        return (
            PlayCardAction(
                player_id=player_id,
                card_instance_id=card_id,
            ),
        )
    return ()


def _card_requires_row_target(definition: CardDefinition) -> bool:
    if definition.card_type == CardType.UNIT:
        return True
    if definition.card_type != CardType.SPECIAL:
        return False
    return special_ability_kind(definition) in ROW_TARGETED_SPECIAL_ABILITIES


def _card_is_untargeted_playable_special(definition: CardDefinition) -> bool:
    if definition.card_type != CardType.SPECIAL:
        return False
    ability_kind = special_ability_kind(definition)
    return is_weather_ability(ability_kind) or ability_kind in UNTARGETED_SPECIAL_ABILITIES


def _finalize_actions(actions: Iterable[GameAction]) -> tuple[GameAction, ...]:
    return tuple(sorted(actions, key=action_sort_key))
