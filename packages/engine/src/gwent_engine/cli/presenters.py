from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import singledispatch

from rich.text import Text

from gwent_engine.cli.models import CliMetadata
from gwent_engine.cli.view_formatters import card_ref_text
from gwent_engine.core import AbilityKind
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
from gwent_engine.core.events import (
    CardPlayedEvent,
    CardsDrawnEvent,
    CardsMovedToDiscardEvent,
    FactionPassiveTriggeredEvent,
    GameEvent,
    GameStartedEvent,
    LeaderAbilityResolvedEvent,
    MatchEndedEvent,
    MulliganPerformedEvent,
    NextRoundStartedEvent,
    PlayerLeftEvent,
    PlayerPassedEvent,
    RoundEndedEvent,
    SpecialCardResolvedEvent,
    SpyResolvedEvent,
    StartingPlayerChosenEvent,
    UnitScorchResolvedEvent,
)
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import PendingChoice


@dataclass(frozen=True, slots=True)
class ActionLabelStyle:
    border_style: str
    label_style: str


@dataclass(frozen=True, slots=True)
class _SummaryCardContext:
    names_by_instance_id: Mapping[CardInstanceId, str]
    values_by_instance_id: Mapping[CardInstanceId, int]

    def card_ref(self, card_instance_id: CardInstanceId) -> str:
        return card_ref(
            card_instance_id,
            self.names_by_instance_id,
            self.values_by_instance_id,
        )


DEFAULT_ACTION_LABEL_STYLE = ActionLabelStyle(
    border_style="white",
    label_style="bold white on grey23",
)
ACTION_LABEL_STYLES: dict[str, ActionLabelStyle] = {
    "StartGameAction": ActionLabelStyle("cyan", "bold white on dark_cyan"),
    "ResolveMulligansAction": ActionLabelStyle("magenta", "bold white on dark_magenta"),
    "PlayCardAction": ActionLabelStyle("green", "bold white on dark_green"),
    "PassAction": ActionLabelStyle("yellow3", "bold black on yellow3"),
    "LeaveAction": ActionLabelStyle("red", "bold white on dark_red"),
    "ResolveChoiceAction": ActionLabelStyle("purple", "bold white on purple"),
    "UseLeaderAbilityAction": ActionLabelStyle("bright_blue", "bold white on blue"),
}


def action_type_name(action: GameAction) -> str:
    return type(action).__name__


def event_type_name(event: GameEvent) -> str:
    return type(event).__name__


def round_ended_event(events: tuple[GameEvent, ...]) -> RoundEndedEvent | None:
    for event in events:
        if isinstance(event, RoundEndedEvent):
            return event
    return None


def winner_text(winner: PlayerId | None) -> str:
    return "draw" if winner is None else str(winner)


def render_action_label(action: GameAction) -> Text:
    label = action_type_name(action)
    palette = ACTION_LABEL_STYLES.get(label, DEFAULT_ACTION_LABEL_STYLE)
    return Text.assemble(
        ("[", palette.border_style),
        (f" {label} ", palette.label_style),
        ("]", palette.border_style),
    )


