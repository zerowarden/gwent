from __future__ import annotations

from dataclasses import dataclass

from gwent_engine.ai.actions import action_to_id, enumerate_legal_actions
from gwent_engine.ai.baseline import (
    DEFAULT_BASE_PROFILE,
    ActionScoreBreakdown,
    BaseProfileDefinition,
    DecisionAssessment,
    DecisionContext,
    HeuristicProfile,
    TacticalOverride,
    build_decision_plan,
)
from gwent_engine.ai.observations import PlayerObservation, build_player_observation
from gwent_engine.ai.policy import DEFAULT_BASELINE_CONFIG, BaselineConfig
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import GameAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry


@dataclass(frozen=True, slots=True)
class CandidateExplanation:
    action: GameAction
    action_id: str
    coarse_score: float
    coarse_rank: int
    reason: str
    always_keep: bool
    retained: bool
    shortlisted: bool
    ranked: bool
    selected: bool
    prune_stage: str | None
    prune_reason: str | None
    score_breakdown: ActionScoreBreakdown | None = None


@dataclass(frozen=True, slots=True)
class DecisionDeltaTerm:
    name: str
    chosen_value: float
    runner_up_value: float
    delta: float


@dataclass(frozen=True, slots=True)
class DecisionComparison:
    selection_source: str
    chosen_action: GameAction
    runner_up_action: GameAction | None
    chosen_score: float | None
    runner_up_score: float | None
    score_margin: float | None
    decisive_terms: tuple[DecisionDeltaTerm, ...]


@dataclass(frozen=True, slots=True)
class HeuristicDecisionExplanation:
    assessment: DecisionAssessment
    context: DecisionContext
    profile: HeuristicProfile
    candidates: tuple[CandidateExplanation, ...]
    ranked_actions: tuple[ActionScoreBreakdown, ...]
    override: TacticalOverride | None
    comparison: DecisionComparison | None
    chosen_action: GameAction


@dataclass(frozen=True, slots=True)
class DecisionExplainer:
    card_registry: CardRegistry
    leader_registry: LeaderRegistry | None = None
    config: BaselineConfig = DEFAULT_BASELINE_CONFIG
    profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE

    def explain_heuristic(
        self,
        observation: PlayerObservation,
        legal_actions: tuple[GameAction, ...],
    ) -> HeuristicDecisionExplanation:
        plan = build_decision_plan(
            observation,
            legal_actions,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
            config=self.config,
            profile_definition=self.profile_definition,
        )
        ranked_by_action_id = {
            action_to_id(breakdown.action): breakdown for breakdown in plan.ranked_actions
        }
        retained_ids = {action_to_id(candidate.action) for candidate in plan.candidates}
        shortlisted_ids = {action_to_id(action) for action in plan.shortlisted_actions}
        chosen_action_id = action_to_id(plan.chosen_action)
        return HeuristicDecisionExplanation(
            assessment=plan.assessment,
            context=plan.context,
            profile=plan.profile,
            candidates=tuple(
                CandidateExplanation(
                    action=candidate.action,
                    action_id=action_to_id(candidate.action),
                    coarse_score=candidate.coarse_score,
                    coarse_rank=index,
                    reason=candidate.reason,
                    always_keep=candidate.always_keep,
                    retained=action_to_id(candidate.action) in retained_ids,
                    shortlisted=action_to_id(candidate.action) in shortlisted_ids,
                    ranked=action_to_id(candidate.action) in ranked_by_action_id,
                    selected=action_to_id(candidate.action) == chosen_action_id,
                    prune_stage=_candidate_prune_stage(
                        candidate_action_id=action_to_id(candidate.action),
                        retained_ids=retained_ids,
                        shortlisted_ids=shortlisted_ids,
                    ),
                    prune_reason=_candidate_prune_reason(
                        candidate_action_id=action_to_id(candidate.action),
                        retained_ids=retained_ids,
                        shortlisted_ids=shortlisted_ids,
                    ),
                    score_breakdown=ranked_by_action_id.get(action_to_id(candidate.action)),
                )
                for index, candidate in enumerate(plan.all_candidates, start=1)
            ),
            ranked_actions=plan.ranked_actions,
            override=plan.override,
            comparison=_build_decision_comparison(
                ranked_actions=plan.ranked_actions,
                chosen_action=plan.chosen_action,
                override=plan.override,
            ),
            chosen_action=plan.chosen_action,
        )

    def explain_heuristic_from_state(
        self,
        state: GameState,
        *,
        player_id: PlayerId | None = None,
        legal_actions: tuple[GameAction, ...] | None = None,
    ) -> HeuristicDecisionExplanation:
        viewer_player_id = player_id or _observation_player_id(state)
        resolved_legal_actions = legal_actions or enumerate_legal_actions(
            state,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
            player_id=viewer_player_id,
        )
        return self.explain_heuristic(
            build_player_observation(state, viewer_player_id, self.leader_registry),
            resolved_legal_actions,
        )


