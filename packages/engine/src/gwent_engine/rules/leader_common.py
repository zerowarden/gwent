"""Shared leader helpers: enabled definitions, passive modifiers, and choice targets.

Kept below the pending-choice and round-continuation layers so both can share
one authoritative set of leader eligibility rules without an import cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from gwent_engine.cards import CardRegistry
from gwent_engine.core import (
    WEATHER_ABILITY_KINDS,
    AbilityKind,
    CardType,
    LeaderAbilityKind,
    LeaderAbilityMode,
    LeaderSelectionMode,
    Row,
)
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import GameEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.effect_applicability import (
    can_affect_card,
    can_target_for_discard_retrieval,
    is_hero,
)
from gwent_engine.rules.players import other_player_from_state, replace_player
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.selection_validation import (
    validate_distinct_selections,
    validate_selection_count,
)
from gwent_engine.rules.state_ops import (
    append_to_row,
    remove_card_from_rows,
    replace_card_instance,
)

type ActiveLeaderValidator = Callable[
    [
        GameState,
        PlayerState,
        LeaderDefinition,
        UseLeaderAbilityAction,
        CardRegistry,
        SupportsRandom | None,
    ],
    None,
]

type ActiveLeaderHandler = Callable[
    [
        GameState,
        PlayerState,
        LeaderDefinition,
        UseLeaderAbilityAction,
        CardRegistry,
        SupportsRandom | None,
        LeaderRegistry,
    ],
    tuple[GameState, tuple[GameEvent, ...]],
]


def require_no_targets(action: UseLeaderAbilityAction) -> None:
    if action.target_card_instance_id is not None or action.selected_card_instance_ids:
        raise IllegalActionError("This leader ability does not take explicit targets.")


def require_only_card_target(action: UseLeaderAbilityAction) -> None:
    if action.selected_card_instance_ids:
        raise IllegalActionError("This leader ability only accepts a single card target.")


def selected_weather_card_in_deck(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
) -> CardInstanceId | None:
    matching_weather_ids = tuple(
        card_id
        for card_id in player.deck
        if deck_card_matches_weather_selection(
            state,
            card_registry,
            card_id=card_id,
            leader_definition=leader_definition,
        )
    )
    if not matching_weather_ids:
        return None
    if action.target_card_instance_id is not None:
        return _selected_matching_weather_card(action, matching_weather_ids)
    if (
        leader_definition.selection_mode == LeaderSelectionMode.CHOOSE
        and len(matching_weather_ids) > 1
    ):
        raise IllegalActionError("Leader must choose which weather card to play from deck.")
    assert matching_weather_ids
    return matching_weather_ids[0]


def discard_and_choose_selection_required(
    player: PlayerState,
    *,
    hand_discard_count: int,
    deck_pick_count: int,
) -> bool:
    return len(player.hand) >= hand_discard_count and len(player.deck) >= deck_pick_count


def _selected_matching_weather_card(
    action: UseLeaderAbilityAction,
    matching_weather_ids: tuple[CardInstanceId, ...],
) -> CardInstanceId:
    assert action.target_card_instance_id is not None
    if action.target_card_instance_id not in matching_weather_ids:
        raise IllegalActionError("Leader must target a matching weather card in your deck.")
    return action.target_card_instance_id


def deck_card_matches_weather_selection(
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
        return ability_kind in WEATHER_ABILITY_KINDS
    return ability_kind == leader_definition.weather_ability_kind


def pick_random_card_ids(
    card_ids: tuple[CardInstanceId, ...],
    count: int,
    *,
    rng: SupportsRandom,
) -> tuple[CardInstanceId, ...]:
    remaining_card_ids = list(card_ids)
    chosen_card_ids: list[CardInstanceId] = []
    while remaining_card_ids and len(chosen_card_ids) < count:
        chosen_card_id = rng.choice(tuple(remaining_card_ids))
        chosen_card_ids.append(chosen_card_id)
        remaining_card_ids.remove(chosen_card_id)
    return tuple(chosen_card_ids)


def is_agile_battlefield_unit(
    state: GameState,
    card_registry: CardRegistry,
    card_id: CardInstanceId,
) -> bool:
    definition = card_registry.get(state.card(card_id).definition_id)
    return definition.is_unit_with(AbilityKind.AGILE) and can_affect_card(
        state,
        card_registry,
        target_card_id=card_id,
    )


def move_battlefield_card_to_row(
    state: GameState,
    card_id: CardInstanceId,
    target_row: Row,
) -> GameState:
    card = state.card(card_id)
    if card.row == target_row:
        return state
    if card.battlefield_side is None or card.row is None:
        raise IllegalActionError("Only battlefield cards can be moved between rows.")
    controller = state.player(card.battlefield_side)
    updated_controller = replace(
        controller,
        rows=append_to_row(
            remove_card_from_rows(controller.rows, card_id),
            target_row,
            card_id,
        ),
    )
    updated_card = replace(card, row=target_row)
    return replace(
        state,
        players=replace_player(state.players, updated_controller),
        card_instances=replace_card_instance(state.card_instances, updated_card),
    )


def resolve_discard_and_choose_from_deck_selection(
    player: PlayerState,
    leader_definition: LeaderDefinition,
    selected_card_instance_ids: tuple[CardInstanceId, ...],
) -> tuple[tuple[CardInstanceId, ...], tuple[CardInstanceId, ...]]:
    expected_count = leader_definition.hand_discard_count + leader_definition.deck_pick_count
    normalized_ids = validate_distinct_selections(
        selected_card_instance_ids,
        duplicate_message="Leader card selections cannot contain duplicates.",
    )
    _ = validate_selection_count(
        normalized_ids,
        min_selections=expected_count,
        max_selections=expected_count,
        invalid_count_message=(
            f"Leader requires exactly {expected_count} selected cards for discard-and-pick."
        ),
    )
    selected_ids = set(normalized_ids)
    discarded_card_ids = tuple(card_id for card_id in player.hand if card_id in selected_ids)
    drawn_card_ids = tuple(card_id for card_id in player.deck if card_id in selected_ids)
    if len(discarded_card_ids) != leader_definition.hand_discard_count:
        raise IllegalActionError("Leader requires the configured number of hand discards.")
    if len(drawn_card_ids) != leader_definition.deck_pick_count:
        raise IllegalActionError("Leader requires the configured number of chosen deck cards.")
    return discarded_card_ids, drawn_card_ids


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
    *,
    card_registry: CardRegistry,
    medic_card_id: CardInstanceId,
) -> bool:
    return not is_hero(state, card_registry, medic_card_id) and (
        any_enabled_passive_leader_has_ability(
            state,
            leader_registry,
            LeaderAbilityKind.RANDOMIZE_RESTORE_TO_BATTLEFIELD_SELECTION,
        )
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


@dataclass(frozen=True, slots=True)
class LeaderChoiceTargets:
    legal_target_ids: tuple[CardInstanceId, ...]
    min_selections: int = 1
    max_selections: int = 1


def leader_pending_choice_targets(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry,
    ability_kind: LeaderAbilityKind,
    hand_discard_count: int,
    deck_pick_count: int,
) -> LeaderChoiceTargets | None:
    match ability_kind:
        case LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK:
            return _discard_and_choose_targets(
                player,
                hand_discard_count=hand_discard_count,
                deck_pick_count=deck_pick_count,
            )
        case LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND:
            return _discard_retrieval_targets(state, card_registry, player.discard)
        case LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND:
            opponent = other_player_from_state(state, player.player_id)
            return _discard_retrieval_targets(state, card_registry, opponent.discard)
        case _:
            raise IllegalActionError(f"Unsupported pending-choice leader ability: {ability_kind!r}")


def _discard_and_choose_targets(
    player: PlayerState,
    *,
    hand_discard_count: int,
    deck_pick_count: int,
) -> LeaderChoiceTargets | None:
    if not discard_and_choose_selection_required(
        player,
        hand_discard_count=hand_discard_count,
        deck_pick_count=deck_pick_count,
    ):
        return None
    selection_count = hand_discard_count + deck_pick_count
    return LeaderChoiceTargets(
        legal_target_ids=player.hand + player.deck,
        min_selections=selection_count,
        max_selections=selection_count,
    )


def _discard_retrieval_targets(
    state: GameState,
    card_registry: CardRegistry,
    discard: tuple[CardInstanceId, ...],
) -> LeaderChoiceTargets | None:
    legal_target_ids = tuple(
        card_id
        for card_id in discard
        if can_target_for_discard_retrieval(
            state,
            card_registry,
            target_card_id=card_id,
        )
    )
    return LeaderChoiceTargets(legal_target_ids) if legal_target_ids else None
