from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from gwent_engine.ai.debug import HeuristicDecisionExplanation, heuristic_decision_to_dict
from gwent_engine.ai.search import (
    SearchCandidate,
    SearchCandidateEvaluation,
    SearchDecisionComparison,
    SearchDecisionExplanation,
    SearchLine,
    SearchLineExplanation,
    SearchReplyExplanation,
    SearchTraceFact,
    SearchValueTerm,
)
from gwent_engine.cli.models import BotDecisionExplanation, CliRun, CliStep
from gwent_engine.cli.render_json import action_to_dict, metadata_to_dict
from gwent_engine.core.ids import CardInstanceId
from gwent_engine.serialize import event_to_dict, game_state_to_dict

AUDIT_SCHEMA_VERSION = 1


def build_bot_match_audit_payload(
    run: CliRun,
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    seed: int,
    generated_at: str,
) -> dict[str, object]:
    return {
        "type": "bot_match_audit",
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "scenario": run.scenario_name,
        "seed": seed,
        "bot_specs": {
            "p1": player_one_bot_spec,
            "p2": player_two_bot_spec,
        },
        "metadata": metadata_to_dict(run.metadata),
        "card_metadata": {
            str(card_id): {
                "name": run.card_names_by_instance_id[card_id],
                "base_value": run.card_values_by_instance_id[card_id],
                "kind": run.card_kinds_by_instance_id[card_id],
                "is_spy": run.card_spy_by_instance_id[card_id],
                "is_medic": run.card_medic_by_instance_id[card_id],
                "is_horn": run.card_horn_by_instance_id[card_id],
                "is_scorch": run.card_scorch_by_instance_id[card_id],
            }
            for card_id in run.card_names_by_instance_id
        },
        "pending_choice_state": (
            None
            if run.pending_choice_state is None
            else game_state_to_dict(run.pending_choice_state)
        ),
        "steps": [
            step_to_audit_dict(step, index=index) for index, step in enumerate(run.steps, start=1)
        ],
        "final_state": game_state_to_dict(run.final_state),
        "final_effective_strengths": _strengths_to_dict(run.final_strengths_by_instance_id),
    }


def step_to_audit_dict(step: CliStep, *, index: int) -> dict[str, object]:
    return {
        "index": index,
        "action": action_to_dict(step.action),
        "events": [event_to_dict(event) for event in step.events],
        "state_before": game_state_to_dict(step.state_before),
        "state_after": game_state_to_dict(step.state_after),
        "effective_strengths_before": _strengths_to_dict(step.effective_strengths_before),
        "effective_strengths_after": _strengths_to_dict(step.effective_strengths_after),
        "round_summary_state": (
            None
            if step.round_summary_state is None
            else game_state_to_dict(step.round_summary_state)
        ),
        "round_summary_strengths": _strengths_to_dict(step.round_summary_strengths),
        "bot_explanation": bot_explanation_to_dict(step.bot_explanation),
    }


def bot_explanation_to_dict(explanation: BotDecisionExplanation | None) -> dict[str, object] | None:
    if explanation is None:
        return None
    if isinstance(explanation, HeuristicDecisionExplanation):
        return {
            "kind": "heuristic",
            **heuristic_decision_to_dict(explanation),
        }
    return {
        "kind": "search",
        **search_decision_to_dict(explanation),
    }


def search_decision_to_dict(explanation: SearchDecisionExplanation) -> dict[str, object]:
    return {
        "chosen_action": action_to_dict(explanation.chosen_action),
        "profile_id": explanation.profile_id,
        "config": asdict(explanation.config),
        "used_fallback_policy": explanation.used_fallback_policy,
        "candidates": [search_candidate_to_dict(candidate) for candidate in explanation.candidates],
        "evaluations": [
            search_candidate_evaluation_to_dict(evaluation)
            for evaluation in explanation.evaluations
        ],
        "principal_line": (
            None
            if explanation.principal_line is None
            else search_line_to_dict(explanation.principal_line)
        ),
        "comparison": (
            None
            if explanation.comparison is None
            else search_decision_comparison_to_dict(explanation.comparison)
        ),
        "notes": list(explanation.notes),
    }


def search_candidate_to_dict(candidate: SearchCandidate) -> dict[str, object]:
    return {
        "action": action_to_dict(candidate.action),
        "ordering_score": candidate.ordering_score,
        "reason": candidate.reason,
    }


def search_candidate_evaluation_to_dict(
    evaluation: SearchCandidateEvaluation,
) -> dict[str, object]:
    return {
        "action": action_to_dict(evaluation.action),
        "root_rank": evaluation.root_rank,
        "ordering_score": evaluation.ordering_score,
        "reason": evaluation.reason,
        "line": search_line_to_dict(evaluation.line),
        "selected": evaluation.selected,
    }


def search_line_to_dict(line: SearchLine) -> dict[str, object]:
    return {
        "actions": [action_to_dict(action) for action in line.actions],
        "reply_actions": [action_to_dict(action) for action in line.reply_actions],
        "value": line.value,
        "explanation": search_line_explanation_to_dict(line.explanation),
        "notes": list(line.notes),
    }


def search_line_explanation_to_dict(
    explanation: SearchLineExplanation,
) -> dict[str, object]:
    return {
        "self_turn_facts": [
            search_trace_fact_to_dict(fact) for fact in explanation.self_turn_facts
        ],
        "leaf_facts": [search_trace_fact_to_dict(fact) for fact in explanation.leaf_facts],
        "leaf_terms": [search_value_term_to_dict(term) for term in explanation.leaf_terms],
        "reply": (
            None
            if explanation.reply is None
            else search_reply_explanation_to_dict(explanation.reply)
        ),
        "root_adjustments": [
            search_value_term_to_dict(term) for term in explanation.root_adjustments
        ],
    }


def search_reply_explanation_to_dict(reply: SearchReplyExplanation) -> dict[str, object]:
    return {
        "kind": reply.kind,
        "reason": reply.reason,
        "actions": [action_to_dict(action) for action in reply.actions],
        "value_adjustment": reply.value_adjustment,
        "components": [search_value_term_to_dict(term) for term in reply.components],
        "notes": [search_trace_fact_to_dict(note) for note in reply.notes],
    }


def search_value_term_to_dict(term: SearchValueTerm) -> dict[str, object]:
    return {
        "name": term.name,
        "value": term.value,
        "formula": term.formula,
        "details": [search_trace_fact_to_dict(detail) for detail in term.details],
    }


def search_trace_fact_to_dict(fact: SearchTraceFact) -> dict[str, object]:
    return {
        "key": fact.key,
        "value": fact.value,
    }


def search_decision_comparison_to_dict(
    comparison: SearchDecisionComparison,
) -> dict[str, object]:
    return {
        "chosen_action": action_to_dict(comparison.chosen_action),
        "runner_up_action": (
            None
            if comparison.runner_up_action is None
            else action_to_dict(comparison.runner_up_action)
        ),
        "chosen_value": comparison.chosen_value,
        "runner_up_value": comparison.runner_up_value,
        "value_margin": comparison.value_margin,
        "chosen_reason": comparison.chosen_reason,
        "runner_up_reason": comparison.runner_up_reason,
    }


def _strengths_to_dict(
    strengths_by_instance_id: Mapping[CardInstanceId, int],
) -> dict[str, int]:
    return {str(card_id): strength for card_id, strength in strengths_by_instance_id.items()}
