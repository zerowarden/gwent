"""Complete, identity-checked evaluation runs adapted to optimizer fitness."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration

from gwent_evaluation.execution import (
    EvidencePolicy,
    candidate_manifest,
    execute_run,
    validate_run_environment,
    validate_worker_count,
)
from gwent_evaluation.models import RunManifest, SpecError, TerminationReason
from gwent_evaluation.progress import advance
from gwent_evaluation.provenance import canonical_digest, default_repository_root
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.reporting import RunReport, build_run_report
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning.models import StudyMode, StudySpec
from gwent_evaluation.tuning.parameters import encode_parameters, finite_float
from gwent_evaluation.tuning.sensitivity import SensitivityReport, require_sensitivity
from gwent_evaluation.tuning.storage import StudyStore
from gwent_evaluation.validation import LoadedRun, execution_identity


class TrialStatus(StrEnum):
    ELIGIBLE = "eligible"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class TrialReason(StrEnum):
    DIAGNOSTIC_PROVENANCE = "diagnostic_provenance"
    MISSING_RESULTS = "missing_results"
    MATCH_FAILURE = "match_failure"


@dataclass(frozen=True, slots=True)
class TrialIdentity:
    study_digest: str
    configuration_digest: str
    execution_identity: str


@dataclass(frozen=True, slots=True)
class TrialResultReference:
    case_id: str
    path: str
    record_digest: str
    semantic_digest: str
    termination: TerminationReason


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    """Failures stop a study; incomplete trials may resume their missing cases.

    Diagnostic scores remain descriptive and never yield optimizer fitness.
    Identity conflicts and corrupt records are hard exceptions, not trial losses.
    """

    schema_version: int
    study_digest: str
    configuration_digest: str
    candidate_digest: str
    suite_id: str
    suite_digest: str
    benchmark_identity: str
    execution_identity: str
    run_root: str
    results: tuple[TrialResultReference, ...]
    planned: int
    completed: int
    failed: int
    missing: int
    score: float | None
    valid_for_comparison: bool
    optimization_evidence: bool
    status: TrialStatus
    reasons: tuple[TrialReason, ...]
    fresh_matches: int = 0

    @property
    def identity(self) -> TrialIdentity:
        return TrialIdentity(self.study_digest, self.configuration_digest, self.execution_identity)

    @property
    def fitness(self) -> float | None:
        if self.status is not TrialStatus.ELIGIBLE:
            return None
        return 1.0 - self.require_eligible_score()

    def require_eligible_score(self) -> float:
        """The common eligibility boundary for optimizer fitness, reuse, and ranking."""
        if (
            self.status is not TrialStatus.ELIGIBLE
            or not self.valid_for_comparison
            or not self.optimization_evidence
            or self.reasons
            or self.planned <= 0
            or self.completed != self.planned
            or self.failed != 0
            or self.missing != 0
            or len(self.results) != self.planned
        ):
            raise SpecError("Only complete eligible trial evidence can be reused or ranked.")
        score = finite_float(self.score, context="trial score")
        if not 0 <= score <= 1:
            raise SpecError("Trial score must lie in [0, 1].")
        if type(self.fresh_matches) is not int or not 0 <= self.fresh_matches <= self.planned:
            raise SpecError("Fresh match count must lie between zero and the planned count.")
        return score

    def to_dict(self) -> dict[str, object]:
        return {**record_to_dict(self), "fitness": self.fitness}


def _candidate_manifest(
    study: StudySpec, configuration: HeuristicConfiguration, run_id: str
) -> RunManifest:
    _ = encode_parameters(
        study.parameter_space, configuration, frozen_configuration=study.incumbent
    )
    return candidate_manifest(study.optimization, configuration, run_id=run_id)


def _require_objective_preflight(
    study: StudySpec, sensitivity_report: SensitivityReport | None
) -> None:
    if study.evidence_policy is not EvidencePolicy.NONE:
        raise SpecError(
            "Bulk candidate evaluation requires summary recording (evidence_policy none)."
        )
    if study.mode is StudyMode.SCIENTIFIC:
        if sensitivity_report is None:
            raise SpecError("Scientific candidate evaluation requires a sensitivity report.")
        require_sensitivity(study, sensitivity_report)


def candidate_evaluation_identity(
    study: StudySpec,
    configuration: HeuristicConfiguration,
    *,
    repository_root: Path | None = None,
) -> TrialIdentity:
    """Check current conditions before looking up study-local evaluation reuse."""
    expected = _candidate_manifest(study, configuration, study.optimization.run_id)
    validate_run_environment(expected, repository_root=repository_root or default_repository_root())
    return TrialIdentity(study.digest(), configuration.digest(), execution_identity(expected))


def load_trial_evaluation(
    study: StudySpec,
    configuration: HeuristicConfiguration,
    *,
    run_root: Path,
    repository_root: Path | None = None,
    sensitivity_report: SensitivityReport | None = None,
) -> TrialEvaluation:
    """Verify existing evidence without running games, including interrupted trials."""
    _require_objective_preflight(study, sensitivity_report)
    store = RunStore.from_root(run_root)
    expected = _candidate_manifest(study, configuration, store.run_id)
    loaded = store.load()
    if loaded.manifest != expected:
        raise RunConflictError("Trial manifest differs from the frozen study or candidate.")
    validate_run_environment(expected, repository_root=repository_root or default_repository_root())
    report = build_run_report(loaded, bootstrap=study.bootstrap)
    reasons: list[TrialReason] = []
    if report.failed_matches:
        reasons.append(TrialReason.MATCH_FAILURE)
    if report.missing_matches:
        reasons.append(TrialReason.MISSING_RESULTS)
    if not expected.repository.is_clean_checkout or study.mode is not StudyMode.SCIENTIFIC:
        reasons.append(TrialReason.DIAGNOSTIC_PROVENANCE)
    if report.failed_matches:
        status = TrialStatus.FAILED
    elif report.missing_matches:
        status = TrialStatus.INCOMPLETE
    elif not report.optimization_evidence:
        status = TrialStatus.DIAGNOSTIC_ONLY
    else:
        status = TrialStatus.ELIGIBLE
    return TrialEvaluation(
        schema_version=1,
        study_digest=study.digest(),
        configuration_digest=configuration.digest(),
        candidate_digest=loaded.manifest.candidate.digest,
        suite_id=expected.suite.suite_id,
        suite_digest=canonical_digest(expected.suite),
        benchmark_identity=loaded.benchmark_identity,
        execution_identity=loaded.execution_identity,
        run_root=str(store.root),
        results=tuple(
            TrialResultReference(
                match.case_id,
                store.result_path(match.case_id).relative_to(store.root).as_posix(),
                loaded.result_digests[match.case_id],
                result.semantic_digest,
                result.termination,
            )
            for match in loaded.matches
            if (result := loaded.results.get(match.case_id)) is not None
        ),
        planned=report.planned_matches,
        completed=report.completed_matches,
        failed=report.failed_matches,
        missing=report.missing_matches,
        score=report.balanced_score,
        valid_for_comparison=report.valid_for_comparison,
        optimization_evidence=report.optimization_evidence,
        status=status,
        reasons=tuple(reasons),
    )


def evaluate_candidate(
    study: StudySpec,
    configuration: HeuristicConfiguration,
    *,
    run_id: str,
    output_root: Path,
    repository_root: Path | None = None,
    sensitivity_report: SensitivityReport | None = None,
) -> TrialEvaluation:
    """Execute or resume only optimization cases using summary recording.

    The evaluator checks the pinned manifest before writing or playing a match;
    loading verifies persisted identities and the environment again afterward.
    Interruptions propagate, leaving existing atomic match results resumable.
    """
    _require_objective_preflight(study, sensitivity_report)
    expected = _candidate_manifest(study, configuration, run_id)
    repository_root = repository_root or default_repository_root()
    run = execute_run(
        suite=expected.suite,
        run_id=run_id,
        output_root=output_root,
        repository_root=repository_root,
        evidence_policy=EvidencePolicy.NONE,
        expected_manifest=expected,
    )
    trial = load_trial_evaluation(
        study,
        configuration,
        run_root=run.root,
        repository_root=repository_root,
        sensitivity_report=sensitivity_report,
    )
    return replace(trial, fresh_matches=len(run.executed_case_ids))


@dataclass(frozen=True, slots=True)
class RecordedEvaluation:
    loaded: LoadedRun
    report: RunReport


def evaluate_recorded_candidate(
    store: StudyStore,
    study: StudySpec,
    template: RunManifest,
    configuration: HeuristicConfiguration,
    *,
    repository_root: Path,
    workers: int = 1,
) -> RecordedEvaluation:
    validate_worker_count(workers)
    advance(f"{template.suite.purpose.value}: checking candidate {configuration.digest()}")
    digest = configuration.digest()
    run_id = "candidate-" + digest.removeprefix("sha256:")
    expected = candidate_manifest(template, configuration, run_id=run_id)
    validate_run_environment(expected, repository_root=repository_root)
    entry = store.next_entry
    if entry is not None and (
        entry.kind != "evaluation" or entry.payload.get("configuration_digest") != digest
    ):
        raise RunConflictError("Unexpected candidate in the frozen evaluation sequence.")
    if entry is None and store.verification_only:
        raise RunConflictError("Recorded evaluation sequence is incomplete.")
    run = RunStore(store.root / "runs", run_id)
    loaded = run.load() if entry is not None or run.root.exists() else None
    if loaded is not None and loaded.manifest != expected:
        raise RunConflictError("Evaluation evidence differs from the frozen candidate or suite.")
    report = None if loaded is None else build_run_report(loaded, bootstrap=study.bootstrap)
    # Recorded failures are terminal. Only interrupted, uncommitted work may resume.
    if entry is None and (report is None or (report.missing_matches and not report.failed_matches)):
        execution = execute_run(
            suite=expected.suite,
            run_id=run_id,
            output_root=run.output_root,
            repository_root=repository_root,
            evidence_policy=EvidencePolicy.NONE,
            expected_manifest=expected,
            workers=workers,
        )
        loaded = RunStore.from_root(execution.root).load()
        report = build_run_report(loaded, bootstrap=study.bootstrap)
    assert loaded is not None and report is not None
    validate_run_environment(expected, repository_root=repository_root)
    _ = store.record(
        "evaluation",
        {
            "configuration_digest": digest,
            "manifest_digest": canonical_digest(loaded.manifest),
            "run_root": str(run.root.relative_to(store.root)),
            "results": dict(loaded.result_digests),
            "report": record_to_dict(report),
        },
    )
    return RecordedEvaluation(loaded, report)
