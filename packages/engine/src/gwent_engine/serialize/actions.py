"""Stable codec for engine actions.

`action_to_id` is the wire format used by match records and search ordering;
`action_from_id` decodes it back into a typed action so recorded trajectories
can be replayed without policy code.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import cast

from gwent_shared.extract import (
    expect_constructor_sequence,
    expect_enum,
    expect_optional_enum,
    expect_sequence,
    expect_str,
    optional_constructor_field,
    require_constructor_field,
    require_field,
    require_str_field,
)

from gwent_engine.core.action_views import (
    resolve_choice_action_view,
    use_leader_ability_action_view,
)
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
    PlayCardAction,
    ResolveChoiceAction,
    ResolveMulligansAction,
    StartGameAction,
    UseLeaderAbilityAction,
)
from gwent_engine.core.enums import Row
from gwent_engine.core.errors import SerializationError
from gwent_engine.core.ids import (
    CardInstanceId,
    ChoiceId,
    PlayerId,
    card_instance_id,
    choice_id,
    player_id,
)

type ActionPayloadValue = str | tuple[str, ...] | tuple[tuple[str, tuple[str, ...]], ...]
type ActionPayload = dict[str, ActionPayloadValue]

_ACTION_CONTEXT = "action payload"


def action_to_id(action: GameAction) -> str:
    payload = action_payload(action)
    ordered_items = tuple(sorted(payload.items()))
    return repr(ordered_items)


def action_from_id(action_id: str) -> GameAction:
    """Decode an id produced by `action_to_id`.

    Non-canonical ids are rejected, so a tampered record cannot silently
    decode into a different action.
    """

    payload = _decode_payload(action_id)
    action = _action_from_payload(payload)
    if action_to_id(action) != action_id:
        raise SerializationError(f"Action id is not canonical: {action_id!r}.")
    return action


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


def _decode_payload(action_id: str) -> Mapping[str, object]:
    try:
        decoded = cast(object, ast.literal_eval(action_id))
    except (ValueError, SyntaxError) as error:
        raise SerializationError(f"Action id is not a valid payload: {action_id!r}.") from error
    entries = expect_sequence(decoded, context="action id", error_factory=SerializationError)
    payload: dict[str, object] = {}
    for entry in entries:
        pair = expect_sequence(entry, context="action id entry", error_factory=SerializationError)
        if len(pair) != 2:
            raise SerializationError("Action id entries must be key/value pairs.")
        key = expect_str(pair[0], context="action id key", error_factory=SerializationError)
        if key in payload:
            raise SerializationError(f"Action id contains the duplicate key {key!r}.")
        payload[key] = pair[1]
    return payload


def _action_from_payload(payload: Mapping[str, object]) -> GameAction:
    action_type = require_str_field(
        payload, "type", context=_ACTION_CONTEXT, error_factory=SerializationError
    )
    match action_type:
        case "StartGameAction":
            return StartGameAction(starting_player=_require_player_id(payload, "starting_player"))
        case "ResolveMulligansAction":
            return ResolveMulligansAction(selections=_mulligan_selections(payload))
        case "PlayCardAction":
            return PlayCardAction(
                player_id=_require_player_id(payload, "player_id"),
                card_instance_id=_require_card_instance_id(payload, "card_instance_id"),
                target_row=_optional_row(payload, "target_row"),
                target_card_instance_id=_optional_card_instance_id(
                    payload, "target_card_instance_id"
                ),
                secondary_target_card_instance_id=_optional_card_instance_id(
                    payload, "secondary_target_card_instance_id"
                ),
            )
        case "PassAction":
            return PassAction(player_id=_require_player_id(payload, "player_id"))
        case "LeaveAction":
            return LeaveAction(player_id=_require_player_id(payload, "player_id"))
        case "ResolveChoiceAction":
            return ResolveChoiceAction(
                player_id=_require_player_id(payload, "player_id"),
                choice_id=_require_choice_id(payload, "choice_id"),
                selected_card_instance_ids=_card_instance_ids(
                    payload, "selected_card_instance_ids"
                ),
                selected_rows=_rows(payload, "selected_rows"),
            )
        case "UseLeaderAbilityAction":
            return UseLeaderAbilityAction(
                player_id=_require_player_id(payload, "player_id"),
                target_row=_optional_row(payload, "target_row"),
                target_player=_optional_player_id(payload, "target_player"),
                target_card_instance_id=_optional_card_instance_id(
                    payload, "target_card_instance_id"
                ),
                secondary_target_card_instance_id=_optional_card_instance_id(
                    payload, "secondary_target_card_instance_id"
                ),
                selected_card_instance_ids=_card_instance_ids(
                    payload, "selected_card_instance_ids"
                ),
            )
        case _:
            raise SerializationError(f"Unknown action type: {action_type!r}.")


def _require_player_id(payload: Mapping[str, object], field: str) -> PlayerId:
    return require_constructor_field(
        payload, field, player_id, context=_ACTION_CONTEXT, error_factory=SerializationError
    )


def _optional_player_id(payload: Mapping[str, object], field: str) -> PlayerId | None:
    return optional_constructor_field(
        payload, field, player_id, context=_ACTION_CONTEXT, error_factory=SerializationError
    )


def _require_card_instance_id(payload: Mapping[str, object], field: str) -> CardInstanceId:
    return require_constructor_field(
        payload, field, card_instance_id, context=_ACTION_CONTEXT, error_factory=SerializationError
    )


def _optional_card_instance_id(
    payload: Mapping[str, object],
    field: str,
) -> CardInstanceId | None:
    return optional_constructor_field(
        payload,
        field,
        card_instance_id,
        context=_ACTION_CONTEXT,
        error_factory=SerializationError,
    )


def _require_choice_id(payload: Mapping[str, object], field: str) -> ChoiceId:
    return require_constructor_field(
        payload, field, choice_id, context=_ACTION_CONTEXT, error_factory=SerializationError
    )


def _card_instance_ids(
    payload: Mapping[str, object],
    field: str,
) -> tuple[CardInstanceId, ...]:
    value = require_field(payload, field, context=_ACTION_CONTEXT, error_factory=SerializationError)
    return expect_constructor_sequence(
        value,
        card_instance_id,
        context=f"{_ACTION_CONTEXT}.{field}",
        error_factory=SerializationError,
    )


def _rows(payload: Mapping[str, object], field: str) -> tuple[Row, ...]:
    entries = expect_sequence(
        require_field(payload, field, context=_ACTION_CONTEXT, error_factory=SerializationError),
        context=f"{_ACTION_CONTEXT}.{field}",
        error_factory=SerializationError,
    )
    return tuple(_row(entry, context=f"{_ACTION_CONTEXT}.{field}") for entry in entries)


def _optional_row(payload: Mapping[str, object], field: str) -> Row | None:
    return expect_optional_enum(
        payload.get(field),
        Row,
        context=_ACTION_CONTEXT,
        label=field,
        error_factory=SerializationError,
    )


def _row(value: object, *, context: str) -> Row:
    return expect_enum(value, Row, context=context, error_factory=SerializationError)


def _mulligan_selections(payload: Mapping[str, object]) -> tuple[MulliganSelection, ...]:
    context = f"{_ACTION_CONTEXT}.selections"
    entries = expect_sequence(
        require_field(
            payload, "selections", context=_ACTION_CONTEXT, error_factory=SerializationError
        ),
        context=context,
        error_factory=SerializationError,
    )
    selections: list[MulliganSelection] = []
    for entry in entries:
        pair = expect_sequence(entry, context=f"{context} entry", error_factory=SerializationError)
        if len(pair) != 2:
            raise SerializationError(f"{context} entries must be player/card pairs.")
        selections.append(
            MulliganSelection(
                player_id=PlayerId(
                    expect_str(
                        pair[0], context=f"{context} player", error_factory=SerializationError
                    )
                ),
                cards_to_replace=expect_constructor_sequence(
                    pair[1],
                    card_instance_id,
                    context=f"{context} cards",
                    error_factory=SerializationError,
                ),
            )
        )
    return tuple(selections)
