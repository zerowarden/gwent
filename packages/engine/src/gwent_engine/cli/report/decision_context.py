from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gwent_engine.ai.baseline import ActionScoreBreakdown
from gwent_engine.ai.debug import CandidateExplanation, HeuristicDecisionExplanation
from gwent_engine.ai.search import SearchDecisionExplanation
from gwent_engine.cli.models import BotDecisionExplanation, CliStep
from gwent_engine.cli.report.common import formatted_summary
from gwent_engine.cli.report.format import HTMLFormatter
from gwent_engine.cli.report.score_derivation import ScoreDerivationPresenter
from gwent_engine.cli.report.search_trace import SearchTracePresenter
from gwent_engine.core.actions import GameAction, PassAction

ActionText = Callable[[GameAction], str]


@dataclass(slots=True)
class DecisionContextPresenter:
    formatter: HTMLFormatter
    action_text: ActionText
    score_derivation: ScoreDerivationPresenter
    search_trace: SearchTracePresenter

    def ranked_actions(
        self,
        step: CliStep,
        step_index: int,
    ) -> tuple[dict[str, object], ...]:
        explanation = step.bot_explanation
        if explanation is None:
            return ()
        if isinstance(explanation, SearchDecisionExplanation):
            return tuple(
                self.search_trace.ranked_action_context(
                    evaluation,
                    popover_id=f"score-popover-step-{step_index}-{index}",
                )
                for index, evaluation in enumerate(
                    self.search_trace.ordered_evaluations(explanation)[:3],
                    start=1,
                )
            )
        return tuple(
            {
                "kind": "ranked",
                "action": self.formatter.fmt(self.action_text(breakdown.action)),
                "score": f"{breakdown.total:.2f}",
                "score_derivation": self.score_derivation.context(
                    breakdown,
                    explanation.profile,
                    popover_id=f"score-popover-step-{step_index}-{index}",
                ),
                "terms": tuple(
                    {
                        "key": self.formatter.fmt(term.name),
                        "value": f"{term.value:.2f}",
                    }
                    for term in breakdown.terms[:6]
                ),
            }
            for index, breakdown in enumerate(explanation.ranked_actions[:3], start=1)
        )

    def comparison(self, step: CliStep) -> dict[str, object] | None:
        explanation = step.bot_explanation
        if explanation is None:
            return None
        if isinstance(explanation, SearchDecisionExplanation):
            search_comparison = explanation.comparison
            if search_comparison is None:
                return None
            return {
                "summary": formatted_summary(
                    self.formatter,
                    (
                        ("Selection Source", "search"),
                        ("Chosen Action", self.action_text(search_comparison.chosen_action)),
                        (
                            "Runner-up",
                            "n/a"
                            if search_comparison.runner_up_action is None
                            else self.action_text(search_comparison.runner_up_action),
                        ),
                        (
                            "Chosen Value",
                            "n/a"
                            if search_comparison.chosen_value is None
                            else f"{search_comparison.chosen_value:.2f}",
                        ),
                        (
                            "Runner-up Value",
                            "n/a"
                            if search_comparison.runner_up_value is None
                            else f"{search_comparison.runner_up_value:.2f}",
                        ),
                        (
                            "Margin",
                            "n/a"
                            if search_comparison.value_margin is None
                            else f"{search_comparison.value_margin:.2f}",
                        ),
                    ),
                ),
                "terms": tuple(
                    {
                        "key": self.formatter.fmt(key),
                        "value": self.formatter.fmt(value),
                    }
                    for key, value in (
                        ("Chosen Root Reason", search_comparison.chosen_reason or "n/a"),
                        ("Runner-up Root Reason", search_comparison.runner_up_reason or "n/a"),
                    )
                ),
            }
        heuristic_comparison = explanation.comparison
        if heuristic_comparison is None:
            return None
        return {
            "summary": formatted_summary(
                self.formatter,
                (
                    ("Selection Source", heuristic_comparison.selection_source),
                    ("Chosen Action", self.action_text(heuristic_comparison.chosen_action)),
                    (
                        "Runner-up",
                        "n/a"
                        if heuristic_comparison.runner_up_action is None
                        else self.action_text(heuristic_comparison.runner_up_action),
                    ),
                    (
                        "Chosen Score",
                        "n/a"
                        if heuristic_comparison.chosen_score is None
                        else f"{heuristic_comparison.chosen_score:.2f}",
                    ),
                    (
                        "Runner-up Score",
                        "n/a"
                        if heuristic_comparison.runner_up_score is None
                        else f"{heuristic_comparison.runner_up_score:.2f}",
                    ),
                    (
                        "Margin",
                        "n/a"
                        if heuristic_comparison.score_margin is None
                        else f"{heuristic_comparison.score_margin:.2f}",
                    ),
                ),
            ),
            "terms": tuple(
                {
                    "key": self.formatter.fmt(term.name),
                    "value": self.formatter.fmt(
                        f"{term.delta:.2f} ({term.chosen_value:.2f} vs {term.runner_up_value:.2f})"
                    ),
                }
                for term in heuristic_comparison.decisive_terms
            ),
        }

    def candidate_diagnosis(self, step: CliStep) -> tuple[dict[str, object], ...]:
        explanation = step.bot_explanation
        if explanation is None:
            return ()
        if isinstance(explanation, SearchDecisionExplanation):
            return tuple(
                {
                    "action": self.formatter.fmt(self.action_text(evaluation.action)),
                    "coarse_rank": str(evaluation.root_rank),
                    "coarse_score": f"{evaluation.ordering_score:.2f}",
                    "status": "selected" if evaluation.selected else "searched",
                    "reason": self.formatter.fmt(evaluation.reason),
                    "prune_reason": None,
                    "selected": evaluation.selected,
                    "trace": self.search_trace.line_trace_context(
                        evaluation,
                        label="Candidate Trace",
                    ),
                }
                for evaluation in explanation.evaluations[:6]
            )
        return tuple(
            {
                "action": self.formatter.fmt(self.action_text(candidate.action)),
                "coarse_rank": str(candidate.coarse_rank),
                "coarse_score": f"{candidate.coarse_score:.2f}",
                "status": candidate_status(candidate),
                "reason": self.formatter.fmt(candidate.reason),
                "prune_reason": (
                    None
                    if candidate.prune_reason is None
                    else self.formatter.fmt(candidate.prune_reason)
                ),
                "selected": candidate.selected,
            }
            for candidate in explanation.candidates[:6]
        )


