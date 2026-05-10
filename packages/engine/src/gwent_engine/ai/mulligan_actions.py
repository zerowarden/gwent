from __future__ import annotations

from itertools import combinations, product

from gwent_engine.ai.action_ids import action_sort_key
from gwent_engine.core import Phase
from gwent_engine.core.actions import GameAction, MulliganSelection, ResolveMulligansAction
from gwent_engine.core.config import MAX_MULLIGAN_REPLACEMENTS
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import GameState


def enumerate_mulligan_selections(
    state: GameState,
    player_id: PlayerId,
) -> tuple[MulliganSelection, ...]:
    if state.phase != Phase.MULLIGAN:
        return ()
    player = state.player(player_id)
    selections = tuple(
        MulliganSelection(player_id=player_id, cards_to_replace=card_ids)
        for card_ids in card_id_combinations(
            player.hand,
            max_count=min(MAX_MULLIGAN_REPLACEMENTS, len(player.hand)),
        )
    )
    return tuple(sorted(selections, key=mulligan_selection_sort_key))


def enumerate_joint_mulligan_actions(state: GameState) -> tuple[GameAction, ...]:
    player_selections = tuple(
        enumerate_mulligan_selections(state, player.player_id) for player in state.players
    )
    actions = tuple(
        ResolveMulligansAction(selections=selection_pair)
        for selection_pair in product(*player_selections)
    )
    return tuple(sorted(actions, key=action_sort_key))


def card_id_combinations(
    card_ids: tuple[CardInstanceId, ...],
    *,
    max_count: int,
) -> tuple[tuple[CardInstanceId, ...], ...]:
    selections = [
        selected_ids
        for selection_size in range(max_count + 1)
        for selected_ids in combinations(card_ids, selection_size)
    ]
    return tuple(
        sorted(
            selections,
            key=lambda ids: (len(ids), tuple(str(card_id) for card_id in ids)),
        )
    )


def mulligan_selection_sort_key(selection: MulliganSelection) -> tuple[object, ...]:
    return (
        str(selection.player_id),
        len(selection.cards_to_replace),
        tuple(str(card_id) for card_id in selection.cards_to_replace),
    )
