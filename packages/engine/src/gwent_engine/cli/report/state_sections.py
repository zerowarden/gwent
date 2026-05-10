from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.cli.models import CliRun, CliStep
from gwent_engine.cli.presenters import round_ended_event, winner_text
from gwent_engine.cli.report.common import formatted_summary
from gwent_engine.cli.report.format import HTMLFormatter
from gwent_engine.cli.view_formatters import (
    board_card_list_text,
    board_row_label,
    board_total,
    card_list_text,
)
from gwent_engine.core.events import GameEvent, MatchEndedEvent
from gwent_engine.core.ids import CardInstanceId, PlayerId
from gwent_engine.core.state import GameState


@dataclass(slots=True)
class StateSectionsPresenter:
    run: CliRun
    formatter: HTMLFormatter

    def round_summary_context(self, step: CliStep) -> dict[str, object] | None:
        if step.round_summary_state is None and not self.has_match_end_event(step.events):
            return None
        state = step.round_summary_state or step.state_after
        round_end = round_ended_event(step.events)
        strengths = (
            step.round_summary_strengths
            if step.round_summary_state is not None
            else step.effective_strengths_after
        )
        player_one_score, player_two_score = self.board_scores(state, strengths)
        winner = round_end.winner if round_end is not None else state.match_winner
        return {
            "anchor_id": f"round-{state.round_number}-summary",
            "round_number": state.round_number,
            "facts": formatted_summary(
                self.formatter,
                (
                    ("Round", str(state.round_number)),
                    ("Winner", winner_text(winner)),
                    ("p1 Score", str(player_one_score)),
                    ("p2 Score", str(player_two_score)),
                    ("p1 Hand", str(len(state.players[0].hand))),
                    ("p2 Hand", str(len(state.players[1].hand))),
                ),
            ),
            "board_rows": self._board_rows_context(state, strengths),
            "hands": (
                {
                    "label": self.formatter.fmt("p1 Hand"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[0].hand)),
                },
                {
                    "label": self.formatter.fmt("p2 Hand"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[1].hand)),
                },
            ),
            "decks": (
                {
                    "label": self.formatter.fmt("p1 Deck"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[0].deck)),
                },
                {
                    "label": self.formatter.fmt("p2 Deck"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[1].deck)),
                },
            ),
            "discards": (
                {
                    "label": self.formatter.fmt("p1 Discard"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[0].discard)),
                },
                {
                    "label": self.formatter.fmt("p2 Discard"),
                    "cards": self.formatter.fmt(self.card_list_text(state.players[1].discard)),
                },
            ),
        }

    def board_state_context(self, step: CliStep, index: int) -> dict[str, object]:
        player_one_score, player_two_score = self.board_scores(
            step.state_after,
            step.effective_strengths_after,
        )
        return {
            "title": f"Board State at {index}",
            "scores": formatted_summary(
                self.formatter,
                (
                    ("p2 Score", str(player_two_score)),
                    ("p1 Score", str(player_one_score)),
                ),
            ),
            "board_rows": self._board_rows_context(
                step.state_after,
                step.effective_strengths_after,
            ),
        }

    def card_list_text(self, card_ids: tuple[CardInstanceId, ...]) -> str:
        return card_list_text(
            card_ids,
            card_names_by_instance_id=self.run.card_names_by_instance_id,
            card_values_by_instance_id=self.run.card_values_by_instance_id,
        )

    def sorted_card_ids(
        self,
        card_ids: tuple[CardInstanceId, ...],
    ) -> tuple[CardInstanceId, ...]:
        return tuple(
            sorted(
                card_ids,
                key=lambda card_id: (
                    -self.run.card_values_by_instance_id.get(card_id, 0),
                    self.run.card_names_by_instance_id.get(card_id, str(card_id)),
                    str(card_id),
                ),
            )
        )

    def board_scores(
        self,
        state: GameState,
        strengths_by_instance_id: Mapping[CardInstanceId, int],
    ) -> tuple[int, int]:
        return (
            board_total(strengths_by_instance_id, state.players[0].rows.all_cards()),
            board_total(strengths_by_instance_id, state.players[1].rows.all_cards()),
        )

    @staticmethod
    def has_match_end_event(events: tuple[GameEvent, ...]) -> bool:
        return any(isinstance(event, MatchEndedEvent) for event in events)

    def _board_rows_context(
        self,
        state: GameState,
        strengths_by_instance_id: Mapping[CardInstanceId, int],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "label": self.formatter.fmt(f"{label} [{row_score}]"),
                "cards": self.formatter.fmt(cards),
                "horn_active": horn_active,
            }
            for label, row_score, cards, horn_active in self.round_board_rows(
                state,
                strengths_by_instance_id,
            )
        )

    def round_board_rows(
        self,
        state: GameState,
        strengths_by_instance_id: Mapping[CardInstanceId, int],
    ) -> tuple[tuple[str, int, str, bool], ...]:
        player_one, player_two = state.players
        return (
            (
                board_row_label("p2 Siege", active=bool(state.weather.siege)),
                board_total(strengths_by_instance_id, player_two.rows.siege),
                self._board_card_list_text(player_two.rows.siege, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p2"), "siege"),
            ),
            (
                board_row_label("p2 Ranged", active=bool(state.weather.ranged)),
                board_total(strengths_by_instance_id, player_two.rows.ranged),
                self._board_card_list_text(player_two.rows.ranged, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p2"), "ranged"),
            ),
            (
                board_row_label("p2 Close", active=bool(state.weather.close)),
                board_total(strengths_by_instance_id, player_two.rows.close),
                self._board_card_list_text(player_two.rows.close, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p2"), "close"),
            ),
            (
                board_row_label("p1 Close", active=bool(state.weather.close)),
                board_total(strengths_by_instance_id, player_one.rows.close),
                self._board_card_list_text(player_one.rows.close, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p1"), "close"),
            ),
            (
                board_row_label("p1 Ranged", active=bool(state.weather.ranged)),
                board_total(strengths_by_instance_id, player_one.rows.ranged),
                self._board_card_list_text(player_one.rows.ranged, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p1"), "ranged"),
            ),
            (
                board_row_label("p1 Siege", active=bool(state.weather.siege)),
                board_total(strengths_by_instance_id, player_one.rows.siege),
                self._board_card_list_text(player_one.rows.siege, strengths_by_instance_id),
                self._row_horn_active(state, PlayerId("p1"), "siege"),
            ),
        )

    def _row_horn_active(
        self,
        state: GameState,
        battlefield_side: PlayerId,
        row_name: str,
    ) -> bool:
        player = state.player(battlefield_side)
        match row_name:
            case "close":
                row = player.rows.close
            case "ranged":
                row = player.rows.ranged
            case "siege":
                row = player.rows.siege
            case _:
                return False
        if player.leader.horn_row is not None and player.leader.horn_row.value == row_name:
            return True
        return any(self.run.card_horn_by_instance_id.get(card_id, False) for card_id in row)

    def _board_card_list_text(
        self,
        card_ids: tuple[CardInstanceId, ...],
        strengths_by_instance_id: Mapping[CardInstanceId, int],
    ) -> str:
        return board_card_list_text(
            card_ids,
            card_names_by_instance_id=self.run.card_names_by_instance_id,
            strengths_by_instance_id=strengths_by_instance_id,
        )
