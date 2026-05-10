from dataclasses import dataclass, replace

from gwent_engine.cards import CardDefinition, CardRegistry
from gwent_engine.core import (
    AbilityKind,
    CardType,
    ChoiceKind,
    ChoiceSourceKind,
    EffectSourceCategory,
    LeaderAbilityKind,
    Row,
)
from gwent_engine.core.actions import PlayCardAction, ResolveChoiceAction, UseLeaderAbilityAction
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.events import GameEvent
from gwent_engine.core.ids import CardInstanceId, ChoiceId, LeaderId
from gwent_engine.core.randomness import SupportsRandom
from gwent_engine.core.state import GameState, PendingChoice, PlayerState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.choice_classification import (
    card_requires_pending_choice,
    leader_requires_pending_choice,
)
from gwent_engine.rules.effect_applicability import (
    can_affect_card,
    can_target_for_decoy,
    can_target_for_medic,
)
from gwent_engine.rules.leader_abilities import apply_use_leader_ability
from gwent_engine.rules.leader_effects import (
    leader_definition_for_player,
    restore_selection_is_randomized,
)
from gwent_engine.rules.players import other_player_from_state
from gwent_engine.rules.row_effects import special_ability_kind
from gwent_engine.rules.selection_validation import validate_selection_count
from gwent_engine.rules.turn_flow import apply_play_card


@dataclass(frozen=True, slots=True)
class _LeaderPendingChoiceTargets:
    legal_target_ids: tuple[CardInstanceId, ...]
    min_selections: int = 1
    max_selections: int = 1


def create_pending_choice_for_decoy(
    state: GameState,
    player: PlayerState,
    *,
    source_card_instance_id: CardInstanceId,
    card_registry: CardRegistry,
) -> PendingChoice:
    legal_target_ids = tuple(
        card_id
        for row in (Row.CLOSE, Row.RANGED, Row.SIEGE)
        for card_id in player.rows.cards_for(row)
        if can_target_for_decoy(
            state,
            card_registry,
            player=player,
            target_card_id=card_id,
        )
    )
    if not legal_target_ids:
        raise IllegalActionError("Decoy requires a valid unit card on your battlefield.")
    return _build_pending_choice(
        state,
        player=player,
        source_kind=ChoiceSourceKind.DECOY,
        source_card_instance_id=source_card_instance_id,
        legal_target_card_instance_ids=legal_target_ids,
    )


