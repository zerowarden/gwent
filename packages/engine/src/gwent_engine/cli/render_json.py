from __future__ import annotations

from gwent_engine.cli.models import CliMetadata, CliRun, CliStep
from gwent_engine.core.action_views import (
    resolve_choice_action_view,
    use_leader_ability_action_view,
)
from gwent_engine.core.actions import (
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.serialize import event_to_dict, game_state_to_dict


def render_json_payload(run: CliRun) -> dict[str, object]:
    return {
        "scenario": run.scenario_name,
        "metadata": metadata_to_dict(run.metadata),
        "pending_choice_state": (
            game_state_to_dict(run.pending_choice_state)
            if run.pending_choice_state is not None
            else None
        ),
        "steps": [step_to_dict(step) for step in run.steps],
        "final_state": game_state_to_dict(run.final_state),
    }


def metadata_to_dict(metadata: CliMetadata) -> dict[str, object]:
    payload: dict[str, object] = {
        "game_id": str(metadata.game_id),
        "p1_id": str(metadata.player_one_id),
        "p2_id": str(metadata.player_two_id),
        "p1_deck_id": str(metadata.player_one_deck_id),
        "p2_deck_id": str(metadata.player_two_deck_id),
        "p1_leader_id": str(metadata.player_one_leader_id),
        "p2_leader_id": str(metadata.player_two_leader_id),
        "p1_leader_name": metadata.player_one_leader_name,
        "p2_leader_name": metadata.player_two_leader_name,
        "rng_name": metadata.rng_name,
        "pending_choice_encountered": metadata.pending_choice_encountered,
    }
    if metadata.player_one_actor is not None:
        payload["p1_actor"] = metadata.player_one_actor
    if metadata.player_two_actor is not None:
        payload["p2_actor"] = metadata.player_two_actor
    return payload


def step_to_dict(step: CliStep) -> dict[str, object]:
    return {
        "action": action_to_dict(step.action),
        "events": [event_to_dict(event) for event in step.events],
    }


def action_to_dict(action: object) -> dict[str, object]:
    payload: dict[str, object]
    match action:
        case StartGameAction(starting_player=starting_player):
            payload = {
                "type": "StartGameAction",
                "starting_player": str(starting_player),
            }
        case ResolveMulligansAction(selections=selections):
            payload = {
                "type": "ResolveMulligansAction",
                "selections": [mulligan_selection_to_dict(selection) for selection in selections],
            }
        case PlayCardAction(
            player_id=player_id,
            card_instance_id=card_instance_id,
            target_row=target_row,
            target_card_instance_id=target_card_instance_id,
            secondary_target_card_instance_id=secondary_target_card_instance_id,
        ):
            payload = {
                "type": "PlayCardAction",
                "player_id": str(player_id),
                "card_instance_id": str(card_instance_id),
                "target_row": target_row.value if target_row is not None else None,
                "target_card_instance_id": (
                    str(target_card_instance_id) if target_card_instance_id is not None else None
                ),
                "secondary_target_card_instance_id": (
                    str(secondary_target_card_instance_id)
                    if secondary_target_card_instance_id is not None
                    else None
                ),
            }
        case PassAction(player_id=player_id):
            payload = {
                "type": "PassAction",
                "player_id": str(player_id),
            }
        case LeaveAction(player_id=player_id):
            payload = {
                "type": "LeaveAction",
                "player_id": str(player_id),
            }
        case ResolveChoiceAction() as resolve_choice_action:
            choice_view = resolve_choice_action_view(resolve_choice_action)
            payload = {
                "type": "ResolveChoiceAction",
                "player_id": choice_view.player_id,
                "choice_id": choice_view.choice_id,
                "selected_card_instance_ids": list(choice_view.selected_card_instance_ids),
                "selected_rows": list(choice_view.selected_rows),
            }
        case UseLeaderAbilityAction() as leader_action:
            leader_view = use_leader_ability_action_view(leader_action)
            payload = {
                "type": "UseLeaderAbilityAction",
                "player_id": leader_view.player_id,
                "target_row": leader_view.target_row,
                "target_player": leader_view.target_player,
                "target_card_instance_id": leader_view.target_card_instance_id,
                "secondary_target_card_instance_id": leader_view.secondary_target_card_instance_id,
                "selected_card_instance_ids": list(leader_view.selected_card_instance_ids),
            }
        case _:
            raise TypeError(f"Unsupported CLI action: {action!r}")
    return payload


def mulligan_selection_to_dict(selection: MulliganSelection) -> dict[str, object]:
    return {
        "player_id": str(selection.player_id),
        "cards_to_replace": [str(card_id) for card_id in selection.cards_to_replace],
    }
