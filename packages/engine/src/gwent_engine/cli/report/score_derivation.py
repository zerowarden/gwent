from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from gwent_engine.ai.baseline import (
    ActionScoreBreakdown,
    HeuristicProfile,
    ScoreTerm,
    ScoreTermDetail,
    WeightProvenance,
)
from gwent_engine.cli.report.common import (
    MULTIPLICATION_SIGN,
    dominant_term_context,
    math_number_text,
    numeric_term_context,
    signed_additions_text,
)
from gwent_engine.cli.report.format import HTMLFormatter


@dataclass(slots=True)
class ScoreDerivationPresenter:
    formatter: HTMLFormatter

    def context(
        self,
        breakdown: ActionScoreBreakdown,
        profile: HeuristicProfile,
        *,
        popover_id: str,
    ) -> dict[str, object]:
        weight_provenance = {item.name: item for item in profile.weight_provenance}
        dominant_term = (
            max(breakdown.terms, key=lambda term: (abs(term.value), term.name))
            if breakdown.terms
            else None
        )
        return {
            "popover_id": popover_id,
            "button_label": self.formatter.fmt(f"score={breakdown.total:.2f}"),
            "title": self.formatter.fmt(f"Score Derivation ({breakdown.total:.2f})"),
            "total": f"{breakdown.total:.2f}",
            "additions": self.formatter.fmt(self._score_additions_text(breakdown)),
            "dominant_term": (
                None
                if dominant_term is None
                else dominant_term_context(
                    self.formatter,
                    name=dominant_term.name,
                    value=dominant_term.value,
                )
            ),
            "terms": tuple(
                sorted(
                    (
                        numeric_term_context(
                            self.formatter,
                            name=term.name,
                            value=term.value,
                            formula=self._term_formula_text(term),
                            details=tuple(
                                (detail.key, self._detail_value_text(detail.value))
                                for detail in (
                                    *term.details,
                                    *self._weight_provenance_details(
                                        term.weight_label,
                                        weight_provenance,
                                    ),
                                )
                            ),
                            dominant=(
                                dominant_term is not None
                                and term.name == dominant_term.name
                                and abs(term.value) == abs(dominant_term.value)
                            ),
                        )
                        for term in breakdown.terms
                    ),
                    key=lambda item: (item["is_zero"], -cast(float, item["numeric_value"])),
                )
            ),
        }

    def _score_additions_text(self, breakdown: ActionScoreBreakdown) -> str:
        non_zero_terms = tuple(term for term in breakdown.terms if abs(term.value) > 1e-9)
        return signed_additions_text(
            tuple(term.value for term in non_zero_terms),
            total=breakdown.total,
            zero_text=f"{breakdown.total:.2f} = 0.00",
        )

    def _term_formula_text(self, term: ScoreTerm) -> str:
        if (
            term.weight is not None
            and term.weight_label is not None
            and term.raw_value is not None
            and term.raw_label is not None
        ):
            return (
                f"{term.weight_label} {MULTIPLICATION_SIGN} {term.raw_label} = "
                f"{math_number_text(term.weight)} {MULTIPLICATION_SIGN} "
                f"{math_number_text(term.raw_value)} = "
                f"{math_number_text(term.value)}"
            )
        if term.formula is not None and len(term.details) == 1:
            detail = term.details[0]
            if detail.key == term.formula:
                return f"{term.formula} = {self._detail_value_text(detail.value)}"
            return (
                f"{term.formula} ({detail.key}) = {self._detail_value_text(detail.value)} = "
                f"{math_number_text(term.value)}"
            )
        if term.formula is not None:
            return f"{term.formula} = {math_number_text(term.value)}"
        return f"contribution = {math_number_text(term.value)}"

    @staticmethod
    def _detail_value_text(value: float | int | str) -> str:
        if isinstance(value, float | int):
            return math_number_text(value)
        return str(value)

    @staticmethod
    def _weight_provenance_details(
        weight_label: str | None,
        weight_provenance: Mapping[str, WeightProvenance],
    ) -> tuple[ScoreTermDetail, ...]:
        if weight_label is None:
            return ()
        provenance = weight_provenance.get(weight_label)
        if provenance is None:
            return ()
        details = [
            ScoreTermDetail("weight_base_config", provenance.base_config),
            ScoreTermDetail(
                "weight_profile_override",
                "none" if provenance.profile_override is None else provenance.profile_override,
            ),
        ]
        details.extend(
            ScoreTermDetail(adjustment.label, adjustment.factor)
            for adjustment in provenance.adjustments
        )
        details.append(ScoreTermDetail("resolved_weight", provenance.resolved))
        return tuple(details)
