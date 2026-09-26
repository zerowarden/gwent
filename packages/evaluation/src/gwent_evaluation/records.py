"""Strict conversion between experiment records and their persisted form."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from gwent_engine.ai.arena.models import (
    MatchFailure,
    MatchFailureStage,
    MatchStepKind,
    TerminationReason,
)
from gwent_engine.ai.observations import player_observation_to_dict
from gwent_engine.cards import CardRegistry
from gwent_engine.core.errors import GwentEngineError
from gwent_engine.core.ids import GameId, PlayerId, player_id
from gwent_engine.core.state import GameState
from gwent_engine.serialize import game_state_from_dict, game_state_to_dict
from gwent_shared.extract import (
    expect_int,
    expect_mapping,
    expect_optional_str,
    expect_str,
    optional_bool_field,
    optional_constructor_field,
    optional_str_field,
    require_bool_field,
    require_constructor_field,
    require_enum_field,
    require_field,
    require_int_field,
    require_pair_sequence_field,
    require_sequence_field,
    require_str_field,
    require_str_sequence_field,
)
from gwent_shared.json_payloads import parse_json_document, to_canonical

from gwent_evaluation.models import (
    RECORD_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSION,
    AgentIdentity,
    AgentSpec,
    AssetIdentities,
    DecisionSample,
    EvidenceRefs,
    MatchResult,
    RunManifest,
    ScheduledMatch,
    SchedulingPolicy,
    SuitePurpose,
    SuiteSpec,
    TrajectoryStep,
)
from gwent_evaluation.provenance import RepositoryProvenance, RuntimeProvenance
from gwent_evaluation.specs import SpecError, parse_agent_spec


class StorageError(ValueError):
    """Raised when a persisted experiment record is malformed."""


class CorruptRecordError(StorageError):
    """Raised when a persisted record fails its integrity check."""


def parse_record_mapping(text: str, *, context: str) -> Mapping[str, object]:
    """Parse one strict JSON record document, rejecting duplicate keys and non-finite numbers."""

    document = parse_json_document(text, context=context, error_factory=CorruptRecordError)
    return expect_mapping(document, context=context, error_factory=CorruptRecordError)


def record_to_dict(record: object) -> dict[str, object]:
    return cast(dict[str, object], to_canonical(record))


def decision_sample_to_dict(sample: DecisionSample) -> dict[str, object]:
    return {
        "index": sample.index,
        "kind": sample.kind.value,
        "actor": str(sample.actor),
        "observation": player_observation_to_dict(sample.observation),
        "legal_option_ids": list(sample.legal_option_ids),
        "chosen_option_id": sample.chosen_option_id,
        "duration_seconds": sample.duration_seconds,
        "failure": None if sample.failure is None else record_to_dict(sample.failure),
    }


def trajectory_step_to_dict(step: TrajectoryStep) -> dict[str, object]:
    return {
        "index": step.index,
        "kind": step.kind.value,
        "action_id": step.action_id,
        "state_before": game_state_to_dict(step.state_before),
        "state_after": game_state_to_dict(step.state_after),
        "event_fingerprints": list(step.event_fingerprints),
    }


def match_result_from_dict(payload: object) -> MatchResult:
    context = "match result"
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    schema_version = require_int_field(
        mapping,
        "schema_version",
        context=context,
        error_factory=StorageError,
    )
    if schema_version != RECORD_SCHEMA_VERSION:
        raise StorageError(
            f"{context} schema_version must be {RECORD_SCHEMA_VERSION}, "
            + f"found {schema_version}."
        )
    return MatchResult(
        schema_version=schema_version,
        case_id=require_str_field(mapping, "case_id", context=context, error_factory=StorageError),
        termination=_require_termination(mapping, context=context),
        candidate_agent_id=require_str_field(
            mapping, "candidate_agent_id", context=context, error_factory=StorageError
        ),
        opponent_agent_id=require_str_field(
            mapping, "opponent_agent_id", context=context, error_factory=StorageError
        ),
        candidate_seat=_require_player_id(mapping, "candidate_seat", context=context),
        requested_starting_player=_require_player_id(
            mapping, "requested_starting_player", context=context
        ),
        actual_starting_player=_optional_player_id(
            mapping, "actual_starting_player", context=context
        ),
        winner=_optional_player_id(mapping, "winner", context=context),
        candidate_score=_optional_float(mapping, "candidate_score", context=context),
        accepted_transitions=require_int_field(
            mapping, "accepted_transitions", context=context, error_factory=StorageError
        ),
        decision_count=require_int_field(
            mapping, "decision_count", context=context, error_factory=StorageError
        ),
        pending_choice_occurred=require_bool_field(
            mapping, "pending_choice_occurred", context=context, error_factory=StorageError
        ),
        observation_contract_version=require_int_field(
            mapping,
            "observation_contract_version",
            context=context,
            error_factory=StorageError,
        ),
        final_state_digest=optional_str_field(
            mapping, "final_state_digest", context=context, error_factory=StorageError
        ),
        semantic_digest=require_str_field(
            mapping, "semantic_digest", context=context, error_factory=StorageError
        ),
        decision_seconds=_require_float(mapping, "decision_seconds", context=context),
        execution_seconds=_require_float(mapping, "execution_seconds", context=context),
        environment_seed=require_int_field(
            mapping, "environment_seed", context=context, error_factory=StorageError
        ),
        evidence=_evidence_refs_from_dict(mapping, context=context),
        execution_identity=require_str_field(
            mapping, "execution_identity", context=context, error_factory=StorageError
        ),
        failure=_failure_from_dict(mapping, context=context),
    )


def scheduled_match_from_dict(payload: object) -> ScheduledMatch:
    context = "scheduled match"
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    return ScheduledMatch(
        case_id=require_str_field(mapping, "case_id", context=context, error_factory=StorageError),
        candidate_agent=_agent_spec_from_dict(
            require_field(mapping, "candidate_agent", context=context, error_factory=StorageError),
            context=f"{context}.candidate_agent",
        ),
        opponent_agent=_agent_spec_from_dict(
            require_field(mapping, "opponent_agent", context=context, error_factory=StorageError),
            context=f"{context}.opponent_agent",
        ),
        candidate_seat=_require_player_id(mapping, "candidate_seat", context=context),
        requested_starting_player=_require_player_id(
            mapping, "requested_starting_player", context=context
        ),
        candidate_deck_id=require_str_field(
            mapping, "candidate_deck_id", context=context, error_factory=StorageError
        ),
        opponent_deck_id=require_str_field(
            mapping, "opponent_deck_id", context=context, error_factory=StorageError
        ),
        environment_seed=require_int_field(
            mapping, "environment_seed", context=context, error_factory=StorageError
        ),
        candidate_policy_seed=require_int_field(
            mapping, "candidate_policy_seed", context=context, error_factory=StorageError
        ),
        opponent_policy_seed=require_int_field(
            mapping, "opponent_policy_seed", context=context, error_factory=StorageError
        ),
        game_id=GameId(
            require_str_field(mapping, "game_id", context=context, error_factory=StorageError)
        ),
        action_budget=require_int_field(
            mapping, "action_budget", context=context, error_factory=StorageError
        ),
    )


def run_manifest_from_dict(payload: object) -> RunManifest:
    context = "run manifest"
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    schema_version = _require_record_schema_version(mapping, context=context)
    return RunManifest(
        schema_version=schema_version,
        run_id=require_str_field(mapping, "run_id", context=context, error_factory=StorageError),
        suite=suite_spec_from_dict(
            require_field(mapping, "suite", context=context, error_factory=StorageError),
            context=f"{context}.suite",
        ),
        seed_derivation_version=require_int_field(
            mapping, "seed_derivation_version", context=context, error_factory=StorageError
        ),
        case_id_version=require_int_field(
            mapping, "case_id_version", context=context, error_factory=StorageError
        ),
        planned_case_ids=require_str_sequence_field(
            mapping, "planned_case_ids", context=context, error_factory=StorageError
        ),
        candidate=_agent_identity_from_dict(
            require_field(mapping, "candidate", context=context, error_factory=StorageError),
            context=f"{context}.candidate",
        ),
        opponents=tuple(
            _agent_identity_from_dict(item, context=f"{context}.opponents[{index}]")
            for index, item in enumerate(
                require_sequence_field(
                    mapping, "opponents", context=context, error_factory=StorageError
                )
            )
        ),
        assets=_asset_identities_from_dict(
            require_field(mapping, "assets", context=context, error_factory=StorageError),
            context=f"{context}.assets",
        ),
        repository=_repository_provenance_from_dict(
            require_field(mapping, "repository", context=context, error_factory=StorageError),
            context=f"{context}.repository",
        ),
        runtime=_runtime_provenance_from_dict(
            require_field(mapping, "runtime", context=context, error_factory=StorageError),
            context=f"{context}.runtime",
        ),
    )


def suite_spec_from_dict(payload: object, *, context: str = "suite spec") -> SuiteSpec:
    """Parse the fully materialized suite embedded in a run manifest."""

    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    schema_version = _require_record_schema_version(
        mapping,
        context=context,
        expected=SUPPORTED_SCHEMA_VERSION,
    )
    return SuiteSpec(
        schema_version=schema_version,
        suite_id=require_str_field(
            mapping, "suite_id", context=context, error_factory=StorageError
        ),
        purpose=require_enum_field(
            mapping, "purpose", SuitePurpose, context=context, error_factory=StorageError
        ),
        candidate=_agent_spec_from_dict(
            require_field(mapping, "candidate", context=context, error_factory=StorageError),
            context=f"{context}.candidate",
        ),
        opponents=tuple(
            _agent_spec_from_dict(item, context=f"{context}.opponents[{index}]")
            for index, item in enumerate(
                require_sequence_field(
                    mapping, "opponents", context=context, error_factory=StorageError
                )
            )
        ),
        deck_pairs=_deck_pairs_from_dict(mapping, context=context),
        seeds=_seeds_from_dict(mapping, context=context),
        scheduling=require_enum_field(
            mapping, "scheduling", SchedulingPolicy, context=context, error_factory=StorageError
        ),
        action_budget=require_int_field(
            mapping, "action_budget", context=context, error_factory=StorageError
        ),
        observation_contract_version=require_int_field(
            mapping,
            "observation_contract_version",
            context=context,
            error_factory=StorageError,
        ),
    )


def _require_record_schema_version(
    mapping: Mapping[str, object],
    *,
    context: str,
    expected: int = RECORD_SCHEMA_VERSION,
) -> int:
    schema_version = require_int_field(
        mapping, "schema_version", context=context, error_factory=StorageError
    )
    if schema_version != expected:
        raise StorageError(f"{context} schema_version must be {expected}, found {schema_version}.")
    return schema_version


def _agent_identity_from_dict(payload: object, *, context: str) -> AgentIdentity:
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    return AgentIdentity(
        agent_id=require_str_field(
            mapping, "agent_id", context=context, error_factory=StorageError
        ),
        family=require_str_field(mapping, "family", context=context, error_factory=StorageError),
        profile=optional_str_field(mapping, "profile", context=context, error_factory=StorageError),
        digest=require_str_field(mapping, "digest", context=context, error_factory=StorageError),
    )


def _asset_identities_from_dict(payload: object, *, context: str) -> AssetIdentities:
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    return AssetIdentities(
        deck_digests=_string_pairs(
            require_pair_sequence_field(
                mapping, "deck_digests", context=context, error_factory=StorageError
            ),
            context=f"{context}.deck_digests",
        ),
        card_data_digest=require_str_field(
            mapping, "card_data_digest", context=context, error_factory=StorageError
        ),
        leader_data_digest=require_str_field(
            mapping, "leader_data_digest", context=context, error_factory=StorageError
        ),
    )


def _repository_provenance_from_dict(payload: object, *, context: str) -> RepositoryProvenance:
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    return RepositoryProvenance(
        commit=optional_str_field(mapping, "commit", context=context, error_factory=StorageError),
        dirty=optional_bool_field(mapping, "dirty", context=context, error_factory=StorageError),
        implementation_digest=optional_str_field(
            mapping, "implementation_digest", context=context, error_factory=StorageError
        ),
        lockfile_digest=optional_str_field(
            mapping, "lockfile_digest", context=context, error_factory=StorageError
        ),
    )


def _runtime_provenance_from_dict(payload: object, *, context: str) -> RuntimeProvenance:
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    pairs = require_pair_sequence_field(
        mapping, "packages", context=context, error_factory=StorageError
    )
    return RuntimeProvenance(
        python_implementation=require_str_field(
            mapping, "python_implementation", context=context, error_factory=StorageError
        ),
        python_version=require_str_field(
            mapping, "python_version", context=context, error_factory=StorageError
        ),
        packages=tuple(
            (
                expect_str(
                    first, context=f"{context}.packages[{index}][0]", error_factory=StorageError
                ),
                expect_optional_str(
                    second, context=f"{context}.packages[{index}][1]", error_factory=StorageError
                ),
            )
            for index, (first, second) in enumerate(pairs)
        ),
    )


def _deck_pairs_from_dict(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> tuple[tuple[str, str], ...]:
    return _string_pairs(
        require_pair_sequence_field(
            mapping, "deck_pairs", context=context, error_factory=StorageError
        ),
        context=f"{context}.deck_pairs",
    )


def _string_pairs(
    pairs: tuple[tuple[object, object], ...],
    *,
    context: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            expect_str(first, context=f"{context}[{index}][0]", error_factory=StorageError),
            expect_str(second, context=f"{context}[{index}][1]", error_factory=StorageError),
        )
        for index, (first, second) in enumerate(pairs)
    )


def _seeds_from_dict(mapping: Mapping[str, object], *, context: str) -> tuple[int, ...]:
    return tuple(
        expect_int(item, context=f"{context}.seeds[{index}]", error_factory=StorageError)
        for index, item in enumerate(
            require_sequence_field(mapping, "seeds", context=context, error_factory=StorageError)
        )
    )


def trajectory_step_from_dict(
    payload: object,
    *,
    card_registry: CardRegistry | None = None,
) -> TrajectoryStep:
    context = "trajectory step"
    mapping = expect_mapping(payload, context=context, error_factory=StorageError)
    return TrajectoryStep(
        index=require_int_field(mapping, "index", context=context, error_factory=StorageError),
        kind=require_enum_field(
            mapping, "kind", MatchStepKind, context=context, error_factory=StorageError
        ),
        action_id=require_str_field(
            mapping, "action_id", context=context, error_factory=StorageError
        ),
        state_before=_game_state_from_dict(
            require_field(mapping, "state_before", context=context, error_factory=StorageError),
            context=f"{context}.state_before",
            card_registry=card_registry,
        ),
        state_after=_game_state_from_dict(
            require_field(mapping, "state_after", context=context, error_factory=StorageError),
            context=f"{context}.state_after",
            card_registry=card_registry,
        ),
        event_fingerprints=require_str_sequence_field(
            mapping, "event_fingerprints", context=context, error_factory=StorageError
        ),
    )


def _agent_spec_from_dict(payload: object, *, context: str) -> AgentSpec:
    try:
        return parse_agent_spec(payload, context=context)
    except SpecError as error:
        raise CorruptRecordError(str(error)) from error


def _game_state_from_dict(
    payload: object,
    *,
    context: str,
    card_registry: CardRegistry | None = None,
) -> GameState:
    try:
        return game_state_from_dict(
            expect_mapping(payload, context=context, error_factory=StorageError),
            card_registry=card_registry,
        )
    except GwentEngineError as error:
        raise CorruptRecordError(f"{context}: {error}") from error


def _require_termination(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> TerminationReason:
    return require_enum_field(
        mapping,
        "termination",
        TerminationReason,
        context=context,
        error_factory=StorageError,
    )


def _require_player_id(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> PlayerId:
    return require_constructor_field(
        mapping, field, player_id, context=context, error_factory=StorageError
    )


def _optional_player_id(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> PlayerId | None:
    return optional_constructor_field(
        mapping, field, player_id, context=context, error_factory=StorageError
    )


def _require_float(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> float:
    return _as_float(
        require_field(mapping, field, context=context, error_factory=StorageError),
        context=context,
        label=field,
    )


def _optional_float(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> float | None:
    value = mapping.get(field)
    if value is None:
        return None
    return _as_float(value, context=context, label=field)


def _as_float(value: object, *, context: str, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StorageError(f"{context} field {label!r} must be numeric.")
    return float(value)


def _require_text(
    mapping: Mapping[str, object],
    field: str,
    *,
    context: str,
) -> str:
    value = require_field(mapping, field, context=context, error_factory=StorageError)
    if not isinstance(value, str):
        raise StorageError(f"{context} field {field!r} must be a string.")
    return value


def _evidence_refs_from_dict(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> EvidenceRefs:
    evidence_context = f"{context}.evidence"
    evidence = expect_mapping(
        require_field(mapping, "evidence", context=context, error_factory=StorageError),
        context=evidence_context,
        error_factory=StorageError,
    )
    return EvidenceRefs(
        samples_digest=optional_str_field(
            evidence, "samples_digest", context=evidence_context, error_factory=StorageError
        ),
        trajectory_digest=optional_str_field(
            evidence, "trajectory_digest", context=evidence_context, error_factory=StorageError
        ),
        samples_path=optional_str_field(
            evidence,
            "samples_path",
            context=evidence_context,
            error_factory=StorageError,
        ),
        trajectory_path=optional_str_field(
            evidence,
            "trajectory_path",
            context=evidence_context,
            error_factory=StorageError,
        ),
    )


def _failure_from_dict(
    mapping: Mapping[str, object],
    *,
    context: str,
) -> MatchFailure | None:
    raw = mapping.get("failure")
    if raw is None:
        return None
    failure_context = f"{context}.failure"
    failure = expect_mapping(raw, context=failure_context, error_factory=StorageError)
    return MatchFailure(
        stage=require_enum_field(
            failure,
            "stage",
            MatchFailureStage,
            context=failure_context,
            error_factory=StorageError,
        ),
        actor=_optional_player_id(failure, "actor", context=failure_context),
        exception_type=require_str_field(
            failure,
            "exception_type",
            context=failure_context,
            error_factory=StorageError,
        ),
        message=_require_text(failure, "message", context=failure_context),
    )
