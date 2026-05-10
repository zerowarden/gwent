from __future__ import annotations

from gwent_engine.cli.report.format import HTMLFormatter
from gwent_engine.core.actions import GameAction
from gwent_engine.core.ids import PlayerId, player_id

MINUS_SIGN = "\N{MINUS SIGN}"
MULTIPLICATION_SIGN = "\N{MULTIPLICATION SIGN}"


def action_player_id(action: GameAction) -> PlayerId | None:
    raw_player_id = getattr(action, "player_id", None)
    return player_id(raw_player_id) if isinstance(raw_player_id, str) else None


def formatted_summary(
    formatter: HTMLFormatter,
    items: tuple[tuple[str, str], ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "key": formatter.fmt(key),
            "value": formatter.fmt(value),
        }
        for key, value in items
    )


def dominant_term_context(
    formatter: HTMLFormatter,
    *,
    name: str,
    value: float,
) -> dict[str, object]:
    return {
        "name": formatter.fmt(name),
        "value": f"{value:.2f}",
    }


def numeric_term_context(
    formatter: HTMLFormatter,
    *,
    name: str,
    value: float,
    formula: str,
    details: tuple[tuple[str, str], ...],
    dominant: bool,
) -> dict[str, object]:
    return {
        "name": formatter.fmt(name),
        "value": f"{value:.2f}",
        "numeric_value": value,
        "is_zero": abs(value) <= 1e-9,
        "formula": formatter.fmt(formula),
        "details": tuple(
            {
                "key": formatter.fmt(key),
                "value": formatter.fmt(detail_value),
            }
            for key, detail_value in details
        ),
        "dominant": dominant,
    }


def math_number_text(value: float | int) -> str:
    if isinstance(value, int):
        text = str(value)
    else:
        text = f"{value:.2f}"
    return text.replace("-", MINUS_SIGN)


def signed_additions_text(
    values: tuple[float, ...],
    *,
    total: float,
    zero_text: str,
) -> str:
    if not values:
        return zero_text
    parts: list[str] = []
    for index, value in enumerate(values):
        magnitude = math_number_text(abs(value))
        if index == 0:
            parts.append(f"{MINUS_SIGN}{magnitude}" if value < 0 else magnitude)
            continue
        parts.append(f"{MINUS_SIGN if value < 0 else '+'} {magnitude}")
    return f"{math_number_text(total)} = {' '.join(parts)}"


def winner_status_text(winner: PlayerId | None, status: str) -> str:
    if winner is None:
        return "draw" if status == "match_ended" else "pending"
    return str(winner)
