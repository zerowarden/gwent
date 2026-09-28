"""Sequential optimization with verified reuse and deterministic journal replay.

Only optimization cases execute here. Validation, held-out confirmation, and
promotion are separate stages. Backends receive numeric settings and fitness.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import NoReturn, final

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_shared.extract import expect_mapping

from gwent_evaluation.execution import EvidencePolicy, validate_run_environment
from gwent_evaluation.models import SpecError
from gwent_evaluation.progress import advance
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.storage import RunConflictError
from gwent_evaluation.tuning.backends import create_optimizer
from gwent_evaluation.tuning.models import OptimizerMethod, StudySpec
from gwent_evaluation.tuning.objective import (
    TrialEvaluation,
    TrialIdentity,
    TrialStatus,
    candidate_evaluation_identity,
    evaluate_candidate,
    load_trial_evaluation,
)
from gwent_evaluation.tuning.optimizers import (
    CachedEvaluation,
    EvaluationCache,
    OptimizerStop,
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
    ScoredCandidate,
    SearchOutcome,
    summarize_search,
)
from gwent_evaluation.tuning.parameters import encode_parameters
from gwent_evaluation.tuning.sensitivity import SensitivityReport, require_sensitivity
from gwent_evaluation.tuning.specs import study_from_dict
from gwent_evaluation.tuning.storage import StudyStore, read_checked_document


class StudyStoppedError(SpecError):
    """The journal records a failure; it cannot be retried as an ordinary loss."""


def _candidate_summary(candidate: ScoredCandidate) -> dict[str, object]:
    trial = candidate.evaluation.trial
    return {
        "configuration_digest": trial.configuration_digest,
        "coordinates": list(candidate.coordinates),
        "score": trial.require_eligible_score(),
        "run_root": trial.run_root,
        "cache_hit": candidate.evaluation.cache_hit,
    }


@dataclass(frozen=True, slots=True)
class MethodResult:
    method: OptimizerMethod
    stop: OptimizerStop
    trials: tuple[ScoredCandidate, ...]
    outcome: SearchOutcome


@dataclass(frozen=True, slots=True)
class StudyResult:
    study_digest: str
    incumbent: ScoredCandidate
    methods: tuple[MethodResult, ...]
    outcome: SearchOutcome

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "stage": "optimization_complete",
            "study_digest": self.study_digest,
            "promotion": "not_assessed",
            "incumbent": _candidate_summary(self.incumbent),
            "best": _candidate_summary(self.outcome.best),
            "optimization_score_gain": self.outcome.optimization_score_gain,
            "incumbent_retained": self.outcome.incumbent_retained,
            "counts": record_to_dict(self.outcome.counts),
            "methods": [
                {
                    "method": result.method.value,
                    "stop": record_to_dict(result.stop),
                    "best": _candidate_summary(result.outcome.best),
                    "optimization_score_gain": result.outcome.optimization_score_gain,
                    "counts": record_to_dict(result.outcome.counts),
                    "trials": [_candidate_summary(trial) for trial in result.trials],
                }
                for result in self.methods
            ],
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    proposal: Proposal
    configuration: HeuristicConfiguration
    identity: TrialIdentity

    @property
    def run_id(self) -> str:
        return "trial-" + canonical_digest(self.identity).removeprefix("sha256:")

    @property
    def relative_root(self) -> Path:
        return Path("runs") / self.run_id


def run_study(
    study: StudySpec,
    *,
    output_root: Path,
    repository_root: Path,
    sensitivity_report: SensitivityReport,
    recover_lock: bool = False,
    verification_only: bool = False,
) -> StudyResult:
    """Run or resume optimization, stopping before any validation/test execution.

    Completed journal entries are checked against regenerated proposals and
    reloaded match evidence. Missing committed results are conflicts, never work
    to rerun. Match work without a committed trial is resumed by the evaluator.
    """
    require_sensitivity(study, sensitivity_report)
    if study.evidence_policy is not EvidencePolicy.NONE:
        raise SpecError("Study optimization requires summary recording.")
    validate_run_environment(study.optimization, repository_root=repository_root)
    store = StudyStore(output_root, verification_only=verification_only)
    with store.writer(recover_lock=recover_lock):
        # Recomputing preflight from verified existing runs changes operational
        # costs, not its scientific evidence. Freeze the latter for recovery.
        evidence = replace(
            sensitivity_report, executed_matches=0, match_execution_seconds=0, disk_bytes=0
        )
        store.prepare({"study": record_to_dict(study), "sensitivity": evidence.to_dict()})
        runner = _StudyRunner(study, store, repository_root, sensitivity_report)
        result = runner.run()
        _ = store.record("complete", result.to_dict())
        store.finish()
        if not verification_only:
            store.write_report(result.to_dict())
        return result


def load_completed_study(
    root: Path, *, repository_root: Path, recover_lock: bool = False
) -> tuple[StudySpec, StudyResult]:
    """Verify frozen inputs and every committed optimization trial without playing games."""
    raw = read_checked_document(root / "snapshot.json")
    snapshot = expect_mapping(
        raw.get("snapshot"), context="study snapshot", error_factory=SpecError
    )
    try:
        study = study_from_dict(snapshot.get("study"))
        preflight = SensitivityReport.from_dict(snapshot.get("sensitivity"))
    except (KeyError, TypeError, ValueError) as error:
        raise SpecError(f"Invalid frozen study inputs: {error}") from error
    result = run_study(
        study,
        output_root=root,
        repository_root=repository_root,
        sensitivity_report=preflight,
        recover_lock=recover_lock,
        verification_only=True,
    )
    return study, result


@final
class _StudyRunner:
    def __init__(
        self,
        study: StudySpec,
        store: StudyStore,
        repository_root: Path,
        preflight: SensitivityReport,
    ) -> None:
        self.study = study
        self.store = store
        self.repository_root = repository_root
        self.preflight = preflight
        self.cache = EvaluationCache()

    def _require_running(self) -> None:
        entry = self.store.next_entry
        if entry is not None and entry.kind == "halt":
            raise StudyStoppedError(f"Study previously stopped: {entry.payload.get('detail')}")

    def _halt(self, payload: dict[str, object]) -> NoReturn:
        _ = self.store.record("halt", payload)
        self.store.write_report(
            {"stage": "stopped", "study_digest": self.study.digest(), **payload}
        )
        raise StudyStoppedError(str(payload["detail"]))

    def _candidate(self, proposal: Proposal) -> _Candidate:
        configuration = self.study.bind(proposal.coordinates)
        identity = candidate_evaluation_identity(
            self.study, configuration, repository_root=self.repository_root
        )
        return _Candidate(proposal, configuration, identity)

    def _load_or_evaluate(self, candidate: _Candidate, *, committed: bool) -> TrialEvaluation:
        root = self.store.root / candidate.relative_root
        existing: TrialEvaluation | None = None
        if committed or root.exists():
            existing = load_trial_evaluation(
                self.study,
                candidate.configuration,
                run_root=root,
                repository_root=self.repository_root,
                sensitivity_report=self.preflight,
            )
        if committed:
            assert existing is not None
            try:
                _ = existing.require_eligible_score()
            except SpecError as error:
                raise RunConflictError(
                    "Committed trial evidence is incomplete or invalid."
                ) from error
            return existing
        if existing is not None and existing.status is not TrialStatus.INCOMPLETE:
            return existing
        return evaluate_candidate(
            self.study,
            candidate.configuration,
            run_id=candidate.run_id,
            output_root=self.store.root / "runs",
            repository_root=self.repository_root,
            sensitivity_report=self.preflight,
        )

    def _evaluate(
        self, method: OptimizerMethod | None, candidate: _Candidate
    ) -> tuple[ScoredCandidate, str]:
        self._require_running()
        label = (
            "incumbent"
            if method is None
            else f"{method.value} proposal {candidate.proposal.index + 1}"
        )
        advance(f"{label}: verifying or evaluating")
        current = candidate_evaluation_identity(
            self.study, candidate.configuration, repository_root=self.repository_root
        )
        if current != candidate.identity:
            raise RunConflictError("Candidate evaluation identity changed after proposal.")
        entry = self.store.next_entry
        if entry is None and self.store.verification_only:
            raise RunConflictError("Optimization has an uncommitted trial.")
        slot = {
            "method": None if method is None else method.value,
            "index": candidate.proposal.index,
        }
        if entry is not None and (
            entry.kind != "trial"
            or any(entry.payload.get(key) != value for key, value in slot.items())
        ):
            raise RunConflictError("Expected a trial for the current proposal slot.")

        def evaluate() -> TrialEvaluation:
            trial = self._load_or_evaluate(candidate, committed=entry is not None)
            try:
                _ = trial.require_eligible_score()
            except SpecError:
                self._halt(
                    {
                        **slot,
                        "detail": "Trial did not produce complete eligible optimization evidence.",
                        "trial": record_to_dict(
                            replace(trial, run_root=str(candidate.relative_root))
                        ),
                    }
                )
            return trial

        evaluation = self.cache.evaluate(candidate.identity, evaluate)
        normalized = replace(
            evaluation.trial, run_root=str(candidate.relative_root), fresh_matches=0
        )
        # Count work over the study's lifetime, including matches committed before
        # an interruption. An identity's first slot owns its matches; duplicates
        # own none. Per-invocation fresh work remains the objective adapter's job.
        fresh_matches = 0 if evaluation.cache_hit else normalized.completed
        digest = self.store.record(
            "trial",
            {
                **slot,
                "trial": record_to_dict(normalized),
                "cache_hit": evaluation.cache_hit,
                "fresh_matches": fresh_matches,
            },
        )
        scored = ScoredCandidate(
            candidate.proposal.coordinates,
            CachedEvaluation(
                replace(normalized, fresh_matches=fresh_matches), evaluation.cache_hit
            ),
        )
        return scored, digest

    def run(self) -> StudyResult:
        self._require_running()
        incumbent = self._candidate(
            Proposal(
                -1,
                encode_parameters(
                    self.study.parameter_space,
                    self.study.incumbent,
                    frozen_configuration=self.study.incumbent,
                ),
            )
        )
        _ = self.store.record("incumbent", record_to_dict(incumbent))
        reference, _ = self._evaluate(None, incumbent)
        methods: list[MethodResult] = []
        all_trials: list[ScoredCandidate] = []
        for settings in self.study.optimizers:
            self._require_running()
            backend = create_optimizer(self.study, settings.method)
            trials: list[ScoredCandidate] = []
            population = 0
            while True:
                self._require_running()
                try:
                    batch = backend.ask()
                except SpecError as error:
                    self._halt({"method": settings.method.value, "detail": str(error)})
                if not batch:
                    break
                candidates = tuple(self._candidate(proposal) for proposal in batch)
                _ = self.store.record(
                    "ask",
                    {
                        "method": settings.method.value,
                        "population": population,
                        "candidates": [record_to_dict(candidate) for candidate in candidates],
                    },
                )
                values: list[ProposalFitness] = []
                references: list[str] = []
                for candidate in candidates:
                    scored, digest = self._evaluate(settings.method, candidate)
                    trials.append(scored)
                    references.append(digest)
                    values.append(
                        ProposalFitness(
                            candidate.proposal,
                            1.0 - scored.evaluation.trial.require_eligible_score(),
                        )
                    )
                _ = self.store.record(
                    "tell",
                    {
                        "method": settings.method.value,
                        "population": population,
                        "results": [record_to_dict(value) for value in values],
                        "trial_records": references,
                    },
                )
                try:
                    backend.tell(tuple(values))
                except SpecError as error:
                    self._halt({"method": settings.method.value, "detail": str(error)})
                population += 1
            stop = backend.stop
            if stop is None:
                raise RunConflictError("Optimizer ended without stop diagnostics.")
            if stop.reason is OptimizerStopReason.BACKEND_FAILURE:
                self._halt(
                    {
                        "method": settings.method.value,
                        "detail": "Optimizer stopped with a backend failure.",
                        "stop": record_to_dict(stop),
                    }
                )
            _ = self.store.record(
                "stop", {"method": settings.method.value, "stop": record_to_dict(stop)}
            )
            outcome = summarize_search(reference, tuple(trials))
            methods.append(MethodResult(settings.method, stop, tuple(trials), outcome))
            all_trials.extend(trials)
        return StudyResult(
            self.study.digest(),
            reference,
            tuple(methods),
            summarize_search(reference, tuple(all_trials)),
        )
