from __future__ import annotations

from dataclasses import dataclass, field, replace

from gwent_engine.ai.actions import enumerate_legal_actions
from gwent_engine.ai.baseline import BaseProfileDefinition
from gwent_engine.ai.observations import build_player_observation
from gwent_engine.ai.policy import SearchConfig
from gwent_engine.ai.search.candidate_generation import generate_search_candidates
from gwent_engine.ai.search.depth_policy import should_search_opponent_reply
from gwent_engine.ai.search.evaluator import evaluate_search_state
from gwent_engine.ai.search.move_ordering import order_search_candidates
from gwent_engine.ai.search.opponent_model import (
    OpponentReplyCandidate,
    generate_opponent_reply_candidates,
)
from gwent_engine.ai.search.types import (
    SearchCandidate,
    SearchLine,
    SearchLineExplanation,
    SearchReplyExplanation,
    SearchTraceFact,
)
from gwent_engine.cards import CardRegistry
from gwent_engine.core.actions import GameAction
from gwent_engine.core.ids import PlayerId
from gwent_engine.core.randomness import SeededRandom
from gwent_engine.core.reducer import apply_action_with_intermediate_state
from gwent_engine.core.state import GameState
from gwent_engine.leaders import LeaderRegistry
from gwent_engine.rules.players import opponent_player_id_from_state


