from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import singledispatch

from gwent_engine.cli.models import CardMetadata
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


def card_ref_text(
    card_instance_id: CardInstanceId,
    cards: Mapping[CardInstanceId, CardMetadata],
) -> str:
    card = cards.get(card_instance_id)
    if card is None:
        return str(card_instance_id)
    return f"[{card.name}] ({card.base_value})"


def card_list_text(
    card_ids: tuple[CardInstanceId, ...],
    cards: Mapping[CardInstanceId, CardMetadata],
) -> str:
    if not card_ids:
        return "-"
    return ", ".join(card_ref_text(card_id, cards) for card_id in card_ids)


def board_total(
    strengths_by_instance_id: Mapping[CardInstanceId, int],
    card_ids: tuple[CardInstanceId, ...],
) -> int:
    return sum(strengths_by_instance_id.get(card_id, 0) for card_id in card_ids)


def board_row_label(label: str, *, active: bool) -> str:
    return f"{label} (weather)" if active else label


def board_card_list_text(
    card_ids: tuple[CardInstanceId, ...],
    *,
    cards: Mapping[CardInstanceId, CardMetadata],
    strengths_by_instance_id: Mapping[CardInstanceId, int],
) -> str:
    if not card_ids:
        return "-"
    return ", ".join(
        f"[{_card_name(card_id, cards)}] ({strengths_by_instance_id.get(card_id, 0)})"
        for card_id in card_ids
    )


def _card_name(card_id: CardInstanceId, cards: Mapping[CardInstanceId, CardMetadata]) -> str:
    card = cards.get(card_id)
    return str(card_id) if card is None else card.name


@dataclass(frozen=True, slots=True)
class _SummaryCardContext:
    cards: Mapping[CardInstanceId, CardMetadata]

    def card_ref(self, card_instance_id: CardInstanceId) -> str:
        return card_ref_text(card_instance_id, self.cards)


def round_ended_event(events: tuple[GameEvent, ...]) -> RoundEndedEvent | None:
    for event in events:
        if isinstance(event, RoundEndedEvent):
            return event
    return None


def winner_text(winner: PlayerId | None) -> str:
    return "draw" if winner is None else str(winner)


def summarize_action(
    action: GameAction,
    *,
    cards: Mapping[CardInstanceId, CardMetadata],
) -> str:
    return _summarize_action(action, _SummaryCardContext(cards))


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
    selection_text = selected_targets or "no explicit selections"
    return f"{action.player_id} resolves {action.choice_id} -> {selection_text}"


@_summarize_action.register
def _(
    action: UseLeaderAbilityAction,
    context: _SummaryCardContext,
) -> str:
    parts = [f"{action.player_id} uses their leader ability"]
    if action.target_card_instance_id is not None:
        target_card = context.card_ref(action.target_card_instance_id)
        parts.append(f"targeting {target_card}")
    if action.selected_card_instance_ids:
        selected = ", ".join(
            context.card_ref(card_id) for card_id in action.selected_card_instance_ids
        )
        parts.append(f"selecting {selected}")
    return " ".join(parts)


def summarize_event(
    event: GameEvent,
    *,
    cards: Mapping[CardInstanceId, CardMetadata],
) -> str:
    return _summarize_event(event, _SummaryCardContext(cards))


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


def _summarize_mulligan_selection(selection: MulliganSelection) -> str:
    count = len(selection.cards_to_replace)
    replacement_text = "replacement" if count == 1 else "replacements"
    return f"{selection.player_id} resolves mulligan ({count} {replacement_text})"
