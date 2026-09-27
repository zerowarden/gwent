"""Prerequisite resolution for leaders whose abilities require a pending choice.

Kept below the pending-choice and round-continuation layers so both can share
one authoritative set of eligibility rules without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.cards import CardRegistry
from gwent_engine.core import LeaderAbilityKind
from gwent_engine.core.errors import IllegalActionError
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.core.state import GameState, PlayerState
from gwent_engine.rules.effect_applicability import can_target_for_discard_retrieval
from gwent_engine.rules.leader_common import discard_and_choose_selection_required
from gwent_engine.rules.players import other_player_from_state


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