@dataclass(slots=True)
class TurnSearchResolver:
    """Resolve a full same-player turn from a root action.

    The resolver operates on the already-redacted Phase 3 search state. It
    searches the acting player's fully resolved turn, including same-player
    pending choices, and stops once control passes away or the round/match
    materially changes.
    """

    viewer_player_id: PlayerId
    profile_definition: BaseProfileDefinition
    config: SearchConfig
    card_registry: CardRegistry
    leader_registry: LeaderRegistry | None = None
    rng: SeededRandom = field(default_factory=lambda: SeededRandom(0))

    @dataclass(frozen=True, slots=True)
    class ResolvedTurn:
        line: SearchLine
        end_state: GameState

    def resolve_root_action_with_reply(
        self,
        state: GameState,
        root_action: GameAction,
    ) -> SearchLine:
        viewer_turn = self._resolve_turn(state, (root_action,))
        reply_decision = should_search_opponent_reply(
            viewer_turn.end_state,
            viewer_player_id=self.viewer_player_id,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        if not reply_decision.enabled:
            return self._with_reply_explanation(
                viewer_turn.line,
                SearchReplyExplanation(
                    kind="none",
                    reason=reply_decision.reason,
                    notes=(SearchTraceFact("reply_search", reply_decision.reason),),
                ),
                notes=(f"reply_search={reply_decision.reason}",),
            )
        reply_candidates = generate_opponent_reply_candidates(
            viewer_turn.end_state,
            viewer_player_id=self.viewer_player_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        if not reply_candidates:
            return self._with_reply_explanation(
                viewer_turn.line,
                SearchReplyExplanation(
                    kind="none",
                    reason=reply_decision.reason,
                    notes=(
                        SearchTraceFact("reply_search", reply_decision.reason),
                        SearchTraceFact("reply_candidates", "empty"),
                    ),
                ),
                notes=(
                    f"reply_search={reply_decision.reason}",
                    "reply_candidates=empty",
                ),
            )
        opponent_id = opponent_player_id_from_state(
            viewer_turn.end_state,
            self.viewer_player_id,
        )
        opponent_resolver = TurnSearchResolver(
            viewer_player_id=opponent_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        worst_reply: SearchLine | None = None
        for candidate in reply_candidates:
            reply_line = self._evaluate_reply_candidate(
                viewer_turn,
                candidate,
                opponent_resolver=opponent_resolver,
            )
            if worst_reply is None or reply_line.value < worst_reply.value:
                worst_reply = reply_line
        assert worst_reply is not None
        return worst_reply

    def _resolve_turn(
        self,
        state: GameState,
        root_actions: tuple[GameAction, ...],
    ) -> ResolvedTurn:
        next_state, _, _ = apply_action_with_intermediate_state(
            state,
            root_actions[0],
            rng=self.rng,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        return self._resolve_after_action(next_state, root_actions)

    def _resolve_after_action(
        self,
        state: GameState,
        actions: tuple[GameAction, ...],
    ) -> ResolvedTurn:
        if (
            state.pending_choice is not None
            and state.pending_choice.player_id == self.viewer_player_id
        ):
            return self._resolve_same_player_pending_choice(state, actions)
        evaluation = evaluate_search_state(
            state,
            viewer_player_id=self.viewer_player_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        return self.ResolvedTurn(
            line=SearchLine(
                actions=actions,
                value=evaluation.value,
                explanation=SearchLineExplanation(
                    leaf_facts=evaluation.facts,
                    leaf_terms=evaluation.terms,
                ),
                notes=evaluation.notes,
            ),
            end_state=state,
        )

    def _resolve_same_player_pending_choice(
        self,
        state: GameState,
        actions: tuple[GameAction, ...],
    ) -> ResolvedTurn:
        legal_actions = enumerate_legal_actions(
            state,
            player_id=self.viewer_player_id,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
            rng=self.rng,
        )
        observation = build_player_observation(
            state,
            self.viewer_player_id,
            self.leader_registry,
        )
        ordered_candidates = order_search_candidates(
            generate_search_candidates(
                observation,
                legal_actions,
                config=self.config,
                card_registry=self.card_registry,
                leader_registry=self.leader_registry,
            )
        )
        best_line: TurnSearchResolver.ResolvedTurn | None = None
        for candidate in ordered_candidates:
            line = self._resolve_pending_choice_candidate(
                state,
                candidate,
                actions,
            )
            if best_line is None or line.line.value > best_line.line.value:
                best_line = line
        if best_line is not None:
            return best_line
        evaluation = evaluate_search_state(
            state,
            viewer_player_id=self.viewer_player_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        return self.ResolvedTurn(
            line=SearchLine(
                actions=actions,
                value=evaluation.value,
                explanation=SearchLineExplanation(
                    self_turn_facts=(SearchTraceFact("pending_choice_candidates", "empty"),),
                    leaf_facts=evaluation.facts,
                    leaf_terms=evaluation.terms,
                ),
                notes=(*evaluation.notes, "pending_choice_candidates=empty"),
            ),
            end_state=state,
        )

    def _resolve_pending_choice_candidate(
        self,
        state: GameState,
        candidate: SearchCandidate,
        actions: tuple[GameAction, ...],
    ) -> ResolvedTurn:
        next_state, _, _ = apply_action_with_intermediate_state(
            state,
            candidate.action,
            rng=self.rng,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        next_line = self._resolve_after_action(next_state, (*actions, candidate.action))
        return self.ResolvedTurn(
            line=SearchLine(
                actions=next_line.line.actions,
                reply_actions=next_line.line.reply_actions,
                value=next_line.line.value,
                explanation=replace(
                    next_line.line.explanation,
                    self_turn_facts=(
                        SearchTraceFact("pending_choice_order_hint", candidate.reason),
                        *next_line.line.explanation.self_turn_facts,
                    ),
                ),
                notes=(f"pending_choice_order_hint={candidate.reason}", *next_line.line.notes),
            ),
            end_state=next_line.end_state,
        )

    def _evaluate_reply_candidate(
        self,
        viewer_turn: ResolvedTurn,
        candidate: OpponentReplyCandidate,
        *,
        opponent_resolver: TurnSearchResolver,
    ) -> SearchLine:
        reply_action = candidate.action
        reply_reason = candidate.reason
        if reply_action is None:
            reply_explanation = candidate.explanation or SearchReplyExplanation(
                kind="inferred_hidden",
                reason=reply_reason,
                value_adjustment=-candidate.inferred_penalty,
            )
            return self._with_reply_explanation(
                viewer_turn.line,
                reply_explanation,
                value=viewer_turn.line.value - candidate.inferred_penalty,
                notes=(
                    f"reply_search={reply_reason}",
                    f"reply_penalty={candidate.inferred_penalty:.2f}",
                ),
            )
        reply_turn = opponent_resolver._resolve_turn(viewer_turn.end_state, (reply_action,))
        evaluation = evaluate_search_state(
            reply_turn.end_state,
            viewer_player_id=self.viewer_player_id,
            profile_definition=self.profile_definition,
            config=self.config,
            card_registry=self.card_registry,
            leader_registry=self.leader_registry,
        )
        reply_explanation = candidate.explanation or SearchReplyExplanation(
            kind="exact_public",
            reason=reply_reason,
        )
        return SearchLine(
            actions=viewer_turn.line.actions,
            reply_actions=reply_turn.line.actions,
            value=evaluation.value,
            explanation=SearchLineExplanation(
                self_turn_facts=viewer_turn.line.explanation.self_turn_facts,
                leaf_facts=evaluation.facts,
                leaf_terms=evaluation.terms,
                reply=SearchReplyExplanation(
                    kind=reply_explanation.kind,
                    reason=reply_explanation.reason,
                    actions=reply_turn.line.actions,
                    value_adjustment=reply_explanation.value_adjustment,
                    components=reply_explanation.components,
                    notes=(
                        *reply_explanation.notes,
                        *reply_turn.line.explanation.self_turn_facts,
                    ),
                ),
                root_adjustments=viewer_turn.line.explanation.root_adjustments,
            ),
            notes=(
                *viewer_turn.line.notes,
                f"reply_search={reply_reason}",
                *reply_turn.line.notes,
            ),
        )

    def _with_reply_explanation(
        self,
        line: SearchLine,
        reply_explanation: SearchReplyExplanation,
        *,
        value: float | None = None,
        notes: tuple[str, ...] = (),
    ) -> SearchLine:
        return SearchLine(
            actions=line.actions,
            reply_actions=reply_explanation.actions,
            value=line.value if value is None else value,
            explanation=replace(line.explanation, reply=reply_explanation),
            notes=(*line.notes, *notes),
        )
