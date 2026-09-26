from collections.abc import Mapping
from dataclasses import dataclass

from gwent_engine.ai.arena import (
    MatchExecution,
    MatchStepKind,
    MatchTransition,
)
from gwent_engine.ai.debug import HeuristicDecisionExplanation
from gwent_engine.ai.search import SearchDecisionExplanation
from gwent_engine.core.actions import GameAction
from gwent_engine.core.events import GameEvent
from gwent_engine.core.ids import CardInstanceId, DeckId, GameId, LeaderId, PlayerId
from gwent_engine.core.state import GameState

type BotDecisionExplanation = HeuristicDecisionExplanation | SearchDecisionExplanation


class CliMatchExecutionError(RuntimeError):
    """Raised when a rich review run is requested for a non-completed match."""

    execution: MatchExecution

    def __init__(self, execution: MatchExecution) -> None:
        super().__init__(f"Bot match did not complete: {execution.termination.value}.")
        self.execution = execution


@dataclass(frozen=True, slots=True)
class CliMetadata:
    game_id: GameId
    player_one_id: PlayerId
    player_two_id: PlayerId
    player_one_deck_id: DeckId
    player_two_deck_id: DeckId
    player_one_leader_id: LeaderId
    player_two_leader_id: LeaderId
    player_one_leader_name: str
    player_two_leader_name: str
    rng_name: str
    pending_choice_encountered: bool
    environment_seed: int | None = None
    player_one_actor: str | None = None
    player_two_actor: str | None = None


@dataclass(frozen=True, slots=True)
class CliStep:
    """CLI-owned projection of one engine transition plus diagnostic richness."""

    transition: MatchTransition
    effective_strengths_before: Mapping[CardInstanceId, int]
    effective_strengths_after: Mapping[CardInstanceId, int]
    round_summary_strengths: Mapping[CardInstanceId, int]
    bot_explanation: BotDecisionExplanation | None = None

    @property
    def action(self) -> GameAction:
        return self.transition.action

    @property
    def kind(self) -> MatchStepKind:
        return self.transition.kind

    @property
    def events(self) -> tuple[GameEvent, ...]:
        return self.transition.events

    @property
    def state_before(self) -> GameState:
        return self.transition.state_before

    @property
    def state_after(self) -> GameState:
        return self.transition.state_after

    @property
    def round_summary_state(self) -> GameState | None:
        return self.transition.round_summary_state


@dataclass(frozen=True, slots=True)
class CliRun:
    scenario_name: str
    metadata: CliMetadata
    steps: tuple[CliStep, ...]
    pending_choice_state: GameState | None
    final_state: GameState
    card_names_by_instance_id: Mapping[CardInstanceId, str]
    card_values_by_instance_id: Mapping[CardInstanceId, int]
    card_kinds_by_instance_id: Mapping[CardInstanceId, str]
    card_spy_by_instance_id: Mapping[CardInstanceId, bool]
    card_medic_by_instance_id: Mapping[CardInstanceId, bool]
    card_horn_by_instance_id: Mapping[CardInstanceId, bool]
    card_scorch_by_instance_id: Mapping[CardInstanceId, bool]
    final_strengths_by_instance_id: Mapping[CardInstanceId, int]
