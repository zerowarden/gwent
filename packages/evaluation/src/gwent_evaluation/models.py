from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path

from gwent_engine.ai.arena import BotFamily as BotFamily
from gwent_engine.ai.arena import bot_family
from gwent_engine.ai.arena.models import (
    MatchDecisionKind,
    MatchFailure,
    MatchStepKind,
)
from gwent_engine.ai.arena.models import (
    TerminationReason as TerminationReason,
)
from gwent_engine.ai.baseline import get_base_profile_definition
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION, PlayerObservation
from gwent_engine.core.ids import PLAYER_ONE, PLAYER_TWO, GameId, PlayerId
from gwent_engine.core.state import GameState

from gwent_evaluation.provenance import RepositoryProvenance, RuntimeProvenance

SUPPORTED_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 2


class SpecError(ValueError):
    """An evaluation specification violates its domain contract."""


class SuitePurpose(Enum):
    SMOKE = "smoke"
    OPTIMIZE = "optimize"
    VALIDATION = "validation"
    TEST = "test"
    DIAGNOSTIC = "diagnostic"

    @property
    def requires_clean_checkout(self) -> bool:
        return self in (SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST)


class SchedulingPolicy(Enum):
    BALANCED = "balanced"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    schema_version: int
    agent_id: str
    family: BotFamily
    profile: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION or not self.agent_id.strip():
            raise SpecError("Agent requires a supported schema_version and nonempty agent_id.")
        if self.profile is not None:
            if not bot_family(self.family).accepts_profile:
                raise SpecError(
                    f"family {self.family.value!r} does not support a profile override."
                )
            try:
                profile = get_base_profile_definition(self.profile).profile_id
            except ValueError as error:
                raise SpecError(f"profile {self.profile!r} is not a recognized profile.") from error
            object.__setattr__(self, "profile", profile)


@dataclass(frozen=True, slots=True)
class SuiteSpec:
    schema_version: int
    suite_id: str
    purpose: SuitePurpose
    candidate: AgentSpec
    opponents: tuple[AgentSpec, ...]
    deck_pairs: tuple[tuple[str, str], ...]
    seeds: tuple[int, ...]
    scheduling: SchedulingPolicy
    action_budget: int
    observation_contract_version: int

    def __post_init__(self) -> None:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise SpecError(f"schema_version must be {SUPPORTED_SCHEMA_VERSION}.")
        if not self.suite_id.strip():
            raise SpecError("suite_id must not be empty.")
        if self.observation_contract_version != OBSERVATION_CONTRACT_VERSION:
            raise SpecError("Unsupported observation contract version.")
        if self.scheduling is not SchedulingPolicy.BALANCED:
            raise SpecError("Unsupported scheduling policy.")
        if type(self.purpose) is not SuitePurpose:
            raise SpecError("Unsupported suite purpose.")
        if type(self.action_budget) is not int or self.action_budget <= 0:
            raise SpecError("action_budget must be positive.")
        for name, values in (
            ("opponents", tuple(agent.agent_id for agent in self.opponents)),
            ("deck_pairs", self.deck_pairs),
            ("seeds", self.seeds),
        ):
            if not values:
                raise SpecError(f"{name} must not be empty.")
            if len(set(values)) != len(values):
                raise SpecError(f"{name} must not contain duplicates.")
        if any(type(seed) is not int for seed in self.seeds):
            raise SpecError("seeds must be integers.")
        if any(
            len(pair) != 2 or any(not deck.strip() for deck in pair) for pair in self.deck_pairs
        ):
            raise SpecError("deck_pairs must contain pairs of nonempty deck ids.")


@dataclass(frozen=True, slots=True)
class ScheduledMatch:
    """A fully materialized balanced leg, ready to execute without further input."""

    case_id: str
    candidate_agent: AgentSpec
    opponent_agent: AgentSpec
    candidate_seat: PlayerId
    requested_starting_player: PlayerId
    candidate_deck_id: str
    opponent_deck_id: str
    environment_seed: int
    candidate_policy_seed: int
    opponent_policy_seed: int
    game_id: GameId
    action_budget: int


