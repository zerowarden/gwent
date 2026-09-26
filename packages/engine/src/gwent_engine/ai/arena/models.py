from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.core.actions import (
    GameAction,
    MulliganSelection,
    ResolveMulligansAction,
    StartGameAction,
)
from gwent_engine.core.events import GameEvent, MatchEndedEvent, RoundEndedEvent
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.state import GameState


class TerminationReason(StrEnum):
    """Why a bot match execution stopped.

    Only `COMPLETED` means the engine reached `MATCH_ENDED`; every other reason
    is an infrastructure or contract failure with no score.
    """

    COMPLETED = "completed"
    ACTION_LIMIT = "action_limit"
    ILLEGAL_ACTION = "illegal_action"
    AGENT_ERROR = "agent_error"
    ENGINE_ERROR = "engine_error"


class MatchFailureStage(StrEnum):
    START = "start"
    OBSERVE = "observe"
    ENUMERATE_ACTIONS = "enumerate_actions"
    CHOOSE_MULLIGAN = "choose_mulligan"
    CHOOSE_ACTION = "choose_action"
    CHOOSE_PENDING_CHOICE = "choose_pending_choice"
    REDUCE = "reduce"
    RECORD = "record"


@dataclass(frozen=True, slots=True)
class MatchFailure:
    stage: MatchFailureStage
    actor: PlayerId | None
    exception_type: str
    message: str


class MatchStepKind(StrEnum):
    """What a single match transition represents, independent of rendering."""

    SETUP = "setup"
    MULLIGAN = "mulligan"
    ACTION = "action"
    ROUND_ENDED = "round_ended"
    MATCH_ENDED = "match_ended"


@dataclass(frozen=True, slots=True)
class MatchTransition:
    """One accepted reducer transition, including the start-game setup step."""

    action: GameAction
    events: tuple[GameEvent, ...]
    state_before: GameState
    state_after: GameState
    intermediate_state: GameState

    @property
    def kind(self) -> MatchStepKind:
        if any(isinstance(event, MatchEndedEvent) for event in self.events):
            return MatchStepKind.MATCH_ENDED
        if any(isinstance(event, RoundEndedEvent) for event in self.events):
            return MatchStepKind.ROUND_ENDED
        if isinstance(self.action, StartGameAction):
            return MatchStepKind.SETUP
        if isinstance(self.action, ResolveMulligansAction):
            return MatchStepKind.MULLIGAN
        return MatchStepKind.ACTION

    @property
    def round_summary_state(self) -> GameState | None:
        if self.kind not in {MatchStepKind.ROUND_ENDED, MatchStepKind.MATCH_ENDED}:
            return None
        return self.intermediate_state


class MatchDecisionKind(StrEnum):
    MULLIGAN = "mulligan"
    ACTION = "action"
    PENDING_CHOICE = "pending_choice"


@dataclass(frozen=True, slots=True)
class MulliganDecision:
    actor: PlayerId
    observation: PlayerObservation
    legal_selections: tuple[MulliganSelection, ...]
    selection: MulliganSelection
    duration_seconds: float

    @property
    def kind(self) -> MatchDecisionKind:
        return MatchDecisionKind.MULLIGAN


@dataclass(frozen=True, slots=True)
class TurnDecision:
    kind: MatchDecisionKind
    actor: PlayerId
    observation: PlayerObservation
    legal_actions: tuple[GameAction, ...]
    action: GameAction
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class FailedDecisionAttempt:
    kind: MatchDecisionKind
    actor: PlayerId
    observation: PlayerObservation
    legal_option_ids: tuple[str, ...]
    chosen_option_id: str | None
    duration_seconds: float
    failure: MatchFailure


type MatchDecision = MulliganDecision | TurnDecision | FailedDecisionAttempt


class MatchRecorder(Protocol):
    """Behaviour-neutral observer of the authoritative match loop.

    Recorders only observe; they must never influence agent choices or RNG
    consumption. `record_decision` reports one agent decision (mulligans produce
    two per joint transition) and `record_transition` reports one accepted
    reducer transition, including the start-game setup step.
    """

    def record_decision(self, decision: MatchDecision) -> None: ...

    def record_transition(self, transition: MatchTransition) -> None: ...


@dataclass(frozen=True, slots=True)
class MatchExecution:
    game_id: GameId
    final_state: GameState | None
    termination: TerminationReason
    accepted_transitions: int
    decision_count: int
    pending_choice_occurred: bool
    environment_seed: int | None = None
    failure: MatchFailure | None = None

    @property
    def completed(self) -> bool:
        return self.termination is TerminationReason.COMPLETED

    @property
    def match_winner(self) -> PlayerId | None:
        if not self.completed or self.final_state is None:
            return None
        return self.final_state.match_winner
