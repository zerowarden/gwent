from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from gwent_engine.ai.arena import BotFamily as BotFamily
from gwent_engine.ai.arena.models import (
    MatchDecisionKind,
    MatchFailure,
    MatchStepKind,
)
from gwent_engine.ai.arena.models import (
    TerminationReason as TerminationReason,
)
from gwent_engine.ai.observations import PlayerObservation
from gwent_engine.core.ids import GameId, PlayerId
from gwent_engine.core.state import GameState

from gwent_evaluation.provenance import RepositoryProvenance, RuntimeProvenance

SUPPORTED_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1


class SuitePurpose(Enum):
    SMOKE = "smoke"
    OPTIMIZE = "optimize"
    VALIDATION = "validation"
    TEST = "test"
    DIAGNOSTIC = "diagnostic"


class SchedulingPolicy(Enum):
    BALANCED = "balanced"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    schema_version: int
    agent_id: str
    family: BotFamily
    profile: str | None = None


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
    chosen_option_id: str
    duration_seconds: float


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


@dataclass(frozen=True, slots=True)
class EvidenceRefs:
    """Run-root-relative paths to persisted evidence."""

    samples_path: str
    trajectory_path: str | None = None


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
    failure: MatchFailure | None = None


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
