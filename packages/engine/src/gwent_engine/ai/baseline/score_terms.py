"""Explainable score terms and per-action breakdowns produced by heuristic evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.core.actions import (
    GameAction,
)


@dataclass(frozen=True, slots=True)
class ScoreTermDetail:
    key: str
    value: float | int | str


@dataclass(frozen=True, slots=True)
class ScoreTerm:
    name: str
    value: float
    formula: str | None = None
    raw_value: float | None = None
    raw_label: str | None = None
    weight: float | None = None
    weight_label: str | None = None
    details: tuple[ScoreTermDetail, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionScoreBreakdown:
    action: GameAction
    terms: tuple[ScoreTerm, ...]

    @property
    def total(self) -> float:
        return sum(term.value for term in self.terms)


def term_detail(key: str, value: float | int | str) -> ScoreTermDetail:
    return ScoreTermDetail(key=key, value=value)


def constant_term(
    name: str,
    value: float,
    *,
    formula: str | None = None,
    details: tuple[ScoreTermDetail, ...] = (),
) -> ScoreTerm:
    return ScoreTerm(
        name=name,
        value=float(value),
        formula=formula,
        details=details,
    )


def weighted_term(
    name: str,
    *,
    raw_value: float,
    raw_label: str,
    weight: float,
    weight_label: str,
    details: tuple[ScoreTermDetail, ...] = (),
) -> ScoreTerm:
    return ScoreTerm(
        name=name,
        value=float(weight) * float(raw_value),
        raw_value=float(raw_value),
        raw_label=raw_label,
        weight=float(weight),
        weight_label=weight_label,
        details=details,
    )
