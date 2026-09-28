"""Freeze validation selection before explicitly consuming held-out evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_engine.ai.policy_artifacts import PolicyArtifact, PolicyStatus
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.models import SpecError
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.reporting import (
    RunComparison,
    build_run_comparison,
)
from gwent_evaluation.storage import RunConflictError, atomic_write_text
from gwent_evaluation.tuning.models import StudySpec
from gwent_evaluation.tuning.objective import RecordedEvaluation, evaluate_recorded_candidate
from gwent_evaluation.tuning.storage import (
    StudyStore,
    read_checked_document,
    write_checked_document,
)
from gwent_evaluation.tuning.study import StudyResult, load_completed_study
from gwent_evaluation.tuning.verification import record_verification, require_verification


@dataclass(frozen=True, slots=True)
class StratumChange:
    dimension: str
    value: str
    difference: float


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    configuration_digest: str
    comparison: RunComparison
    strata: tuple[StratumChange, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelectionResult:
    study_digest: str
    finalist_digests: tuple[str, ...]
    selected: HeuristicConfiguration | None
    assessments: tuple[CandidateAssessment, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "stage": "validation_complete",
            **record_to_dict(self),
            "selected_digest": None if self.selected is None else self.selected.digest(),
            "incumbent_retained": self.selected is None,
            "promotion": "not_assessed",
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    study_digest: str
    selection_digest: str
    selected_digest: str | None
    promoted: bool
    assessment: CandidateAssessment | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "stage": "confirmation_complete", **record_to_dict(self)}


def assess_candidate(
    study: StudySpec,
    reference: RecordedEvaluation,
    candidate: RecordedEvaluation,
    *,
    confirmation: bool,
) -> CandidateAssessment:
    comparison = build_run_comparison(reference.loaded, candidate.loaded, bootstrap=study.bootstrap)
    reasons: list[str] = []
    changes: list[StratumChange] = []
    if not comparison.valid or not comparison.optimization_evidence:
        reasons.append("invalid_or_incomplete_evidence")
    else:
        difference = comparison.mean_difference
        assert difference is not None
        if difference <= 0:
            reasons.append("no_positive_improvement")
        if confirmation and difference < study.selection.minimum_test_improvement:
            reasons.append("improvement_below_threshold")
        if comparison.interval.lower is None:
            reasons.append("insufficient_sample")
        elif comparison.interval.lower <= 0:
            reasons.append("inconclusive_improvement")
        reference_strata = {
            (item.dimension, item.value): item.summary.score
            for item in reference.report.strata
            if item.dimension in study.selection.strata
        }
        for item in candidate.report.strata:
            if item.dimension not in study.selection.strata:
                continue
            original = reference_strata[(item.dimension, item.value)]
            score = item.summary.score
            assert original is not None and score is not None
            change = StratumChange(item.dimension, item.value, score - original)
            changes.append(change)
            if change.difference < -study.selection.maximum_stratum_decline:
                reasons.append(f"stratum_decline:{item.dimension}:{item.value}")
    configuration = candidate.loaded.manifest.suite.candidate.heuristic_configuration
    assert configuration is not None
    return CandidateAssessment(configuration.digest(), comparison, tuple(changes), tuple(reasons))


def _export(
    path: Path,
    study: StudySpec,
    selection: SelectionResult,
    *,
    status: PolicyStatus,
    evidence_digest: str,
) -> None:
    assert selection.selected is not None
    repository = study.optimization.repository
    assert repository.commit is not None and repository.implementation_digest is not None
    artifact = PolicyArtifact(
        selection.selected,
        status,
        study.digest(),
        selection.digest(),
        evidence_digest,
        repository.commit,
        repository.implementation_digest,
    )
    payload = artifact.to_dict()
    if path.exists():
        if PolicyArtifact.load(path).to_dict() != payload:
            raise RunConflictError("Exported policy differs from its frozen evidence.")
    else:
        atomic_write_text(path, dump_pretty_json(payload))


def _validate_finalists(
    store: StudyStore,
    study: StudySpec,
    finalists: tuple[HeuristicConfiguration, ...],
    *,
    repository_root: Path,
) -> SelectionResult:
    result = SelectionResult(
        study.digest(),
        tuple(item.digest() for item in finalists),
        None,
        (),
        (),
    )
    if not finalists:
        return replace(result, reasons=("no_optimization_challenger",))
    reference = evaluate_recorded_candidate(
        store, study, study.validation, study.incumbent, repository_root=repository_root
    )
    if not reference.report.optimization_evidence:
        return replace(result, reasons=("invalid_incumbent_validation",))
    assessments: list[CandidateAssessment] = []
    for configuration in finalists:
        candidate = evaluate_recorded_candidate(
            store, study, study.validation, configuration, repository_root=repository_root
        )
        assessments.append(assess_candidate(study, reference, candidate, confirmation=False))
        if not candidate.report.optimization_evidence:
            return replace(
                result, assessments=tuple(assessments), reasons=("invalid_challenger_validation",)
            )
    result = replace(result, assessments=tuple(assessments))
    eligible = [item for item in assessments if not item.reasons]
    if not eligible:
        return replace(result, reasons=("no_qualifying_validation_challenger",))
    best_score = max(item.comparison.candidate_score or 0.0 for item in eligible)
    best = [item for item in eligible if item.comparison.candidate_score == best_score]
    if len(best) != 1:
        return replace(result, reasons=("tied_validation_finalists",))
    selected = next(
        config for config in finalists if config.digest() == best[0].configuration_digest
    )
    return replace(result, selected=selected)


def _select(
    store: StudyStore, study: StudySpec, optimization: StudyResult, *, repository_root: Path
) -> SelectionResult:
    store.prepare({"study": record_to_dict(study), "optimization": optimization.to_dict()})
    baseline = optimization.incumbent.evaluation.trial.require_eligible_score()
    finalists = tuple(
        study.bind(candidate.coordinates)
        for candidate in optimization.outcome.ranked_candidates
        if candidate.evaluation.trial.configuration_digest != study.incumbent.digest()
        and candidate.evaluation.trial.require_eligible_score() > baseline
    )[: study.selection.finalist_count]
    _ = store.record(
        "finalists",
        {
            "configurations": [configuration.to_dict() for configuration in finalists],
            "digests": [configuration.digest() for configuration in finalists],
        },
    )
    result = _validate_finalists(store, study, finalists, repository_root=repository_root)
    _ = store.record("selection", result.to_dict())
    store.finish()
    path = store.root / "selection.json"
    if path.exists() or store.verification_only:
        if read_checked_document(path) != result.to_dict():
            raise RunConflictError("Frozen selection differs from verified validation evidence.")
    else:
        _ = write_checked_document(path, result.to_dict())
    if not store.verification_only:
        store.write_report(result.to_dict())
    if result.selected is not None:
        artifact_path = store.root / "selected-policy.json"
        if store.verification_only and not artifact_path.is_file():
            raise RunConflictError("Selected policy artifact is missing.")
        _export(
            artifact_path,
            study,
            result,
            status=PolicyStatus.UNPROMOTED,
            evidence_digest=result.digest(),
        )
    return result


def select_challenger(
    optimization_root: Path, *, repository_root: Path, recover_lock: bool = False
) -> SelectionResult:
    study, optimization = load_completed_study(
        optimization_root, repository_root=repository_root, recover_lock=recover_lock
    )
    store = StudyStore(optimization_root / "selection")
    with store.writer(recover_lock=recover_lock):
        return _select(store, study, optimization, repository_root=repository_root)


def verify_selection(
    optimization_root: Path, *, repository_root: Path, recover_lock: bool = False
) -> Mapping[str, object]:
    """Run repository correctness gates for the already frozen challenger."""
    study, optimization = load_completed_study(
        optimization_root, repository_root=repository_root, recover_lock=recover_lock
    )
    store = StudyStore(optimization_root / "selection", verification_only=True)
    with store.writer(recover_lock=recover_lock):
        selected = _select(store, study, optimization, repository_root=repository_root)
        if selected.selected is None:
            raise SpecError("There is no selected challenger to verify.")
        return record_verification(
            store.root, study, selected.digest(), repository_root=repository_root
        )


def finalize_study(
    optimization_root: Path, *, repository_root: Path, recover_lock: bool = False
) -> ConfirmationResult:
    study, optimization = load_completed_study(
        optimization_root, repository_root=repository_root, recover_lock=recover_lock
    )
    selection_store = StudyStore(optimization_root / "selection", verification_only=True)
    with selection_store.writer(recover_lock=recover_lock):
        selection = _select(selection_store, study, optimization, repository_root=repository_root)
        verification = None
        if selection.selected is not None:
            verification = require_verification(selection_store.root, study, selection.digest())
        store = StudyStore(selection_store.root / "confirmation")
        with store.writer(recover_lock=recover_lock):
            store.prepare(
                {
                    "study": record_to_dict(study),
                    "selection": selection.to_dict(),
                    "verification": verification,
                }
            )
            assessment = None
            reasons: tuple[str, ...] = ("incumbent_retained_after_validation",)
            if selection.selected is not None:
                reference = evaluate_recorded_candidate(
                    store, study, study.test, study.incumbent, repository_root=repository_root
                )
                if reference.report.optimization_evidence:
                    candidate = evaluate_recorded_candidate(
                        store,
                        study,
                        study.test,
                        selection.selected,
                        repository_root=repository_root,
                    )
                    assessment = assess_candidate(study, reference, candidate, confirmation=True)
                    reasons = assessment.reasons
                else:
                    reasons = ("invalid_incumbent_confirmation",)
            result = ConfirmationResult(
                study.digest(),
                selection.digest(),
                None if selection.selected is None else selection.selected.digest(),
                not reasons,
                assessment,
                reasons,
            )
            _ = store.record("confirmation", result.to_dict())
            store.finish()
            store.write_report(result.to_dict())
            if selection.selected is not None:
                _export(
                    store.root / "policy.json",
                    study,
                    selection,
                    status=PolicyStatus.PROMOTED if result.promoted else PolicyStatus.UNPROMOTED,
                    evidence_digest=canonical_digest(result.to_dict()),
                )
            return result
