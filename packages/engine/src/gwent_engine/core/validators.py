from gwent_shared.error_translation import recover_exception, translate_exception

from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    LeaveAction,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.config import MAX_MULLIGAN_REPLACEMENTS, OPENING_HAND_SIZE
from gwent_engine.core.enums import GameStatus, Phase
from gwent_engine.core.errors import (
    IllegalActionError,
    UnknownCardDefinitionError,
    UnknownCardInstanceError,
)
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.leader_abilities import validate_use_leader_ability_legality
from gwent_engine.rules.legality import (
    validate_in_round_player_can_act,
    validate_play_card_legality,
)
from gwent_engine.rules.selection_validation import (
    validate_distinct_selections,
    validate_legal_selections,
    validate_selection_count,
)


def validate_start_game_action(
    state: GameState,
    action: StartGameAction,
    *,
    rng: SupportsRandom | None,
) -> None:
    if state.phase != Phase.NOT_STARTED or state.status != GameStatus.NOT_STARTED:
        raise IllegalActionError("StartGameAction requires a NOT_STARTED game state.")
    if rng is None:
        raise IllegalActionError("StartGameAction requires an injected RNG.")
    if action.starting_player not in state.player_ids():
        raise IllegalActionError(f"Unknown starting player: {action.starting_player!r}")

    for player in state.players:
        if player.hand or player.discard or player.rows.all_cards():
            raise IllegalActionError("StartGameAction requires empty non-deck zones.")
        if player.has_passed:
            raise IllegalActionError("StartGameAction requires players that have not passed.")
        if player.leader.used or player.leader.disabled:
            raise IllegalActionError("StartGameAction requires enabled unused leader states.")
        if len(player.deck) < OPENING_HAND_SIZE:
            raise IllegalActionError(
                f"Player {player.player_id!r} does not have enough cards for the opening draw."
            )


def validate_resolve_mulligans_action(
    state: GameState,
    action: ResolveMulligansAction,
) -> None:
    if state.phase != Phase.MULLIGAN or state.status != GameStatus.IN_PROGRESS:
        raise IllegalActionError("ResolveMulligansAction is only legal during the MULLIGAN phase.")
    if len(action.selections) != len(state.players):
        raise IllegalActionError("ResolveMulligansAction requires one selection per player.")

    seen_player_ids = frozenset(selection.player_id for selection in action.selections)
    if seen_player_ids != state.player_ids():
        raise IllegalActionError("ResolveMulligansAction must include both players exactly once.")
    if len(seen_player_ids) != len(action.selections):
        raise IllegalActionError("ResolveMulligansAction cannot repeat the same player.")

    for selection in action.selections:
        if len(selection.cards_to_replace) > MAX_MULLIGAN_REPLACEMENTS:
            raise IllegalActionError(
                "ResolveMulligansAction may replace at most "
                + f"{MAX_MULLIGAN_REPLACEMENTS} cards per player."
            )
        if len(set(selection.cards_to_replace)) != len(selection.cards_to_replace):
            raise IllegalActionError(
                "ResolveMulligansAction cannot replace the same card twice for one player."
            )
        player = state.player(selection.player_id)
        hand_card_ids = set(player.hand)
        for card_id in selection.cards_to_replace:
            if card_id not in hand_card_ids:
                raise IllegalActionError(
                    f"ResolveMulligansAction card {card_id!r} is not in "
                    + f"player {selection.player_id!r} hand."
                )
        if len(player.deck) < len(selection.cards_to_replace):
            raise IllegalActionError(
                "ResolveMulligansAction cannot draw more cards than remain in deck."
            )