def create_pending_choice_for_medic(
    state: GameState,
    player: PlayerState,
    *,
    source_card_instance_id: CardInstanceId,
    source_row: Row,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> PendingChoice | None:
    if restore_selection_is_randomized(state, leader_registry):
        return None
    legal_target_ids = tuple(
        card_id
        for card_id in player.discard
        if can_target_for_medic(
            state,
            card_registry,
            player=player,
            target_card_id=card_id,
        )
    )
    if not legal_target_ids:
        raise IllegalActionError("Medic requires a valid unit card in your discard pile.")
    return _build_pending_choice(
        state,
        player=player,
        source_kind=ChoiceSourceKind.MEDIC,
        source_card_instance_id=source_card_instance_id,
        legal_target_card_instance_ids=legal_target_ids,
        source_row=source_row,
    )


def create_pending_choice_for_leader(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> PendingChoice | None:
    leader_definition = leader_definition_for_player(player, leader_registry)
    if not leader_requires_pending_choice(leader_definition.ability_kind):
        return None

    targets = _leader_pending_choice_targets(
        state,
        player,
        card_registry=card_registry,
        ability_kind=leader_definition.ability_kind,
        hand_discard_count=leader_definition.hand_discard_count,
        deck_pick_count=leader_definition.deck_pick_count,
    )
    if targets is None:
        return None
    if not targets.legal_target_ids:
        raise IllegalActionError("Leader ability requires at least one legal discard target.")
    return _build_pending_choice(
        state,
        player=player,
        source_kind=ChoiceSourceKind.LEADER_ABILITY,
        source_leader_id=player.leader.leader_id,
        legal_target_card_instance_ids=targets.legal_target_ids,
        min_selections=targets.min_selections,
        max_selections=targets.max_selections,
    )


def _leader_pending_choice_targets(
    state: GameState,
    player: PlayerState,
    *,
    card_registry: CardRegistry,
    ability_kind: LeaderAbilityKind,
    hand_discard_count: int,
    deck_pick_count: int,
) -> _LeaderPendingChoiceTargets | None:
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
) -> _LeaderPendingChoiceTargets | None:
    if len(player.hand) < hand_discard_count or len(player.deck) < deck_pick_count:
        return None
    selection_count = hand_discard_count + deck_pick_count
    return _LeaderPendingChoiceTargets(
        legal_target_ids=player.hand + player.deck,
        min_selections=selection_count,
        max_selections=selection_count,
    )


def _discard_retrieval_targets(
    state: GameState,
    card_registry: CardRegistry,
    discard: tuple[CardInstanceId, ...],
) -> _LeaderPendingChoiceTargets | None:
    legal_target_ids = tuple(
        card_id
        for card_id in discard
        if _can_target_for_discard_retrieval_leader(
            state,
            card_registry,
            target_card_id=card_id,
        )
    )
    return _LeaderPendingChoiceTargets(legal_target_ids) if legal_target_ids else None


def maybe_create_pending_choice_for_play(
    state: GameState,
    action: PlayCardAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> PendingChoice | None:
    player = state.player(action.player_id)
    definition = card_registry.get(state.card(action.card_instance_id).definition_id)
    if not card_requires_pending_choice(definition):
        return None
    if definition.card_type == CardType.UNIT and action.target_row is not None:
        return _pending_choice_for_unit_play(
            state,
            player,
            action,
            definition=definition,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
    if definition.card_type == CardType.SPECIAL:
        return _pending_choice_for_special_play(
            state,
            player,
            action,
            definition=definition,
            card_registry=card_registry,
        )
    return None


def _pending_choice_for_unit_play(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    *,
    definition: CardDefinition,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None,
) -> PendingChoice | None:
    if AbilityKind.MEDIC not in definition.ability_kinds:
        return None
    assert action.target_row is not None
    return create_pending_choice_for_medic(
        state,
        player,
        source_card_instance_id=action.card_instance_id,
        source_row=action.target_row,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )


def _pending_choice_for_special_play(
    state: GameState,
    player: PlayerState,
    action: PlayCardAction,
    *,
    definition: CardDefinition,
    card_registry: CardRegistry,
) -> PendingChoice | None:
    if special_ability_kind(definition) != AbilityKind.DECOY:
        return None
    return create_pending_choice_for_decoy(
        state,
        player,
        source_card_instance_id=action.card_instance_id,
        card_registry=card_registry,
    )


def maybe_create_pending_choice_for_leader(
    state: GameState,
    action: UseLeaderAbilityAction,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry,
) -> PendingChoice | None:
    player = state.player(action.player_id)
    return create_pending_choice_for_leader(
        state,
        player,
        card_registry=card_registry,
        leader_registry=leader_registry,
    )


def _can_target_for_discard_retrieval_leader(
    state: GameState,
    card_registry: CardRegistry,
    *,
    target_card_id: CardInstanceId,
) -> bool:
    definition = card_registry.get(state.card(target_card_id).definition_id)
    return definition.card_type == CardType.UNIT and can_affect_card(
        state,
        card_registry,
        source_category=EffectSourceCategory.LEADER_ABILITY,
        target_card_id=target_card_id,
    )


def resolve_pending_choice(
    state: GameState,
    action: ResolveChoiceAction,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    pending_choice = state.pending_choice
    assert pending_choice is not None
    if pending_choice.kind != ChoiceKind.SELECT_CARD_INSTANCE:
        raise IllegalActionError(f"Unsupported pending choice kind: {pending_choice.kind!r}")
    base_state = replace(state, pending_choice=None)

    if pending_choice.source_kind == ChoiceSourceKind.DECOY:
        return _resolve_pending_decoy(
            base_state,
            action,
            pending_choice,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )

    if pending_choice.source_kind == ChoiceSourceKind.MEDIC:
        return _resolve_pending_medic(
            base_state,
            action,
            pending_choice,
            card_registry=card_registry,
            leader_registry=leader_registry,
            rng=rng,
        )

    if pending_choice.source_kind == ChoiceSourceKind.LEADER_ABILITY:
        return _resolve_pending_leader(
            base_state,
            action,
            leader_registry=leader_registry,
            card_registry=card_registry,
            rng=rng,
        )

    raise IllegalActionError(f"Unsupported pending choice source: {pending_choice.source_kind!r}")


def _resolve_pending_decoy(
    base_state: GameState,
    action: ResolveChoiceAction,
    pending_choice: PendingChoice,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    _validate_single_card_selection(
        action,
        invalid_count_message="Pending Decoy resolution requires exactly one target.",
    )
    if card_registry is None:
        raise IllegalActionError("Pending Decoy resolution requires a card registry.")
    assert pending_choice.source_card_instance_id is not None
    return apply_play_card(
        base_state,
        PlayCardAction(
            player_id=action.player_id,
            card_instance_id=pending_choice.source_card_instance_id,
            target_card_instance_id=action.selected_card_instance_ids[0],
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def _resolve_pending_medic(
    base_state: GameState,
    action: ResolveChoiceAction,
    pending_choice: PendingChoice,
    *,
    card_registry: CardRegistry | None,
    leader_registry: LeaderRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    _validate_single_card_selection(
        action,
        invalid_count_message="Pending Medic resolution requires exactly one target.",
    )
    if card_registry is None:
        raise IllegalActionError("Pending Medic resolution requires a card registry.")
    assert pending_choice.source_card_instance_id is not None
    assert pending_choice.source_row is not None
    return apply_play_card(
        base_state,
        PlayCardAction(
            player_id=action.player_id,
            card_instance_id=pending_choice.source_card_instance_id,
            target_row=pending_choice.source_row,
            target_card_instance_id=action.selected_card_instance_ids[0],
        ),
        card_registry=card_registry,
        leader_registry=leader_registry,
        rng=rng,
    )


def _resolve_pending_leader(
    base_state: GameState,
    action: ResolveChoiceAction,
    *,
    leader_registry: LeaderRegistry | None,
    card_registry: CardRegistry | None,
    rng: SupportsRandom | None,
) -> tuple[GameState, tuple[GameEvent, ...]]:
    if leader_registry is None or card_registry is None:
        raise IllegalActionError("Pending leader resolution requires both registries.")
    return apply_use_leader_ability(
        base_state,
        UseLeaderAbilityAction(
            player_id=action.player_id,
            target_card_instance_id=action.selected_card_instance_ids[0]
            if len(action.selected_card_instance_ids) == 1
            else None,
            selected_card_instance_ids=action.selected_card_instance_ids,
        ),
        leader_registry=leader_registry,
        card_registry=card_registry,
        rng=rng,
    )


def _validate_single_card_selection(
    action: ResolveChoiceAction,
    *,
    invalid_count_message: str,
) -> None:
    _ = validate_selection_count(
        action.selected_card_instance_ids,
        min_selections=1,
        max_selections=1,
        invalid_count_message=invalid_count_message,
    )


def _pending_choice_id(
    state: GameState,
    *,
    source_kind: ChoiceSourceKind,
    source_card_instance_id: CardInstanceId | None = None,
    source_leader_id: LeaderId | None = None,
) -> ChoiceId:
    source_id = source_card_instance_id if source_card_instance_id is not None else source_leader_id
    return ChoiceId(f"{source_kind.value}_{source_id}_{state.event_counter}")


def _build_pending_choice(
    state: GameState,
    *,
    player: PlayerState,
    source_kind: ChoiceSourceKind,
    source_card_instance_id: CardInstanceId | None = None,
    source_leader_id: LeaderId | None = None,
    legal_target_card_instance_ids: tuple[CardInstanceId, ...] = (),
    legal_rows: tuple[Row, ...] = (),
    min_selections: int = 1,
    max_selections: int = 1,
    source_row: Row | None = None,
) -> PendingChoice:
    return PendingChoice(
        choice_id=_pending_choice_id(
            state,
            source_kind=source_kind,
            source_card_instance_id=source_card_instance_id,
            source_leader_id=source_leader_id,
        ),
        player_id=player.player_id,
        kind=ChoiceKind.SELECT_CARD_INSTANCE,
        source_kind=source_kind,
        source_card_instance_id=source_card_instance_id,
        source_leader_id=source_leader_id,
        legal_target_card_instance_ids=legal_target_card_instance_ids,
        legal_rows=legal_rows,
        min_selections=min_selections,
        max_selections=max_selections,
        source_row=source_row,
    )