def summarize_action(
    action: GameAction,
    *,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    return _summarize_action(
        action,
        _SummaryCardContext(card_names_by_instance_id, card_values_by_instance_id),
    )


@singledispatch
def _summarize_action(
    action: object,
    _context: _SummaryCardContext,
) -> str:
    return _fallback_summary(action)


@_summarize_action.register
def _(
    action: StartGameAction,
    _context: _SummaryCardContext,
) -> str:
    return f"{action.starting_player} starts the match"


@_summarize_action.register
def _(
    action: ResolveMulligansAction,
    _context: _SummaryCardContext,
) -> str:
    return "; ".join(_summarize_mulligan_selection(selection) for selection in action.selections)


@_summarize_action.register
def _(
    action: PlayCardAction,
    context: _SummaryCardContext,
) -> str:
    played_card = context.card_ref(action.card_instance_id)
    parts = [f"{action.player_id} plays {played_card}"]
    if action.target_row is not None:
        parts.append(f"to {action.target_row.value}")
    if action.target_card_instance_id is not None:
        target_card = context.card_ref(action.target_card_instance_id)
        parts.append(f"targeting {target_card}")
    if action.secondary_target_card_instance_id is not None:
        secondary_target_card = context.card_ref(action.secondary_target_card_instance_id)
        parts.append(f"then {secondary_target_card}")
    return " ".join(parts)


@_summarize_action.register
def _(
    action: PassAction,
    _context: _SummaryCardContext,
) -> str:
    return f"{action.player_id} passes"


@_summarize_action.register
def _(
    action: LeaveAction,
    _context: _SummaryCardContext,
) -> str:
    return f"{action.player_id} leaves the match"


@_summarize_action.register
def _(
    action: ResolveChoiceAction,
    context: _SummaryCardContext,
) -> str:
    selected_targets = ", ".join(
        context.card_ref(card_id) for card_id in action.selected_card_instance_ids
    )
    selected_row_text = ", ".join(row.value for row in action.selected_rows)
    selection_text = selected_targets or selected_row_text or "no explicit selections"
    return f"{action.player_id} resolves {action.choice_id} -> {selection_text}"


@_summarize_action.register
def _(
    action: UseLeaderAbilityAction,
    context: _SummaryCardContext,
) -> str:
    parts = [f"{action.player_id} uses their leader ability"]
    if action.target_row is not None:
        parts.append(f"on {action.target_row.value}")
    if action.target_player is not None:
        parts.append(f"against {action.target_player}")
    if action.target_card_instance_id is not None:
        target_card = context.card_ref(action.target_card_instance_id)
        parts.append(f"targeting {target_card}")
    if action.secondary_target_card_instance_id is not None:
        secondary_target_card = context.card_ref(action.secondary_target_card_instance_id)
        parts.append(f"then {secondary_target_card}")
    if action.selected_card_instance_ids:
        selected = ", ".join(
            context.card_ref(card_id) for card_id in action.selected_card_instance_ids
        )
        parts.append(f"selecting {selected}")
    return " ".join(parts)


def summarize_event(
    event: GameEvent,
    *,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    return _summarize_event(
        event,
        _SummaryCardContext(card_names_by_instance_id, card_values_by_instance_id),
    )


@singledispatch
def _summarize_event(
    event: object,
    _context: _SummaryCardContext,
) -> str:
    return _fallback_summary(event)


def _fallback_summary(value: object) -> str:
    return type(value).__name__


@_summarize_event.register
def _(
    event: StartingPlayerChosenEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} becomes the starting player"


@_summarize_event.register
def _(
    event: GameStartedEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"phase={event.phase.value}, round={event.round_number}"


@_summarize_event.register
def _(
    event: CardsDrawnEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} draws {len(event.card_instance_ids)} card(s)"


@_summarize_event.register
def _(
    event: MulliganPerformedEvent,
    _context: _SummaryCardContext,
) -> str:
    return (
        f"{event.player_id} replaces {len(event.replaced_card_instance_ids)} and "
        f"draws {len(event.drawn_card_instance_ids)}"
    )


@_summarize_event.register
def _(
    event: CardPlayedEvent,
    context: _SummaryCardContext,
) -> str:
    row_text = event.target_row.value if event.target_row is not None else "auto"
    played_card = context.card_ref(event.card_instance_id)
    return f"{event.player_id} plays {played_card} to {row_text}"


@_summarize_event.register
def _(
    event: SpyResolvedEvent,
    context: _SummaryCardContext,
) -> str:
    spy_card = context.card_ref(event.card_instance_id)
    return (
        f"{event.player_id} resolves spy {spy_card} and draws {len(event.drawn_card_instance_ids)}"
    )


@_summarize_event.register
def _(
    event: SpecialCardResolvedEvent,
    context: _SummaryCardContext,
) -> str:
    resolved_card = context.card_ref(event.card_instance_id)
    parts = [f"{resolved_card} resolves {event.ability_kind.value}"]
    if event.affected_row is not None:
        parts.append(f"on {event.affected_row.value}")
    if event.target_card_instance_id is not None:
        target_card = context.card_ref(event.target_card_instance_id)
        parts.append(f"targeting {target_card}")
    if event.ability_kind == AbilityKind.SCORCH:
        parts.append(
            _summarize_special_scorch_targets(
                event,
                context,
            )
        )
    return " ".join(parts)


@_summarize_event.register
def _(
    event: UnitScorchResolvedEvent,
    context: _SummaryCardContext,
) -> str:
    scorch_card = context.card_ref(event.card_instance_id)
    prefix = f"{event.player_id} resolves {scorch_card} on {event.affected_row.value}:"
    if not event.destroyed_card_instance_ids:
        return f"{prefix} No units scorched"
    destroyed = ", ".join(
        context.card_ref(card_id) for card_id in event.destroyed_card_instance_ids
    )
    return f"{prefix} scorched {destroyed}"


@_summarize_event.register
def _(
    event: LeaderAbilityResolvedEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} resolves {event.leader_id} ({event.ability_kind.value})"


@_summarize_event.register
def _(
    event: PlayerPassedEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} passes"


@_summarize_event.register
def _(
    event: PlayerLeftEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} leaves the match"


@_summarize_event.register
def _(
    event: FactionPassiveTriggeredEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{event.player_id} triggers {event.passive_kind.value}"


@_summarize_event.register
def _(
    event: RoundEndedEvent,
    _context: _SummaryCardContext,
) -> str:
    left_player, left_score = event.player_scores[0]
    right_player, right_score = event.player_scores[1]
    winner_label = winner_text(event.winner)
    return (
        f"round {event.round_number} ends: {left_player}={left_score}, "
        f"{right_player}={right_score}, winner={winner_label}"
    )


@_summarize_event.register
def _(
    event: CardsMovedToDiscardEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"{len(event.card_instance_ids)} card(s) move to discard"


@_summarize_event.register
def _(
    event: NextRoundStartedEvent,
    _context: _SummaryCardContext,
) -> str:
    return f"round {event.round_number} starts with {event.starting_player}"


@_summarize_event.register
def _(
    event: MatchEndedEvent,
    _context: _SummaryCardContext,
) -> str:
    return "match ends in a draw" if event.winner is None else f"match winner={event.winner}"


def _summarize_special_scorch_targets(
    event: SpecialCardResolvedEvent,
    context: _SummaryCardContext,
) -> str:
    scorched_card_instance_ids = tuple(
        discarded_card_id
        for discarded_card_id in event.discarded_card_instance_ids
        if discarded_card_id != event.card_instance_id
    )
    if not scorched_card_instance_ids:
        return "No units scorched"
    scorched = ", ".join(context.card_ref(card_id) for card_id in scorched_card_instance_ids)
    return f"scorched {scorched}"


def metadata_items(metadata: CliMetadata) -> tuple[tuple[str, str], ...]:
    items: list[tuple[str, str]] = [
        ("Game Id", str(metadata.game_id)),
        ("Player One", str(metadata.player_one_id)),
    ]
    if metadata.player_one_actor is not None:
        items.append(("Player One Actor", metadata.player_one_actor))
    items.extend(
        [
            ("Player Two", str(metadata.player_two_id)),
        ]
    )
    if metadata.player_two_actor is not None:
        items.append(("Player Two Actor", metadata.player_two_actor))
    items.extend(
        [
            ("Player One Deck", str(metadata.player_one_deck_id)),
            ("Player Two Deck", str(metadata.player_two_deck_id)),
            ("Player One Leader", metadata.player_one_leader_name),
            ("Player Two Leader", metadata.player_two_leader_name),
            ("RNG Policy", metadata.rng_name),
            ("Pending Choice", "yes" if metadata.pending_choice_encountered else "no"),
        ]
    )
    return tuple(items)


def pending_choice_items(
    choice: PendingChoice,
    *,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> tuple[tuple[str, str], ...]:
    legal_targets = ", ".join(
        card_ref(card_id, card_names_by_instance_id, card_values_by_instance_id)
        for card_id in choice.legal_target_card_instance_ids
    )
    legal_rows = ", ".join(row.value for row in choice.legal_rows)
    return (
        ("Chooser", str(choice.player_id)),
        ("Choice Id", str(choice.choice_id)),
        ("Choice Kind", choice.kind.value),
        ("Source Kind", choice.source_kind.value),
        ("Legal Target Count", str(len(choice.legal_target_card_instance_ids))),
        (
            "Legal Targets",
            legal_targets if legal_targets else "none",
        ),
        ("Legal Rows", legal_rows if legal_rows else "none"),
    )


def _summarize_mulligan_selection(selection: MulliganSelection) -> str:
    count = len(selection.cards_to_replace)
    replacement_text = "replacement" if count == 1 else "replacements"
    return f"{selection.player_id} resolves mulligan ({count} {replacement_text})"


def card_ref(
    card_instance_id: CardInstanceId,
    card_names_by_instance_id: Mapping[CardInstanceId, str],
    card_values_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    return card_ref_text(
        card_instance_id,
        card_names_by_instance_id,
        card_values_by_instance_id,
    )
