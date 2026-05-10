from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from gwent_engine.ai.search import (
    SearchCandidateEvaluation,
    SearchDecisionExplanation,
    SearchLine,
    SearchReplyExplanation,
    SearchTraceFact,
    SearchValueTerm,
)
from gwent_engine.cli.report.common import (
    MULTIPLICATION_SIGN,
    dominant_term_context,
    math_number_text,
    numeric_term_context,
    signed_additions_text,
)
from gwent_engine.cli.report.format import HTMLFormatter
from gwent_engine.core.actions import GameAction

ActionText = Callable[[GameAction], str]


@dataclass(slots=True)
class SearchTracePresenter:
    formatter: HTMLFormatter
    action_text: ActionText

    def ordered_evaluations(
        self,
        explanation: SearchDecisionExplanation,
    ) -> tuple[SearchCandidateEvaluation, ...]:
        chosen = tuple(evaluation for evaluation in explanation.evaluations if evaluation.selected)
        others = tuple(
            sorted(
                (evaluation for evaluation in explanation.evaluations if not evaluation.selected),
                key=lambda item: (-item.line.value, item.root_rank),
            )
        )
        return (*chosen, *others)

    def line_traces_context(
        self,
        explanation: SearchDecisionExplanation,
    ) -> tuple[dict[str, object], ...]:
        chosen = next(
            (evaluation for evaluation in explanation.evaluations if evaluation.selected),
            None,
        )
        if chosen is None:
            return ()
        ordered = self.ordered_evaluations(explanation)
        runner_up = next(
            (evaluation for evaluation in ordered if evaluation.action != chosen.action),
            None,
        )
        panels = [self.line_trace_context(chosen, label="Chosen Line")]
        if runner_up is not None:
            panels.append(self.line_trace_context(runner_up, label="Runner-up Line"))
            self._annotate_selected_trace_fact_differences(
                selected_trace=panels[0],
                runner_up_trace=panels[1],
            )
        return tuple(panels)

    def ranked_action_context(
        self,
        evaluation: SearchCandidateEvaluation,
        *,
        popover_id: str,
    ) -> dict[str, object]:
        return {
            "kind": "searched",
            "action": self.formatter.fmt(self.action_text(evaluation.action)),
            "score": f"{evaluation.line.value:.2f}",
            "score_derivation": self.score_derivation_context(
                evaluation,
                popover_id=popover_id,
            ),
            "terms": (
                {
                    "key": self.formatter.fmt("root_reason"),
                    "value": self.formatter.fmt(evaluation.reason),
                },
                {
                    "key": self.formatter.fmt("reply"),
                    "value": self.formatter.fmt(
                        self.reply_summary_text(evaluation.line.explanation.reply)
                    ),
                },
            ),
        }

    def score_derivation_context(
        self,
        evaluation: SearchCandidateEvaluation,
        *,
        popover_id: str,
    ) -> dict[str, object]:
        trace_terms = self._trace_terms(evaluation.line)
        dominant_term = (
            max(trace_terms, key=lambda term: (abs(term.value), term.name)) if trace_terms else None
        )
        return {
            "popover_id": popover_id,
            "button_label": self.formatter.fmt(f"value={evaluation.line.value:.2f}"),
            "title": self.formatter.fmt(f"Search Line Trace ({evaluation.line.value:.2f})"),
            "total": f"{evaluation.line.value:.2f}",
            "additions": self.formatter.fmt(self._line_additions_text(trace_terms)),
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
                            formula=self._formula_text(term.formula, fallback=term.name),
                            details=tuple((detail.key, detail.value) for detail in term.details),
                            dominant=(
                                dominant_term is not None
                                and term.name == dominant_term.name
                                and abs(term.value) == abs(dominant_term.value)
                            ),
                        )
                        for term in trace_terms
                    ),
                    key=lambda item: (item["is_zero"], -abs(cast(float, item["numeric_value"]))),
                )
            ),
            "sections": self.trace_sections_context(evaluation),
        }

    def line_trace_context(
        self,
        evaluation: SearchCandidateEvaluation,
        *,
        label: str,
    ) -> dict[str, object]:
        return {
            "label": self.formatter.fmt(label),
            "action": self.formatter.fmt(self.action_text(evaluation.action)),
            "value": f"{evaluation.line.value:.2f}",
            "selected": evaluation.selected,
            "sections": self.trace_sections_context(evaluation),
        }

    def trace_sections_context(
        self,
        evaluation: SearchCandidateEvaluation,
    ) -> tuple[dict[str, object], ...]:
        sections: list[dict[str, object]] = [
            self._trace_section_context(
                "Root",
                facts=(
                    SearchTraceFact("root_rank", str(evaluation.root_rank)),
                    SearchTraceFact(
                        "root_ordering_score",
                        math_number_text(evaluation.ordering_score),
                    ),
                    SearchTraceFact("root_reason", evaluation.reason),
                ),
            ),
            self._trace_section_context(
                "Self Turn",
                actions=evaluation.line.actions,
                facts=evaluation.line.explanation.self_turn_facts,
            ),
        ]
        reply = evaluation.line.explanation.reply
        if reply is not None:
            reply_facts = [
                SearchTraceFact("reply_kind", reply.kind),
                SearchTraceFact("reply_reason", reply.reason),
            ]
            if abs(reply.value_adjustment) > 1e-9:
                reply_facts.append(
                    SearchTraceFact(
                        "reply_value_adjustment",
                        math_number_text(reply.value_adjustment),
                    )
                )
            reply_facts.extend(reply.notes)
            sections.append(
                self._trace_section_context(
                    "Opponent Reply",
                    actions=reply.actions,
                    facts=tuple(reply_facts),
                    terms=reply.components,
                )
            )
        sections.append(
            self._trace_section_context(
                "Leaf Evaluation",
                facts=evaluation.line.explanation.leaf_facts,
                terms=evaluation.line.explanation.leaf_terms,
            )
        )
        if evaluation.line.explanation.root_adjustments:
            sections.append(
                self._trace_section_context(
                    "Root Adjustments",
                    terms=evaluation.line.explanation.root_adjustments,
                )
            )
        return tuple(sections)

    def _trace_section_context(
        self,
        label: str,
        *,
        facts: tuple[SearchTraceFact, ...] = (),
        actions: tuple[GameAction, ...] = (),
        terms: tuple[SearchValueTerm, ...] = (),
    ) -> dict[str, object]:
        overlapping_fact_keys = {term.name for term in terms} & {fact.key for fact in facts}
        return {
            "label": self.formatter.fmt(label),
            "has_differences": False,
            "facts": tuple(
                {
                    "key": self.formatter.fmt(
                        f"{fact.key} (input)" if fact.key in overlapping_fact_keys else fact.key
                    ),
                    "value": self.formatter.fmt(fact.value),
                    "changed": False,
                }
                for fact in facts
            ),
            "actions": tuple(self.formatter.fmt(self.action_text(action)) for action in actions),
            "terms": tuple(self._value_term_context(term) for term in terms),
        }

    @staticmethod
    def _annotate_selected_trace_fact_differences(
        *,
        selected_trace: dict[str, object],
        runner_up_trace: dict[str, object],
    ) -> None:
        selected_sections = cast(tuple[dict[str, object], ...], selected_trace["sections"])
        runner_up_sections = cast(tuple[dict[str, object], ...], runner_up_trace["sections"])
        runner_up_by_label = {
            cast(str, section["label"]): section for section in runner_up_sections
        }
        for selected_section in selected_sections:
            runner_up_section = runner_up_by_label.get(cast(str, selected_section["label"]))
            SearchTracePresenter._annotate_selected_section_fact_differences(
                selected_section=selected_section,
                runner_up_section=runner_up_section,
            )

    @staticmethod
    def _annotate_selected_section_fact_differences(
        *,
        selected_section: dict[str, object],
        runner_up_section: dict[str, object] | None,
    ) -> None:
        selected_facts = cast(tuple[dict[str, object], ...], selected_section["facts"])
        runner_up_facts = (
            ()
            if runner_up_section is None
            else cast(tuple[dict[str, object], ...], runner_up_section["facts"])
        )
        runner_up_by_key = {cast(str, fact["key"]): fact for fact in runner_up_facts}
        section_has_differences = False
        for selected_fact in selected_facts:
            runner_up_fact = runner_up_by_key.get(cast(str, selected_fact["key"]))
            runner_up_value = None if runner_up_fact is None else runner_up_fact["value"]
            changed = selected_fact["value"] != runner_up_value
            section_has_differences = section_has_differences or changed
            selected_fact["changed"] = changed
        selected_section["has_differences"] = section_has_differences

    def _value_term_context(
        self,
        term: SearchValueTerm,
    ) -> dict[str, object]:
        return {
            "name": self.formatter.fmt(term.name),
            "value": f"{term.value:.2f}",
            "details": tuple(
                {
                    "key": self.formatter.fmt(detail.key),
                    "value": self.formatter.fmt(detail.value),
                }
                for detail in term.details
            ),
            "formula": (
                None
                if term.formula is None
                else self.formatter.fmt(self._formula_text(term.formula))
            ),
        }

    def _trace_terms(
        self,
        line: SearchLine,
    ) -> tuple[SearchValueTerm, ...]:
        terms = list(line.explanation.leaf_terms)
        reply = line.explanation.reply
        if reply is not None and abs(reply.value_adjustment) > 1e-9:
            terms.append(
                SearchValueTerm(
                    name=reply.reason,
                    value=reply.value_adjustment,
                    formula="reply value adjustment",
                    details=(
                        *reply.notes,
                        *tuple(
                            SearchTraceFact(component.name, math_number_text(component.value))
                            for component in reply.components
                        ),
                    ),
                )
            )
        terms.extend(line.explanation.root_adjustments)
        return tuple(terms)

    def _line_additions_text(
        self,
        terms: tuple[SearchValueTerm, ...],
    ) -> str:
        non_zero_terms = tuple(term for term in terms if abs(term.value) > 1e-9)
        return signed_additions_text(
            tuple(term.value for term in non_zero_terms),
            total=sum(term.value for term in non_zero_terms),
            zero_text="0.00 = 0.00",
        )

    @staticmethod
    def reply_summary_text(reply: SearchReplyExplanation | None) -> str:
        if reply is None:
            return "none"
        if reply.kind == "none":
            return f"none ({reply.reason})"
        if reply.actions:
            return f"{reply.kind} ({len(reply.actions)} action)"
        return reply.kind

    @staticmethod
    def _formula_text(formula: str | None, *, fallback: str | None = None) -> str:
        text = formula or f"{fallback} contribution"
        return text.replace("*", MULTIPLICATION_SIGN)
