from __future__ import annotations

from itertools import combinations

from gwent_engine.ai.action_ids import action_sort_key
from gwent_engine.core.actions import GameAction, ResolveChoiceAction
from gwent_engine.core.state import PendingChoice


def enumerate_pending_choice_actions(
    pending_choice: PendingChoice,
) -> tuple[GameAction, ...]:
    actions: list[GameAction] = []
    if pending_choice.legal_target_card_instance_ids:
        for selection_size in range(
            pending_choice.min_selections,
            pending_choice.max_selections + 1,
        ):
            for selected_ids in combinations(
                pending_choice.legal_target_card_instance_ids,
                selection_size,
            ):
                actions.append(
                    ResolveChoiceAction(
                        player_id=pending_choice.player_id,
                        choice_id=pending_choice.choice_id,
                        selected_card_instance_ids=selected_ids,
                    )
                )
    elif pending_choice.legal_rows:
        for selection_size in range(
            pending_choice.min_selections,
            pending_choice.max_selections + 1,
        ):
            for selected_rows in combinations(pending_choice.legal_rows, selection_size):
                actions.append(
                    ResolveChoiceAction(
                        player_id=pending_choice.player_id,
                        choice_id=pending_choice.choice_id,
                        selected_rows=selected_rows,
                    )
                )
    return tuple(sorted(actions, key=action_sort_key))
