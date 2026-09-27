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


@dataclass(frozen=True, slots=True)
class UseLeaderAbilityActionView:
    player_id: str
    target_card_instance_id: str | None
    selected_card_instance_ids: tuple[str, ...]


def resolve_choice_action_view(action: ResolveChoiceAction) -> ResolveChoiceActionView:
    return ResolveChoiceActionView(
        player_id=str(action.player_id),
        choice_id=str(action.choice_id),
        selected_card_instance_ids=tuple(
            str(card_id) for card_id in action.selected_card_instance_ids
        ),
    )


def use_leader_ability_action_view(action: UseLeaderAbilityAction) -> UseLeaderAbilityActionView:
    return UseLeaderAbilityActionView(
        player_id=str(action.player_id),
        target_card_instance_id=(
            str(action.target_card_instance_id)
            if action.target_card_instance_id is not None
            else None
        ),
        selected_card_instance_ids=tuple(
            str(card_id) for card_id in action.selected_card_instance_ids
        ),
    )