@dataclass(frozen=True, slots=True)
class DecisionSample:
    """Player-safe decision evidence, safe to use as evaluation/training input.

    The observation is the exact `PlayerObservation` the agent received, so a
    sample can never expose information outside the WS01 boundary.
    """

    index: int
    kind: MatchDecisionKind
    actor: PlayerId
    observation: PlayerObservation
    legal_option_ids: tuple[str, ...]
    chosen_option_id: str | None
    duration_seconds: float
    failure: MatchFailure | None = None


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """Privileged trajectory evidence for replay and diagnosis.

    Retains authoritative snapshots and is never treated as a training
    observation.
    """

    index: int
    kind: MatchStepKind
    action_id: str
    state_before: GameState
    state_after: GameState
    event_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    samples: tuple[DecisionSample, ...]
    trajectory: tuple[TrajectoryStep, ...]
    trace_digest: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceRefs:
    """Run-root-relative paths to persisted evidence."""

    samples_path: str | None = None
    trajectory_path: str | None = None
    samples_digest: str | None = None
    trajectory_digest: str | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Semantic outcome of one scheduled match.

    `candidate_score` is `1.0`/`0.5`/`0.0` only for completed matches and
    `None` for every infrastructure or agent failure.
    """

    schema_version: int
    case_id: str
    termination: TerminationReason
    candidate_agent_id: str
    opponent_agent_id: str
    candidate_seat: PlayerId
    requested_starting_player: PlayerId
    actual_starting_player: PlayerId | None
    winner: PlayerId | None
    candidate_score: float | None
    accepted_transitions: int
    decision_count: int
    pending_choice_occurred: bool
    observation_contract_version: int
    semantic_digest: str
    decision_seconds: float
    execution_seconds: float
    environment_seed: int
    evidence: EvidenceRefs
    execution_identity: str
    final_state_digest: str | None
    failure: MatchFailure | None = None

    def __post_init__(self) -> None:
        if self.schema_version != RECORD_SCHEMA_VERSION:
            raise ValueError("Unsupported result schema_version.")
        for seat in (
            self.candidate_seat,
            self.requested_starting_player,
            self.actual_starting_player,
            self.winner,
        ):
            if seat is not None and seat not in (PLAYER_ONE, PLAYER_TWO):
                raise ValueError("Result contains an unknown player seat.")
        if self.observation_contract_version != OBSERVATION_CONTRACT_VERSION:
            raise ValueError("Unsupported result observation contract.")
        if (
            self.termination
            in (
                TerminationReason.AGENT_ERROR,
                TerminationReason.ENGINE_ERROR,
                TerminationReason.ILLEGAL_ACTION,
            )
            and self.failure is None
        ):
            raise ValueError("Failed result requires failure details.")
        if self.termination is TerminationReason.ACTION_LIMIT and self.failure is not None:
            raise ValueError("Action limit result cannot contain an exception.")
        for count in (self.accepted_transitions, self.decision_count):
            if type(count) is not int or count < 0:
                raise ValueError("Result counts must be nonnegative integers.")
        for duration in (self.decision_seconds, self.execution_seconds):
            if not isfinite(duration) or duration < 0:
                raise ValueError("Result durations must be finite and nonnegative.")
        if self.termination is TerminationReason.COMPLETED:
            expected = candidate_score_for_outcome(
                winner=self.winner,
                candidate_seat=self.candidate_seat,
                completed=True,
            )
            if self.candidate_score != expected or self.failure is not None:
                raise ValueError("Completed result score/failure is inconsistent with its winner.")
            if self.actual_starting_player is None:
                raise ValueError("Completed result requires an actual starting player.")
            if self.final_state_digest is None or self.accepted_transitions < 1:
                raise ValueError("Completed result requires a final state and transitions.")
        elif self.candidate_score is not None or self.winner is not None:
            raise ValueError("Non-completed results cannot contain a normal match score/winner.")


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: str
    family: str
    profile: str | None
    digest: str


@dataclass(frozen=True, slots=True)
class AssetIdentities:
    deck_digests: tuple[tuple[str, str], ...]
    card_data_digest: str
    leader_data_digest: str


@dataclass(frozen=True, slots=True)
class RunManifest:
    schema_version: int
    run_id: str
    suite: SuiteSpec
    seed_derivation_version: int
    case_id_version: int
    planned_case_ids: tuple[str, ...]
    candidate: AgentIdentity
    opponents: tuple[AgentIdentity, ...]
    assets: AssetIdentities
    repository: RepositoryProvenance
    runtime: RuntimeProvenance


@dataclass(frozen=True, slots=True)
class RunExecution:
    run_id: str
    root: Path
    results: tuple[MatchResult, ...]
    executed_case_ids: tuple[str, ...]
    resumed_case_ids: tuple[str, ...]


def candidate_score_for_outcome(
    *,
    winner: PlayerId | None,
    candidate_seat: PlayerId,
    completed: bool,
) -> float | None:
    if not completed:
        return None
    if winner is None:
        return 0.5
    return float(winner == candidate_seat)
