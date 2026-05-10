"""Shared presentation views for actions.

These helpers keep human/JSON-facing action renderers aligned without forcing
them to share the same output container type. The AI action-id path still emits
tuple payloads for stable sorting, while CLI JSON keeps list/null semantics.
"""

from dataclasses import dataclass

from gwent_engine.core.actions import ResolveChoiceAction, UseLeaderAbilityAction


@dataclass(frozen=True, slots=True)
class ResolveChoiceActionView:
    player_id: str
    choice_id: str
    selected_card_instance_ids: tuple[str, ...]
    selected_rows: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UseLeaderAbilityActionView:
    player_id: str
    target_row: str | None
    target_player: str | None
    target_card_instance_id: str | None
    secondary_target_card_instance_id: str | None
    selected_card_instance_ids: tuple[str, ...]


def resolve_choice_action_view(action: ResolveChoiceAction) -> ResolveChoiceActionView:
    return ResolveChoiceActionView(
        player_id=str(action.player_id),
        choice_id=str(action.choice_id),
        selected_card_instance_ids=tuple(
            str(card_id) for card_id in action.selected_card_instance_ids
        ),
        selected_rows=tuple(row.value for row in action.selected_rows),
    )


def use_leader_ability_action_view(action: UseLeaderAbilityAction) -> UseLeaderAbilityActionView:
    return UseLeaderAbilityActionView(
        player_id=str(action.player_id),
        target_row=action.target_row.value if action.target_row is not None else None,
        target_player=str(action.target_player) if action.target_player is not None else None,
        target_card_instance_id=(
            str(action.target_card_instance_id)
            if action.target_card_instance_id is not None
            else None
        ),
        secondary_target_card_instance_id=(
            str(action.secondary_target_card_instance_id)
            if action.secondary_target_card_instance_id is not None
            else None
        ),
        selected_card_instance_ids=tuple(
            str(card_id) for card_id in action.selected_card_instance_ids
        ),
    )
