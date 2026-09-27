from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import AbilityKind, CardType, Row, Zone
from gwent_engine.core.actions import PlayCardAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import CardInstance, GameState, PlayerState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.battlefield_effects import is_weather_ability
from gwent_engine.rules.card_abilities import definition_has_ability
from gwent_engine.rules.effect_applicability import can_target_for_decoy
from gwent_engine.rules.leader_effects import restore_selection_is_randomized
from gwent_engine.rules.round_continuation import can_continue_round
from gwent_engine.rules.row_effects import (
    row_has_commanders_horn,
    row_has_special_commanders_horn,
    row_has_special_mardroeme,
    special_ability_kind,
)


def validate_in_round_player_can_act(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry | None = None,
    leader_registry: LeaderRegistry | None = None,
    rng: SupportsRandom | None = None,
) -> None:
    if player.has_passed:
        raise IllegalActionError("Passed players cannot act again in the same round.")
    if not can_continue_round(
        state,
        player.player_id,
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    ):
        raise IllegalActionError(
            "Players with an empty hand and no available leader action cannot act "
            "in the same round."
        )
    if state.current_player != player.player_id:
        raise IllegalActionError("Only the current player may act.")


def validate_play_card_legality(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    card_registry: CardRegistry,
    *,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    card_instance = _validate_playable_hand_card(state, player, action)

    definition = card_registry.get(card_instance.definition_id)
    if definition.card_type == CardType.UNIT:
        _validate_unit_play_legality(
            state,
            action,
            definition,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
        return
    if definition.card_type != CardType.SPECIAL:
        raise IllegalActionError("Only unit cards and supported special cards are legal plays.")
    _validate_special_play_legality(state, player, action, definition, card_registry)


def _validate_playable_hand_card(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
) -> CardInstance:
    if action.card_instance_id not in player.hand:
        raise IllegalActionError(
            f"Card {action.card_instance_id!r} is not in player {player.player_id!r} hand."
        )

    card_instance = state.card(action.card_instance_id)
    if card_instance.owner != player.player_id:
        raise IllegalActionError(
            f"Card {action.card_instance_id!r} does not belong to player {player.player_id!r}."
        )
    if card_instance.zone != Zone.HAND:
        raise IllegalActionError(f"Card {action.card_instance_id!r} must be in hand to be played.")
    return card_instance


def _validate_unit_play_legality(
    state: GameState,
    action: PlayCardAction,
    definition: CardDefinition,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    _ = _validate_target_row(
        action,
        definition,
        missing_message="Unit cards must target a combat row.",
    )
    if definition_has_ability(definition, AbilityKind.MEDIC):
        _validate_medic_play_legality(
            state,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )
        return
    if action.target_card_instance_id is not None:
        raise IllegalActionError("Only Medic unit cards may target another card.")


def _validate_medic_play_legality(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    if restore_selection_is_randomized(
        state,
        leader_registry,
        card_registry=card_registry,
        medic_card_id=action.card_instance_id,
    ):
        _validate_randomized_medic_play_action(action, rng=rng)
        return

    if action.target_card_instance_id is not None:
        raise IllegalActionError("Medic discard targets are resolved through pending choice.")


def _validate_randomized_medic_play_action(
    action: PlayCardAction,
    *,
    rng: SupportsRandom | None,
) -> None:
    if rng is None:
        raise IllegalActionError("Randomized restoration requires an injected RNG.")
    if action.target_card_instance_id is not None:
        raise IllegalActionError(
            "Randomized restoration leaders do not allow explicit Medic targets."
        )


def _validate_special_play_legality(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    definition: CardDefinition,
    card_registry: CardRegistry,
) -> None:
    ability_kind = special_ability_kind(definition)
    if ability_kind == AbilityKind.COMMANDERS_HORN:
        _validate_commanders_horn_legality(state, player, action, definition, card_registry)
        return
    if ability_kind == AbilityKind.MARDROEME:
        _validate_special_mardroeme_legality(state, player, action, definition, card_registry)
        return
    if is_weather_ability(ability_kind) or ability_kind in (
        AbilityKind.CLEAR_WEATHER,
        AbilityKind.SCORCH,
    ):
        _validate_global_special_legality(action)
        return
    if ability_kind == AbilityKind.DECOY:
        _validate_decoy_legality(state, player, action, card_registry)
        return
    raise IllegalActionError(f"Unsupported special ability kind: {ability_kind!r}")


def _validate_target_row(
    action: PlayCardAction,
    definition: CardDefinition,
    *,
    missing_message: str,
) -> Row:
    if action.target_row is None:
        raise IllegalActionError(missing_message)
    if action.target_row not in definition.allowed_rows:
        raise IllegalActionError(
            f"Card {action.card_instance_id!r} cannot be played to row {action.target_row!r}."
        )
    return action.target_row


def _validate_commanders_horn_legality(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    definition: CardDefinition,
    card_registry: CardRegistry,
) -> None:
    if action.target_card_instance_id is not None:
        raise IllegalActionError("Commander's Horn does not target a battlefield card.")
    target_row = _validate_target_row(
        action,
        definition,
        missing_message="Commander's Horn must target a combat row.",
    )
    if row_has_commanders_horn(state, card_registry, player.player_id, target_row):
        raise IllegalActionError("A combat row cannot have more than one Commander's Horn.")
    if row_has_special_mardroeme(state, card_registry, player.player_id, target_row):
        raise IllegalActionError("Special Mardroeme and special Horn cannot share a row.")


def _validate_special_mardroeme_legality(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    definition: CardDefinition,
    card_registry: CardRegistry,
) -> None:
    if action.target_card_instance_id is not None:
        raise IllegalActionError("Mardroeme does not target a battlefield card.")
    target_row = _validate_target_row(
        action,
        definition,
        missing_message="Mardroeme must target a combat row.",
    )
    if row_has_special_commanders_horn(state, card_registry, player.player_id, target_row):
        raise IllegalActionError("Special Mardroeme and special Horn cannot share a row.")
    if row_has_special_mardroeme(state, card_registry, player.player_id, target_row):
        raise IllegalActionError("A combat row cannot have more than one special Mardroeme.")


def _validate_global_special_legality(action: PlayCardAction) -> None:
    if action.target_row is not None:
        raise IllegalActionError("This special card does not target a combat row.")
    if action.target_card_instance_id is not None:
        raise IllegalActionError("This special card does not target a battlefield card.")


def _validate_decoy_legality(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    card_registry: CardRegistry,
) -> None:
    if action.target_row is not None:
        raise IllegalActionError("Decoy targets a battlefield card, not a combat row.")
    if action.target_card_instance_id is not None:
        raise IllegalActionError("Decoy battlefield targets are resolved through pending choice.")
    if any(
        can_target_for_decoy(
            state,
            card_registry,
            player=player,
            target_card_id=card_id,
        )
        for card_id in player.rows.all_cards()
    ):
        return
    raise IllegalActionError("Decoy requires a valid non-hero unit card on your battlefield.")
