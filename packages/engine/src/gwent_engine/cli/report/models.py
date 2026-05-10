from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from gwent_engine.ai.search import SearchDecisionExplanation
from gwent_engine.cli.models import CliRun, CliStep
from gwent_engine.cli.presenters import (
    event_type_name,
    round_ended_event,
    summarize_action,
    summarize_event,
)
from gwent_engine.cli.report.common import (
    action_player_id,
    formatted_summary,
    winner_status_text,
)
from gwent_engine.cli.report.decision_context import (
    DecisionContextPresenter,
    best_non_pass_breakdown,
    candidate_diagnosis_title,
    decision_comparison_title,
    override_reason,
    pass_debug_details,
    pass_score_delta,
    ranked_actions_title,
)
from gwent_engine.cli.report.format import HTMLFormatter, counter_text, split_key_value
from gwent_engine.cli.report.score_derivation import ScoreDerivationPresenter
from gwent_engine.cli.report.search_trace import SearchTracePresenter
from gwent_engine.cli.report.state_sections import StateSectionsPresenter
from gwent_engine.core import Phase
from gwent_engine.core.actions import (
    GameAction,
    LeaveAction,
    PassAction,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.events import FactionPassiveTriggeredEvent, GameEvent, RoundEndedEvent
from gwent_engine.core.ids import PlayerId


def build_report_context(
    run: CliRun,
    *,
    player_one_bot_spec: str,
    player_two_bot_spec: str,
    seed: int,
) -> dict[str, object]:
    return MatchReportBuilder(
        run=run,
        player_one_bot_spec=player_one_bot_spec,
        player_two_bot_spec=player_two_bot_spec,
        seed=seed,
    ).build_context()


@dataclass(slots=True)
class MatchReportBuilder:
    run: CliRun
    player_one_bot_spec: str
    player_two_bot_spec: str
    seed: int
    formatter: HTMLFormatter = field(init=False)
    score_derivation: ScoreDerivationPresenter = field(init=False)
    search_trace: SearchTracePresenter = field(init=False)
    state_sections: StateSectionsPresenter = field(init=False)
    decision_context: DecisionContextPresenter = field(init=False)

    def __post_init__(self) -> None:
        self.formatter = HTMLFormatter(self.run)
        self.score_derivation = ScoreDerivationPresenter(self.formatter)
        self.search_trace = SearchTracePresenter(self.formatter, self._action_text)
        self.state_sections = StateSectionsPresenter(self.run, self.formatter)
        self.decision_context = DecisionContextPresenter(
            self.formatter,
            self._action_text,
            self.score_derivation,
            self.search_trace,
        )

    def build_context(self) -> dict[str, object]:
        final_state = self.run.final_state
        action_counts = Counter(action_player_id(step.action) for step in self.run.steps)
        override_counts = Counter(
            reason
            for reason in (override_reason(step.bot_explanation) for step in self.run.steps)
            if reason is not None
        )
        pass_action_count = sum(isinstance(step.action, PassAction) for step in self.run.steps)
        leave_action_count = sum(isinstance(step.action, LeaveAction) for step in self.run.steps)
        structured_explanation_count = sum(
            step.bot_explanation is not None for step in self.run.steps
        )
        return {
            "metadata": (
                ("Scenario", self.run.scenario_name),
                ("Seed", str(self.seed)),
                ("Bot 1", self.formatter.fmt(self.player_one_bot_spec)),
                ("Bot 2", self.formatter.fmt(self.player_two_bot_spec)),
                ("Player 1 Deck", self.formatter.fmt(str(self.run.metadata.player_one_deck_id))),
                ("Player 2 Deck", self.formatter.fmt(str(self.run.metadata.player_two_deck_id))),
                ("Player 1 Leader", self.formatter.fmt(self.run.metadata.player_one_leader_name)),
                ("Player 2 Leader", self.formatter.fmt(self.run.metadata.player_two_leader_name)),
                ("Game Id", self.formatter.fmt(str(self.run.metadata.game_id))),
                ("Trace Steps", str(len(self.run.steps))),
            ),
            "steps": self._step_contexts(),
            "toc_rounds": tuple(self._toc_rounds()),
            "summary_overview": self._formatted_summary(
                (
                    ("Seed", str(self.seed)),
                    (
                        "Winner",
                        winner_status_text(
                            final_state.match_winner,
                            final_state.status.value,
                        ),
                    ),
                    ("Round", str(final_state.round_number)),
                )
            ),
            "summary_player_rows": (
                {
                    "metric": self.formatter.fmt("Round Wins"),
                    "p1": str(final_state.players[0].round_wins),
                    "p2": str(final_state.players[1].round_wins),
                },
                {
                    "metric": self.formatter.fmt("Hand"),
                    "p1": str(len(final_state.players[0].hand)),
                    "p2": str(len(final_state.players[1].hand)),
                },
                {
                    "metric": self.formatter.fmt("Deck"),
                    "p1": str(len(final_state.players[0].deck)),
                    "p2": str(len(final_state.players[1].deck)),
                },
                {
                    "metric": self.formatter.fmt("Actions"),
                    "p1": str(action_counts.get(PlayerId("p1"), 0)),
                    "p2": str(action_counts.get(PlayerId("p2"), 0)),
                },
            ),
            "additional_stats": self._formatted_summary(
                (
                    (
                        "Overrides",
                        counter_text("Overrides", override_counts).removeprefix("Overrides: "),
                    ),
                    (
                        "Pass Actions",
                        str(pass_action_count),
                    ),
                    ("Leave Actions", str(leave_action_count)),
                    ("Structured Explanations", str(structured_explanation_count)),
                )
            ),
            "timeline": tuple(
                self._timeline_entry(step, index + 1) for index, step in enumerate(self.run.steps)
            ),
        }

    def _step_contexts(self) -> tuple[dict[str, object], ...]:
        contexts: list[dict[str, object]] = []
        previous_in_round: int | None = None
        for index, step in enumerate(self.run.steps, start=1):
            round_start: dict[str, object] | None = None
            current_round = step.state_before.round_number
            if step.state_before.phase == Phase.IN_ROUND and current_round != previous_in_round:
                round_start = {
                    "label": self.formatter.fmt(f"Round {current_round} Start"),
                }
                previous_in_round = current_round
            contexts.append(self._step_context(step, index, round_start=round_start))
        return tuple(contexts)

    def _step_context(
        self,
        step: CliStep,
        index: int,
        *,
        round_start: dict[str, object] | None,
    ) -> dict[str, object]:
        show_board_state = not isinstance(
            step.action,
            StartGameAction | ResolveMulligansAction,
        ) and not self.state_sections.has_match_end_event(step.events)
        if isinstance(step.action, PassAction) and step.round_summary_state is not None:
            show_board_state = False
        return {
            "index": index,
            "round_start": round_start,
            "action_type": type(step.action).__name__,
            "actor": self._actor_context(step, index),
            "action": self.formatter.fmt(self._step_action_text(step.action)),
            "events": tuple(self._event_context(event) for event in step.events),
            "debug_entries": tuple(
                {
                    "key": self.formatter.fmt(key),
                    "value": self.formatter.fmt(value),
                }
                for key, value in self._debug_entries(step)
            ),
            "ranked_actions_title": self.formatter.fmt(ranked_actions_title(step.bot_explanation)),
            "baseline_ranked_actions": self.decision_context.ranked_actions(step, index),
            "decision_comparison_title": self.formatter.fmt(
                decision_comparison_title(step.bot_explanation)
            ),
            "decision_comparison": self.decision_context.comparison(step),
            "search_line_traces": self._search_line_traces_context(step),
            "candidate_diagnosis_title": self.formatter.fmt(
                candidate_diagnosis_title(step.bot_explanation)
            ),
            "candidate_diagnosis": self.decision_context.candidate_diagnosis(step),
            "mulligan_review": self._mulligan_review_context(step),
            "board_state": (
                self.state_sections.board_state_context(step, index) if show_board_state else None
            ),
            "round_summary": self.state_sections.round_summary_context(step),
        }

    def _actor_context(self, step: CliStep, index: int) -> dict[str, object] | None:
        actor = action_player_id(step.action)
        if actor is None:
            return None
        hand = self.state_sections.sorted_card_ids(step.state_before.player(actor).hand)
        return {
            "label": self.formatter.fmt(str(actor)),
            "css_class": "p1" if actor == PlayerId("p1") else "p2",
            "popover_id": f"hand-popover-step-{index}-{actor}",
            "title": self.formatter.fmt(f"{actor} hand before step {index}"),
            "cards": self.formatter.fmt(self.state_sections.card_list_text(hand)),
        }

    def _mulligan_review_context(self, step: CliStep) -> dict[str, object] | None:
        if not isinstance(step.action, ResolveMulligansAction):
            return None
        selections_by_player = {
            selection.player_id: selection.cards_to_replace for selection in step.action.selections
        }
        players: list[dict[str, object]] = []
        for player in step.state_before.players:
            before_hand = step.state_before.player(player.player_id).hand
            after_hand = step.state_after.player(player.player_id).hand
            selected_cards = selections_by_player.get(player.player_id, ())
            kept_cards = tuple(card_id for card_id in before_hand if card_id not in selected_cards)
            replacement_cards = tuple(
                card_id for card_id in after_hand if card_id not in kept_cards
            )
            players.append(
                {
                    "title": self.formatter.fmt(str(player.player_id)),
                    "before_hand": self.formatter.fmt(
                        self.state_sections.card_list_text(before_hand)
                    ),
                    "selected": self.formatter.fmt(
                        self.state_sections.card_list_text(selected_cards)
                    ),
                    "replacement": self.formatter.fmt(
                        self.state_sections.card_list_text(replacement_cards)
                    ),
                    "after_hand": self.formatter.fmt(
                        self.state_sections.card_list_text(after_hand)
                    ),
                }
            )
        return {"players": tuple(players)}

    def _action_text(self, action: GameAction) -> str:
        return summarize_action(
            action,
            card_names_by_instance_id=self.run.card_names_by_instance_id,
            card_values_by_instance_id=self.run.card_values_by_instance_id,
        )

    def _step_action_text(self, action: GameAction) -> str:
        text = self._action_text(action)
        actor = action_player_id(action)
        if actor is None:
            return text
        prefix = f"{actor} "
        return text[len(prefix) :] if text.startswith(prefix) else text

    def _event_text(self, event: GameEvent) -> str:
        return summarize_event(
            event,
            card_names_by_instance_id=self.run.card_names_by_instance_id,
            card_values_by_instance_id=self.run.card_values_by_instance_id,
        )

    def _debug_lines(self, step: CliStep) -> tuple[str, ...]:
        if isinstance(step.action, ResolveMulligansAction):
            return ("joint_mulligan_resolution=yes",)
        explanation = step.bot_explanation
        if explanation is None:
            return self._fallback_debug_lines(step)
        if isinstance(explanation, SearchDecisionExplanation):
            lines = [
                f"actual={self._action_text(step.action)}",
                f"profile={explanation.profile_id}",
                "search_mode=public_information",
                f"fallback_policy={'yes' if explanation.used_fallback_policy else 'no'}",
                f"root_candidates={len(explanation.candidates)}",
                f"searched_lines={len(explanation.evaluations)}",
            ]
            if explanation.chosen_action != step.action:
                lines.append(f"model_choice={self._action_text(explanation.chosen_action)}")
            if explanation.principal_line is not None:
                lines.extend(
                    (
                        f"principal_value={explanation.principal_line.value:.2f}",
                        f"principal_actions={len(explanation.principal_line.actions)}",
                        f"principal_reply_actions={len(explanation.principal_line.reply_actions)}",
                    )
                )
            if explanation.notes:
                lines.append(f"search_notes={'; '.join(explanation.notes)}")
            return tuple(lines)
        lines = [
            f"actual={self._action_text(step.action)}",
            f"profile={explanation.profile.profile_id}",
            f"scorch_policy={explanation.profile.policy_names.scorch_policy}",
            f"leader_policy={explanation.profile.policy_names.leader_policy}",
            f"tempo={explanation.context.tempo.value}",
            f"pressure={explanation.context.pressure.value}",
            f"score_gap={explanation.assessment.score_gap}",
            f"card_advantage={explanation.assessment.card_advantage}",
            f"viewer_hand={explanation.assessment.viewer.hand_count}",
            f"opponent_hand={explanation.assessment.opponent.hand_count}",
        ]
        if explanation.chosen_action != step.action:
            lines.append(f"model_choice={self._action_text(explanation.chosen_action)}")
        if explanation.override is not None:
            lines.append(f"override={explanation.override.reason}")
        if isinstance(step.action, PassAction):
            pass_details = pass_debug_details(explanation)
            best_non_pass = best_non_pass_breakdown(explanation)
            pass_source = (
                explanation.override.reason if explanation.override is not None else "ranked_choice"
            )
            lines.extend(
                (
                    f"pass_margin_floor={pass_details['margin_floor']}",
                    f"pass_tempo_per_card={pass_details['tempo_per_card']}",
                    f"pass_estimated_opponent_response={pass_details['estimated_opponent_response']}",
                    f"pass_required_lead={pass_details['required_lead']}",
                    f"pass_projection={pass_details['projection']}",
                    f"pass_source={pass_source}",
                )
            )
            if best_non_pass is not None:
                lines.extend(
                    (
                        f"best_non_pass={self._action_text(best_non_pass.action)}",
                        f"best_non_pass_score={best_non_pass.total:.2f}",
                        f"pass_score_delta={pass_score_delta(explanation, best_non_pass):.2f}",
                    )
                )
        return tuple(lines)

    def _debug_entries(self, step: CliStep) -> tuple[tuple[str, str], ...]:
        return tuple(split_key_value(line) for line in self._debug_lines(step))

    def _search_line_traces_context(
        self,
        step: CliStep,
    ) -> tuple[dict[str, object], ...]:
        explanation = step.bot_explanation
        if not isinstance(explanation, SearchDecisionExplanation):
            return ()
        return self.search_trace.line_traces_context(explanation)

    def _event_context(self, event: GameEvent) -> dict[str, object]:
        match event:
            case FactionPassiveTriggeredEvent(player_id=player_id, passive_kind=passive_kind):
                summary = (
                    f"{self.formatter.fmt(str(player_id))} triggers "
                    f"<em>{self.formatter.fmt(passive_kind.value)}</em>"
                )
            case _:
                summary = self.formatter.fmt(self._event_text(event))
        return {
            "type": event_type_name(event),
            "summary": summary,
        }

    def _fallback_debug_lines(self, step: CliStep) -> tuple[str, ...]:
        player_id_value = action_player_id(step.action)
        if player_id_value is None:
            return ("actor=system",)
        actor = (
            self.run.metadata.player_one_actor
            if player_id_value == PlayerId("p1")
            else self.run.metadata.player_two_actor
        )
        if actor == "RandomBot":
            return (
                "actor=RandomBot",
                "policy=seeded_random",
                "avoid_leave=yes",
                "avoid_pass_when_other_actions_exist=yes",
            )
        if actor == "GreedyBot":
            return (
                "actor=GreedyBot",
                "policy=immediate_gain",
                "tie_break=deterministic",
            )
        return (f"actor={actor or 'unknown'}", "debug_trace=unavailable")

    def _timeline_entry(self, step: CliStep, index: int) -> dict[str, object]:
        timeline_state = step.round_summary_state or step.state_after
        timeline_strengths = (
            step.round_summary_strengths
            if step.round_summary_state
            else step.effective_strengths_after
        )
        round_end = round_ended_event(step.events)
        p1_score, p2_score = self.state_sections.board_scores(
            timeline_state,
            timeline_strengths,
        )
        actor = action_player_id(step.action)
        action_text = self._action_text(step.action)
        lead = "p1 ahead" if p1_score > p2_score else "p2 ahead" if p2_score > p1_score else "even"
        return {
            "index": index,
            "actor": self.formatter.fmt(str(actor) if actor is not None else "system"),
            "action": self.formatter.fmt(action_text),
            "p1_score": str(p1_score),
            "p2_score": str(p2_score),
            "lead": self.formatter.fmt(lead),
            "round_ended": round_end is not None,
            "round_end_summary": self._round_end_summary(round_end),
        }

    def _toc_rounds(self) -> tuple[dict[str, object], ...]:
        seen_rounds: set[int] = set()
        items: list[dict[str, object]] = []
        for step in self.run.steps:
            if step.round_summary_state is not None:
                round_number = step.round_summary_state.round_number
            elif self.state_sections.has_match_end_event(step.events):
                round_number = step.state_after.round_number
            else:
                continue
            if round_number in seen_rounds:
                continue
            seen_rounds.add(round_number)
            items.append(
                {
                    "label": self.formatter.fmt(f"Round {round_number}"),
                    "anchor": f"round-{round_number}-summary",
                }
            )
        return tuple(items)

    def _round_end_summary(self, round_end: RoundEndedEvent | None) -> str | None:
        if round_end is None:
            return None
        winner = round_end.winner
        scores = dict(round_end.player_scores)
        p1_score = scores.get(PlayerId("p1"), 0)
        p2_score = scores.get(PlayerId("p2"), 0)
        match winner:
            case None:
                return self.formatter.fmt(f"draw: p1 {p1_score} - p2 {p2_score}")
            case _:
                loser = PlayerId("p2") if winner == PlayerId("p1") else PlayerId("p1")
                return self.formatter.fmt(
                    f"winner={winner}, loser={loser}, points: p1 {p1_score} - p2 {p2_score}"
                )

    def _formatted_summary(
        self,
        items: tuple[tuple[str, str], ...],
    ) -> tuple[dict[str, object], ...]:
        return formatted_summary(self.formatter, items)
