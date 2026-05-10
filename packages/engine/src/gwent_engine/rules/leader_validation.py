from gwent_engine.cards import CardRegistry
from gwent_engine.core import LeaderAbilityKind, LeaderAbilityMode
from gwent_engine.core.actions import UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderDefinition, LeaderRegistry
from gwent_engine.rules.leader_common import (
    ActiveLeaderValidator,
    require_no_targets,
    require_only_card_target,
    selected_weather_card_in_deck,
)
from gwent_engine.rules.leader_effects import leader_definition_for_player
from gwent_engine.rules.legality import validate_in_round_player_can_act
from gwent_engine.rules.row_effects import row_has_commanders_horn


def validate_use_leader_ability_legality(
    state: GameState,
    action: UseLeaderAbilityAction,
    *,
    leader_registry: LeaderRegistry | None,
    card_registry: CardRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    assert leader_registry is not None
    assert card_registry is not None
    player = state.player(action.player_id)
    validate_in_round_player_can_act(state, player)
    leader_definition = leader_definition_for_player(player, leader_registry)
    if player.leader.disabled:
        raise IllegalActionError("Disabled leaders cannot use their active ability.")
    if player.leader.used:
        raise IllegalActionError("Leader abilities may be used at most once per battle.")
    if leader_definition.ability_mode != LeaderAbilityMode.ACTIVE:
        raise IllegalActionError("Passive leaders cannot be activated with an action.")

    validator = ACTIVE_LEADER_VALIDATORS.get(leader_definition.ability_kind)
    if validator is None:
        raise IllegalActionError(
            f"Unsupported active leader ability kind: {leader_definition.ability_kind!r}"
        )
    validator(state, player, leader_definition, action, card_registry, rng)


def _validate_no_target_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> None:
    del state, player, leader_definition, card_registry, rng
    require_no_targets(action)


def _validate_play_weather_from_deck_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> None:
    del rng
    require_only_card_target(action)
    chosen_card_id = selected_weather_card_in_deck(
        state,
        player,
        leader_definition,
        action,
        card_registry,
    )
    if chosen_card_id is None:
        raise IllegalActionError("Leader requires a matching weather card in deck.")


def _validate_horn_own_row_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> None:
    del rng
    require_no_targets(action)
    if leader_definition.affected_row is None:
        raise IllegalActionError("Leader horn ability must declare an affected row.")
    if leader_definition.blocked_if_row_already_affected_by_horn and row_has_commanders_horn(
        state,
        card_registry,
        player.player_id,
        leader_definition.affected_row,
    ):
        raise IllegalActionError("A combat row cannot have more than one Commander's Horn.")


def _validate_reveal_random_opponent_hand_cards_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> None:
    del state, player, leader_definition, card_registry
    require_no_targets(action)
    if rng is None:
        raise IllegalActionError("Random reveal leader abilities require an injected RNG.")


def _validate_shuffle_all_discards_into_decks_leader(
    state: GameState,
    player: PlayerState,
    leader_definition: LeaderDefinition,
    action: UseLeaderAbilityAction,
    card_registry: CardRegistry,
    rng: SupportsRandom | None,
) -> None:
    del state, player, leader_definition, card_registry
    require_no_targets(action)
    if rng is None:
        raise IllegalActionError("Shuffle leader abilities require an injected RNG.")


ACTIVE_LEADER_VALIDATORS: dict[LeaderAbilityKind, ActiveLeaderValidator] = {
    LeaderAbilityKind.CLEAR_WEATHER: _validate_no_target_leader,
    LeaderAbilityKind.PLAY_WEATHER_FROM_DECK: _validate_play_weather_from_deck_leader,
    LeaderAbilityKind.HORN_OWN_ROW: _validate_horn_own_row_leader,
    LeaderAbilityKind.SCORCH_OPPONENT_ROW: _validate_no_target_leader,
    LeaderAbilityKind.DISCARD_AND_CHOOSE_FROM_DECK: _validate_no_target_leader,
    LeaderAbilityKind.RETURN_CARD_FROM_OWN_DISCARD_TO_HAND: _validate_no_target_leader,
    LeaderAbilityKind.REVEAL_RANDOM_OPPONENT_HAND_CARDS: (
        _validate_reveal_random_opponent_hand_cards_leader
    ),
    LeaderAbilityKind.TAKE_CARD_FROM_OPPONENT_DISCARD_TO_HAND: _validate_no_target_leader,
    LeaderAbilityKind.OPTIMIZE_AGILE_ROWS: _validate_no_target_leader,
    LeaderAbilityKind.SHUFFLE_ALL_DISCARDS_INTO_DECKS: (
        _validate_shuffle_all_discards_into_decks_leader
    ),
}