def ranked_actions_title(explanation: BotDecisionExplanation | None) -> str:
    return _search_or_baseline_title(
        explanation,
        search_title="Search Evaluated Lines",
        baseline_title="Baseline Ranked Actions",
    )


def decision_comparison_title(explanation: BotDecisionExplanation | None) -> str:
    return _search_or_baseline_title(
        explanation,
        search_title="Search Decision",
        baseline_title="Decision Diagnosis",
    )


def candidate_diagnosis_title(explanation: BotDecisionExplanation | None) -> str:
    return _search_or_baseline_title(
        explanation,
        search_title="Search Root Candidates",
        baseline_title="Candidate Pool",
    )


def _search_or_baseline_title(
    explanation: BotDecisionExplanation | None,
    *,
    search_title: str,
    baseline_title: str,
) -> str:
    return search_title if isinstance(explanation, SearchDecisionExplanation) else baseline_title


def override_reason(explanation: BotDecisionExplanation | None) -> str | None:
    if explanation is None or not isinstance(explanation, HeuristicDecisionExplanation):
        return None
    return None if explanation.override is None else explanation.override.reason


def pass_debug_details(explanation: HeuristicDecisionExplanation) -> dict[str, int]:
    tempo_per_card = (
        explanation.profile.elimination_estimated_opponent_tempo_per_card
        if explanation.context.pressure.value == "elimination"
        else explanation.profile.estimated_opponent_tempo_per_card
    )
    estimated_opponent_response = explanation.assessment.opponent.hand_count * tempo_per_card
    required_lead = max(explanation.profile.pass_lead_margin, estimated_opponent_response)
    return {
        "margin_floor": explanation.profile.pass_lead_margin,
        "tempo_per_card": tempo_per_card,
        "estimated_opponent_response": estimated_opponent_response,
        "required_lead": required_lead,
        "projection": explanation.assessment.score_gap - required_lead,
    }


def best_non_pass_breakdown(
    explanation: HeuristicDecisionExplanation,
) -> ActionScoreBreakdown | None:
    return next(
        (
            breakdown
            for breakdown in explanation.ranked_actions
            if not isinstance(breakdown.action, PassAction)
        ),
        None,
    )


def pass_score_delta(
    explanation: HeuristicDecisionExplanation,
    best_non_pass: ActionScoreBreakdown,
) -> float:
    pass_breakdown = next(
        (
            breakdown
            for breakdown in explanation.ranked_actions
            if isinstance(breakdown.action, PassAction)
        ),
        None,
    )
    if pass_breakdown is None:
        return 0.0
    return pass_breakdown.total - best_non_pass.total


def candidate_status(candidate: CandidateExplanation) -> str:
    if candidate.selected:
        return "selected"
    if candidate.shortlisted:
        return "shortlisted"
    if candidate.retained:
        return "retained"
    if candidate.prune_stage == "candidate_pool":
        return "pruned in candidate pool"
    if candidate.prune_stage == "shortlist":
        return "pruned before shortlist"
    return "considered"