def validate_play_card_action(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    _require_in_round_action_phase(state, "PlayCardAction")
    if card_registry is None:
        raise IllegalActionError("PlayCardAction requires a card registry.")

    player = state.player(action.player_id)
    translate_exception(
        lambda: _validate_in_round_play_card(
            state,
            player,
            action,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        ),
        IllegalActionError,
        lambda exc: IllegalActionError(
            _play_card_error_message(state, action, card_registry=card_registry, message=str(exc))
        ),
    )


def validate_pass_action(state: GameState, action: PassAction) -> None:
    _require_in_round_action_phase(state, "PassAction")

    player = state.player(action.player_id)
    validate_in_round_player_can_act(state, player)


def _validate_in_round_play_card(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    validate_in_round_player_can_act(state, player)
    validate_play_card_legality(
        state,
        player,
        action,
        card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def validate_leave_action(state: GameState, action: LeaveAction) -> None:
    if state.status == GameStatus.MATCH_ENDED or state.phase == Phase.MATCH_ENDED:
        raise IllegalActionError("LeaveAction is only legal before the match has ended.")
    if action.player_id not in state.player_ids():
        raise IllegalActionError(f"Unknown leaving player: {action.player_id!r}")


def validate_resolve_choice_action(state: GameState, action: ResolveChoiceAction) -> None:
    pending_choice = state.pending_choice
    if pending_choice is None:
        raise IllegalActionError("ResolveChoiceAction requires a pending choice.")
    if action.player_id != pending_choice.player_id:
        raise IllegalActionError("ResolveChoiceAction must come from the pending-choice player.")
    if action.choice_id != pending_choice.choice_id:
        raise IllegalActionError("ResolveChoiceAction choice_id does not match the pending choice.")

    if pending_choice.legal_target_card_instance_ids:
        selected_ids = action.selected_card_instance_ids
        if action.selected_rows:
            raise IllegalActionError("This pending choice does not allow row selections.")
        _ = validate_distinct_selections(
            selected_ids,
            duplicate_message="ResolveChoiceAction cannot select the same card twice.",
        )
        _ = validate_selection_count(
            selected_ids,
            min_selections=pending_choice.min_selections,
            max_selections=pending_choice.max_selections,
            invalid_count_message="ResolveChoiceAction selected an invalid number of cards.",
        )
        _ = validate_legal_selections(
            selected_ids,
            legal_values=pending_choice.legal_target_card_instance_ids,
            illegal_message="ResolveChoiceAction selected an illegal target card.",
        )
        return

    if pending_choice.legal_rows:
        selected_rows = action.selected_rows
        if action.selected_card_instance_ids:
            raise IllegalActionError("This pending choice does not allow card selections.")
        _ = validate_distinct_selections(
            selected_rows,
            duplicate_message="ResolveChoiceAction cannot select the same row twice.",
        )
        _ = validate_selection_count(
            selected_rows,
            min_selections=pending_choice.min_selections,
            max_selections=pending_choice.max_selections,
            invalid_count_message="ResolveChoiceAction selected an invalid number of rows.",
        )
        _ = validate_legal_selections(
            selected_rows,
            legal_values=pending_choice.legal_rows,
            illegal_message="ResolveChoiceAction selected an illegal row.",
        )
        return

    raise IllegalActionError("Pending choice does not expose any legal selections.")


def validate_use_leader_ability_action(
    state: GameState,
    action: UseLeaderAbilityAction,
    *,
    leader_registry: LeaderRegistry | None,
    card_registry: CardRegistry | None,
    rng: SupportsRandom | None,
) -> None:
    _require_in_round_action_phase(state, "UseLeaderAbilityAction")
    if leader_registry is None:
        raise IllegalActionError("UseLeaderAbilityAction requires a leader registry.")
    if card_registry is None:
        raise IllegalActionError("UseLeaderAbilityAction requires a card registry.")
    validate_use_leader_ability_legality(
        state,
        action,
        leader_registry=leader_registry,
        card_registry=card_registry,
        rng=rng,
    )


def _require_in_round_action_phase(state: GameState, action_name: str) -> None:
    if state.phase != Phase.IN_ROUND or state.status != GameStatus.IN_PROGRESS:
        raise IllegalActionError(f"{action_name} is only legal during the IN_ROUND phase.")


def _play_card_error_message(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    message: str,
) -> str:
    return recover_exception(
        lambda: _play_card_context_message(
            state,
            action,
            card_registry=card_registry,
            message=message,
        ),
        (UnknownCardDefinitionError, UnknownCardInstanceError, KeyError, ValueError),
        lambda _exc: message,
    )


def _play_card_context_message(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    message: str,
) -> str:
    card_instance = state.card(action.card_instance_id)
    card_name = card_registry.get(card_instance.definition_id).name
    return f"{message} Attempted play: {card_name!r} ({action.card_instance_id})."