def explain_heuristic_decision(
    observation: PlayerObservation,
    legal_actions: tuple[GameAction, ...],
    *,
    card_registry: CardRegistry,
    config: BaselineConfig = DEFAULT_BASELINE_CONFIG,
    profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
) -> HeuristicDecisionExplanation:
    return DecisionExplainer(
        card_registry=card_registry,
        config=config,
        profile_definition=profile_definition,
    ).explain_heuristic(observation, legal_actions)


def explain_heuristic_decision_from_state(
    state: GameState,
    *,
    card_registry: CardRegistry,
    leader_registry: LeaderRegistry | None = None,
    config: BaselineConfig = DEFAULT_BASELINE_CONFIG,
    profile_definition: BaseProfileDefinition = DEFAULT_BASE_PROFILE,
    player_id: PlayerId | None = None,
    legal_actions: tuple[GameAction, ...] | None = None,
) -> HeuristicDecisionExplanation:
    return DecisionExplainer(
        card_registry=card_registry,
        leader_registry=leader_registry,
        config=config,
        profile_definition=profile_definition,
    ).explain_heuristic_from_state(
        state,
        player_id=player_id,
        legal_actions=legal_actions,
    )


def heuristic_decision_to_dict(explanation: HeuristicDecisionExplanation) -> dict[str, object]:
    return {
        "assessment": {
            "viewer_player_id": str(explanation.assessment.viewer_player_id),
            "score_gap": explanation.assessment.score_gap,
            "card_advantage": explanation.assessment.card_advantage,
            "viewer_hand_count": explanation.assessment.viewer.hand_count,
            "opponent_hand_count": explanation.assessment.opponent.hand_count,
        },
        "context": {
            "tempo": explanation.context.tempo.value,
            "mode": explanation.context.mode.value,
            "pressure": explanation.context.pressure.value,
            "preserve_resources": explanation.context.preserve_resources,
            "prioritize_immediate_points": explanation.context.prioritize_immediate_points,
            "minimum_commitment_mode": explanation.context.minimum_commitment_mode,
        },
        "profile": {
            "profile_id": explanation.profile.profile_id,
            "policy_names": {
                "scorch": explanation.profile.policy_names.scorch_policy,
                "leader": explanation.profile.policy_names.leader_policy,
            },
            "weight_provenance": {
                item.name: {
                    "base_config": item.base_config,
                    "profile_override": item.profile_override,
                    "adjustments": [
                        {
                            "label": adjustment.label,
                            "factor": adjustment.factor,
                        }
                        for adjustment in item.adjustments
                    ],
                    "resolved": item.resolved,
                }
                for item in explanation.profile.weight_provenance
            },
        },
        "candidates": [
            candidate_explanation_to_dict(candidate) for candidate in explanation.candidates
        ],
        "ranked_actions": [
            action_score_breakdown_to_dict(breakdown) for breakdown in explanation.ranked_actions
        ],
        "override": (
            {
                "action": _action_summary(explanation.override.action),
                "reason": explanation.override.reason,
            }
            if explanation.override is not None
            else None
        ),
        "comparison": (
            decision_comparison_to_dict(explanation.comparison)
            if explanation.comparison is not None
            else None
        ),
        "chosen_action": _action_summary(explanation.chosen_action),
    }


def candidate_explanation_to_dict(candidate: CandidateExplanation) -> dict[str, object]:
    return {
        "action": _action_summary(candidate.action),
        "action_id": candidate.action_id,
        "coarse_score": candidate.coarse_score,
        "coarse_rank": candidate.coarse_rank,
        "reason": candidate.reason,
        "always_keep": candidate.always_keep,
        "retained": candidate.retained,
        "shortlisted": candidate.shortlisted,
        "ranked": candidate.ranked,
        "selected": candidate.selected,
        "prune_stage": candidate.prune_stage,
        "prune_reason": candidate.prune_reason,
        "score_breakdown": (
            action_score_breakdown_to_dict(candidate.score_breakdown)
            if candidate.score_breakdown is not None
            else None
        ),
    }


def action_score_breakdown_to_dict(breakdown: ActionScoreBreakdown) -> dict[str, object]:
    return {
        "action": _action_summary(breakdown.action),
        "total": breakdown.total,
        "terms": [
            {
                "name": term.name,
                "value": term.value,
                "formula": term.formula,
                "raw_value": term.raw_value,
                "raw_label": term.raw_label,
                "weight": term.weight,
                "weight_label": term.weight_label,
                "details": [
                    {
                        "key": detail.key,
                        "value": detail.value,
                    }
                    for detail in term.details
                ],
            }
            for term in breakdown.terms
        ],
    }


