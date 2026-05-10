from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from gwent_engine.ai.baseline import BaseProfileDefinition, HeuristicBot, build_assessment
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.ai.policy import SearchConfig
from gwent_engine.ai.search.candidate_generation import generate_search_candidates
from gwent_engine.ai.search.explain import (
    SearchDecisionComparison,
    SearchDecisionExplanation,
)
from gwent_engine.ai.search.move_ordering import order_search_candidates
from gwent_engine.ai.search.public_info import redact_private_information
from gwent_engine.ai.search.turn_resolution import TurnSearchResolver
from gwent_engine.ai.search.types import (
    SearchCandidate,
    SearchCandidateEvaluation,
    SearchLine,
    SearchLineExplanation,
    SearchResult,
    SearchTraceFact,
    SearchValueTerm,
)
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    MulliganSelection,
    PassAction,
)
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry


@dataclass(slots=True)
class SearchEngine:
    """Public-information search engine.

    Search runs on a redacted engine state:
    the viewer keeps their own private zones, while opponent hidden hand/deck
    identities are collapsed to a stable placeholder definition. The opponent
    side is then modeled from public information:
    explicit pass and exact public leader replies are searched directly, while
    hidden-hand pressure is represented through an inferred public-info reply
    candidate.

    Root selection also applies one deliberate elimination-round safeguard:
    if the viewer is in a final/elimination round, the opponent has not
    already passed, and search still found plausible non-pass continuations,
    `PassAction` is penalized before root comparison. This exists because a
    shallow tree is otherwise too willing to bank a temporary lead and forfeit
    future agency, even when lines like "Decoy back a spy, then draw next turn"
    are still alive.
    """

    config: SearchConfig
    profile_definition: BaseProfileDefinition
    fallback_policy: HeuristicBot

    def choose_mulligan(
        self,
        observation: PlayerObservation,
        legal_selections: Sequence[MulliganSelection],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> MulliganSelection:
        return self.fallback_policy.choose_mulligan(
            observation,
            legal_selections,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )

    def choose_action(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> SearchResult:
        return self._choose_with_search(
            observation,
            tuple(legal_actions),
            card_registry=card_registry,
            leader_registry=leader_registry,
            entry=None,
            apply_elimination_pass_safeguard=True,
            success_notes=(
                "phase=3",
                "search_scope=full_turn_same_player_plus_reply",
                "info_mode=public_redacted",
            ),
        )

    def choose_pending_choice(
        self,
        observation: PlayerObservation,
        legal_actions: Sequence[GameAction],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None = None,
    ) -> SearchResult:
        return self._choose_with_search(
            observation,
            tuple(legal_actions),
            card_registry=card_registry,
            leader_registry=leader_registry,
            entry="pending_choice",
            apply_elimination_pass_safeguard=False,
            success_notes=("phase=3", "entry=pending_choice", "info_mode=public_redacted"),
        )

    def _choose_with_search(
        self,
        observation: PlayerObservation,
        action_options: tuple[GameAction, ...],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None,
        entry: str | None,
        apply_elimination_pass_safeguard: bool,
        success_notes: tuple[str, ...],
    ) -> SearchResult:
        state = observation.engine_state
        if state is None:
            return self._fallback_result(
                observation,
                action_options,
                card_registry=card_registry,
                leader_registry=leader_registry,
                reason="missing_engine_state",
                entry=entry,
            )
        search_state = redact_private_information(
            state,
            viewer_player_id=observation.viewer_player_id,
            card_registry=card_registry,
        )
        ordered_candidates = order_search_candidates(
            generate_search_candidates(
                observation,
                action_options,
                config=self.config,
                card_registry=card_registry,
                leader_registry=leader_registry,
            )
        )
        resolver = TurnSearchResolver(
            viewer_player_id=observation.viewer_player_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        evaluated_candidates = self._evaluate_candidates(
            search_state,
            ordered_candidates,
            resolver=resolver,
        )
        best_evaluation = self._best_evaluation(evaluated_candidates)
        if apply_elimination_pass_safeguard and evaluated_candidates:
            evaluated_candidates = self._apply_elimination_pass_safeguard(
                observation,
                evaluated_candidates,
                card_registry=card_registry,
            )
            best_evaluation = self._best_evaluation(evaluated_candidates)
        if best_evaluation is None:
            return self._fallback_result(
                observation,
                action_options,
                card_registry=card_registry,
                leader_registry=leader_registry,
                candidates=ordered_candidates,
                evaluations=tuple(evaluated_candidates),
                reason="empty_candidate_set",
                entry=entry,
            )
        return self._search_result(
            best_evaluation,
            evaluated_candidates,
            candidates=ordered_candidates,
            notes=success_notes,
        )

    def _fallback_result(
        self,
        observation: PlayerObservation,
        action_options: tuple[GameAction, ...],
        *,
        card_registry: CardRegistry,
        leader_registry: LeaderRegistry | None,
        reason: str,
        entry: str | None,
        candidates: tuple[SearchCandidate, ...] = (),
        evaluations: tuple[SearchCandidateEvaluation, ...] = (),
    ) -> SearchResult:
        chosen_action = (
            self.fallback_policy.choose_pending_choice
            if entry == "pending_choice"
            else self.fallback_policy.choose_action
        )(
            observation,
            action_options,
            card_registry=card_registry,
            leader_registry=leader_registry,
        )
        notes: tuple[str, ...] = ("fallback_policy=heuristic", f"reason={reason}")
        if entry is not None:
            notes = (*notes, f"entry={entry}")
        return SearchResult(
            chosen_action=chosen_action,
            used_fallback_policy=True,
            candidates=candidates,
            evaluations=evaluations,
            notes=notes,
        )

    @staticmethod
    def _search_result(
        best_evaluation: SearchCandidateEvaluation,
        evaluated_candidates: tuple[SearchCandidateEvaluation, ...],
        *,
        candidates: tuple[SearchCandidate, ...],
        notes: tuple[str, ...],
    ) -> SearchResult:
        best_line = best_evaluation.line
        selected_action = best_line.actions[0]
        return SearchResult(
            chosen_action=selected_action,
            candidates=candidates,
            evaluations=tuple(
                SearchCandidateEvaluation(
                    action=item.action,
                    root_rank=item.root_rank,
                    ordering_score=item.ordering_score,
                    reason=item.reason,
                    line=item.line,
                    selected=item.action == selected_action,
                )
                for item in evaluated_candidates
            ),
            principal_line=best_line,
            used_fallback_policy=False,
            notes=notes,
        )

    def _evaluate_candidates(
        self,
        search_state: GameState,
        ordered_candidates: tuple[SearchCandidate, ...],
        *,
        resolver: TurnSearchResolver,
    ) -> tuple[SearchCandidateEvaluation, ...]:
        evaluated_candidates: list[SearchCandidateEvaluation] = []
        for candidate in ordered_candidates:
            line = resolver.resolve_root_action_with_reply(search_state, candidate.action)
            evaluated_candidates.append(
                SearchCandidateEvaluation(
                    action=candidate.action,
                    root_rank=len(evaluated_candidates) + 1,
                    ordering_score=candidate.ordering_score,
                    reason=candidate.reason,
                    line=line,
                )
            )
        return tuple(evaluated_candidates)

    def _best_evaluation(
        self,
        evaluated_candidates: tuple[SearchCandidateEvaluation, ...],
    ) -> SearchCandidateEvaluation | None:
        best: SearchCandidateEvaluation | None = None
        for evaluation in evaluated_candidates:
            if best is None or evaluation.line.value > best.line.value:
                best = evaluation
        return best

    def _apply_elimination_pass_safeguard(
        self,
        observation: PlayerObservation,
        evaluated_candidates: tuple[SearchCandidateEvaluation, ...],
        *,
        card_registry: CardRegistry,
    ) -> tuple[SearchCandidateEvaluation, ...]:
        """Penalize premature passes in elimination states with live lines.

        This is intentionally a root-action adjustment rather than another leaf
        evaluator weight. The bad move pattern is not "pass leaves behind bad
        static metrics"; it is "search surrendered the rest of the round while
        plausible continuations still existed". Round-3 Decoy-reclaim-spy is
        the motivating case, but the principle is broader: if elimination is at
        stake and the opponent has not passed, search should not cash out
        simply because shallow evaluation slightly prefers preserving the
        current score snapshot.
        """

        assessment = build_assessment(observation, card_registry)
        if not assessment.is_elimination_round or assessment.opponent_passed:
            return evaluated_candidates
        pass_evaluation = next(
            (
                evaluation
                for evaluation in evaluated_candidates
                if isinstance(evaluation.action, PassAction)
            ),
            None,
        )
        if pass_evaluation is None:
            return evaluated_candidates
        live_non_pass_lines = tuple(
            evaluation
            for evaluation in evaluated_candidates
            if self._is_live_non_pass_line(
                evaluation,
                pass_value=pass_evaluation.line.value,
            )
        )
        if not live_non_pass_lines:
            return evaluated_candidates
        adjusted_evaluations: list[SearchCandidateEvaluation] = []
        for evaluation in evaluated_candidates:
            if evaluation != pass_evaluation:
                adjusted_evaluations.append(evaluation)
                continue
            adjusted_evaluations.append(
                SearchCandidateEvaluation(
                    action=evaluation.action,
                    root_rank=evaluation.root_rank,
                    ordering_score=evaluation.ordering_score,
                    reason=evaluation.reason,
                    selected=evaluation.selected,
                    line=SearchLine(
                        actions=evaluation.line.actions,
                        reply_actions=evaluation.line.reply_actions,
                        value=(
                            evaluation.line.value - self.config.elimination_pass_live_line_penalty
                        ),
                        explanation=SearchLineExplanation(
                            self_turn_facts=evaluation.line.explanation.self_turn_facts,
                            leaf_facts=evaluation.line.explanation.leaf_facts,
                            leaf_terms=evaluation.line.explanation.leaf_terms,
                            reply=evaluation.line.explanation.reply,
                            root_adjustments=(
                                *evaluation.line.explanation.root_adjustments,
                                SearchValueTerm(
                                    name="elimination_pass_with_live_lines",
                                    value=-self.config.elimination_pass_live_line_penalty,
                                    formula="-elimination_pass_live_line_penalty",
                                    details=(
                                        SearchTraceFact(
                                            "live_non_pass_lines",
                                            str(len(live_non_pass_lines)),
                                        ),
                                        SearchTraceFact(
                                            "elimination_pass_live_line_margin",
                                            (
                                                f"{self.config.elimination_pass_live_line_margin:.2f}"
                                            ),
                                        ),
                                        SearchTraceFact(
                                            "elimination_pass_live_line_penalty",
                                            (
                                                f"{self.config.elimination_pass_live_line_penalty:.2f}"
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                        notes=(
                            *evaluation.line.notes,
                            "root_adjustment=elimination_pass_with_live_lines",
                            f"live_non_pass_lines={len(live_non_pass_lines)}",
                            (
                                "elimination_pass_live_line_margin="
                                f"{self.config.elimination_pass_live_line_margin:.2f}"
                            ),
                            (
                                "elimination_pass_live_line_penalty="
                                f"{self.config.elimination_pass_live_line_penalty:.2f}"
                            ),
                        ),
                    ),
                )
            )
        return tuple(adjusted_evaluations)

    def _is_live_non_pass_line(
        self,
        evaluation: SearchCandidateEvaluation,
        *,
        pass_value: float,
    ) -> bool:
        if isinstance(evaluation.action, (PassAction, LeaveAction)):
            return False
        return evaluation.line.value + self.config.elimination_pass_live_line_margin >= pass_value

    def explain_result(self, result: SearchResult) -> SearchDecisionExplanation:
        return SearchDecisionExplanation(
            chosen_action=result.chosen_action,
            profile_id=self.profile_definition.profile_id,
            config=self.config,
            used_fallback_policy=result.used_fallback_policy,
            candidates=result.candidates,
            evaluations=result.evaluations,
            principal_line=result.principal_line,
            comparison=_build_search_comparison(result.evaluations),
            notes=result.notes,
        )


def _build_search_comparison(
    evaluations: tuple[SearchCandidateEvaluation, ...],
) -> SearchDecisionComparison | None:
    if not evaluations:
        return None
    ordered = tuple(sorted(evaluations, key=lambda item: (-item.line.value, item.root_rank)))
    chosen = ordered[0]
    runner_up = ordered[1] if len(ordered) > 1 else None
    return SearchDecisionComparison(
        chosen_action=chosen.action,
        runner_up_action=None if runner_up is None else runner_up.action,
        chosen_value=chosen.line.value,
        runner_up_value=None if runner_up is None else runner_up.line.value,
        value_margin=(None if runner_up is None else chosen.line.value - runner_up.line.value),
        chosen_reason=chosen.reason,
        runner_up_reason=None if runner_up is None else runner_up.reason,
    )


def build_search_engine(
    *,
    config: SearchConfig,
    profile_definition: BaseProfileDefinition,
    bot_id: str,
) -> SearchEngine:
    return SearchEngine(
        config=config,
        profile_definition=profile_definition,
        fallback_policy=HeuristicBot(
            bot_id=f"{bot_id}_fallback",
            profile_definition=profile_definition,
        ),
    )
