from __future__ import annotations

from gwent_engine.core.action_views import (
    resolve_choice_action_view,
    use_leader_ability_action_view,
)
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)

type ActionPayloadValue = str | tuple[str, ...] | tuple[tuple[str, tuple[str, ...]], ...]
type ActionPayload = dict[str, ActionPayloadValue]

ACTION_TYPE_ORDER = {
    "StartGameAction": 0,
    "ResolveMulligansAction": 1,
    "ResolveChoiceAction": 2,
    "PlayCardAction": 3,
    "UseLeaderAbilityAction": 4,
    "PassAction": 5,
    "LeaveAction": 6,
}


def action_to_id(action: GameAction) -> str:
    payload = action_payload(action)
    ordered_items = tuple(sorted(payload.items()))
    return repr(ordered_items)


def action_sort_key(action: GameAction) -> tuple[object, ...]:
    payload = action_payload(action)
    type_name = str(payload["type"])
    return (
        ACTION_TYPE_ORDER[type_name],
        *(payload[key] for key in sorted(payload) if key != "type"),
    )


def action_payload(action: GameAction) -> ActionPayload:
    match action:
        case StartGameAction() as start_action:
            payload = _start_game_payload(start_action)
        case ResolveMulligansAction() as mulligan_action:
            payload = _resolve_mulligans_payload(mulligan_action)
        case PlayCardAction() as play_action:
            payload = _play_card_payload(play_action)
        case PassAction() as pass_action:
            payload = _player_only_payload("PassAction", pass_action.player_id)
        case LeaveAction() as leave_action:
            payload = _player_only_payload("LeaveAction", leave_action.player_id)
        case ResolveChoiceAction() as resolve_choice_action:
            payload = _resolve_choice_payload(resolve_choice_action)
        case UseLeaderAbilityAction() as leader_action:
            payload = _use_leader_ability_payload(leader_action)
    return payload


def _start_game_payload(action: StartGameAction) -> ActionPayload:
    return {
        "type": "StartGameAction",
        "starting_player": str(action.starting_player),
    }


def _resolve_mulligans_payload(action: ResolveMulligansAction) -> ActionPayload:
    return {
        "type": "ResolveMulligansAction",
        "selections": tuple(
            (
                str(selection.player_id),
                tuple(str(card_id) for card_id in selection.cards_to_replace),
            )
            for selection in action.selections
        ),
    }


def _play_card_payload(action: PlayCardAction) -> ActionPayload:
    return {
        "type": "PlayCardAction",
        "player_id": str(action.player_id),
        "card_instance_id": str(action.card_instance_id),
        "target_row": action.target_row.value if action.target_row is not None else "",
        "target_card_instance_id": str(action.target_card_instance_id or ""),
        "secondary_target_card_instance_id": str(action.secondary_target_card_instance_id or ""),
    }


def _player_only_payload(action_type: str, player_id: object) -> ActionPayload:
    return {
        "type": action_type,
        "player_id": str(player_id),
    }


def _resolve_choice_payload(action: ResolveChoiceAction) -> ActionPayload:
    choice_view = resolve_choice_action_view(action)
    return {
        "type": "ResolveChoiceAction",
        "player_id": choice_view.player_id,
        "choice_id": choice_view.choice_id,
        "selected_card_instance_ids": choice_view.selected_card_instance_ids,
        "selected_rows": choice_view.selected_rows,
    }


def _use_leader_ability_payload(action: UseLeaderAbilityAction) -> ActionPayload:
    leader_view = use_leader_ability_action_view(action)
    return {
        "type": "UseLeaderAbilityAction",
        "player_id": leader_view.player_id,
        "target_row": leader_view.target_row or "",
        "target_player": leader_view.target_player or "",
        "target_card_instance_id": leader_view.target_card_instance_id or "",
        "secondary_target_card_instance_id": leader_view.secondary_target_card_instance_id or "",
        "selected_card_instance_ids": leader_view.selected_card_instance_ids,
    }