def decision_comparison_to_dict(comparison: DecisionComparison) -> dict[str, object]:
    return {
        "selection_source": comparison.selection_source,
        "chosen_action": _action_summary(comparison.chosen_action),
        "runner_up_action": (
            None
            if comparison.runner_up_action is None
            else _action_summary(comparison.runner_up_action)
        ),
        "chosen_score": comparison.chosen_score,
        "runner_up_score": comparison.runner_up_score,
        "score_margin": comparison.score_margin,
        "decisive_terms": [
            {
                "name": term.name,
                "chosen_value": term.chosen_value,
                "runner_up_value": term.runner_up_value,
                "delta": term.delta,
            }
            for term in comparison.decisive_terms
        ],
    }


def _observation_player_id(state: GameState) -> PlayerId:
    if state.pending_choice is not None:
        return state.pending_choice.player_id
    if state.current_player is not None:
        return state.current_player
    raise ValueError("Decision explanation requires a current acting player.")


def _candidate_prune_stage(
    *,
    candidate_action_id: str,
    retained_ids: set[str],
    shortlisted_ids: set[str],
) -> str | None:
    return _candidate_prune_value(
        candidate_action_id,
        retained_ids=retained_ids,
        shortlisted_ids=shortlisted_ids,
        dropped_from_pool="candidate_pool",
        dropped_from_shortlist="shortlist",
    )


def _candidate_prune_reason(
    *,
    candidate_action_id: str,
    retained_ids: set[str],
    shortlisted_ids: set[str],
) -> str | None:
    return _candidate_prune_value(
        candidate_action_id,
        retained_ids=retained_ids,
        shortlisted_ids=shortlisted_ids,
        dropped_from_pool="candidate_limit",
        dropped_from_shortlist="below_shortlist_cutoff",
    )


def _candidate_prune_value(
    candidate_action_id: str,
    *,
    retained_ids: set[str],
    shortlisted_ids: set[str],
    dropped_from_pool: str,
    dropped_from_shortlist: str,
) -> str | None:
    if candidate_action_id not in retained_ids:
        return dropped_from_pool
    if candidate_action_id not in shortlisted_ids:
        return dropped_from_shortlist
    return None


def _build_decision_comparison(
    *,
    ranked_actions: tuple[ActionScoreBreakdown, ...],
    chosen_action: GameAction,
    override: TacticalOverride | None,
) -> DecisionComparison | None:
    if not ranked_actions:
        return None
    selection_source = "ranked_choice" if override is None else override.reason
    chosen_breakdown = next(
        (breakdown for breakdown in ranked_actions if breakdown.action == chosen_action),
        None,
    )
    if chosen_breakdown is None:
        return DecisionComparison(
            selection_source=selection_source,
            chosen_action=chosen_action,
            runner_up_action=ranked_actions[0].action,
            chosen_score=None,
            runner_up_score=ranked_actions[0].total,
            score_margin=None,
            decisive_terms=(),
        )
    runner_up = next(
        (breakdown for breakdown in ranked_actions if breakdown.action != chosen_action),
        None,
    )
    return DecisionComparison(
        selection_source=selection_source,
        chosen_action=chosen_action,
        runner_up_action=None if runner_up is None else runner_up.action,
        chosen_score=chosen_breakdown.total,
        runner_up_score=None if runner_up is None else runner_up.total,
        score_margin=(None if runner_up is None else chosen_breakdown.total - runner_up.total),
        decisive_terms=(
            () if runner_up is None else _decision_delta_terms(chosen_breakdown, runner_up)
        ),
    )


def _decision_delta_terms(
    chosen: ActionScoreBreakdown,
    runner_up: ActionScoreBreakdown,
) -> tuple[DecisionDeltaTerm, ...]:
    chosen_terms = {term.name: term.value for term in chosen.terms}
    runner_up_terms = {term.name: term.value for term in runner_up.terms}
    term_names = set(chosen_terms) | set(runner_up_terms)
    deltas = tuple(
        sorted(
            (
                DecisionDeltaTerm(
                    name=name,
                    chosen_value=chosen_terms.get(name, 0.0),
                    runner_up_value=runner_up_terms.get(name, 0.0),
                    delta=chosen_terms.get(name, 0.0) - runner_up_terms.get(name, 0.0),
                )
                for name in term_names
                if abs(chosen_terms.get(name, 0.0) - runner_up_terms.get(name, 0.0)) > 1e-9
            ),
            key=lambda term: (-term.delta, term.name),
        )
    )
    positive = tuple(term for term in deltas if term.delta > 0.0)
    return positive[:5] if positive else deltas[:5]


def _action_summary(action: GameAction) -> dict[str, object]:
    return {
        "id": action_to_id(action),
        "type": type(action).__name__,
    }
