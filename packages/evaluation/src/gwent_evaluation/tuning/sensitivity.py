"""Player-safe score diagnostics and a prespecified complete-match control panel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from gwent_engine.ai.action_ids import action_to_id
from gwent_engine.ai.arena.models import MatchDecisionKind
from gwent_engine.ai.baseline.decision_plan import build_decision_plan
from gwent_engine.ai.baseline.evaluation import explain_ranked_actions
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_engine.serialize.actions import action_from_id
from gwent_shared.extract import (
    expect_finite_float,
    expect_int,
    expect_mapping,
    expect_sequence,
    expect_str,
)
from gwent_shared.json_payloads import dump_pretty_json

from gwent_evaluation.agents import resolve_agent
from gwent_evaluation.assets import ResolvedAssets, resolve_assets
from gwent_evaluation.execution import EvidencePolicy, execute_run, validate_run_environment
from gwent_evaluation.metrics import block_outcomes, compute_run_metrics
from gwent_evaluation.models import DecisionSample, SpecError, SuitePurpose, SuiteSpec
from gwent_evaluation.progress import advance
from gwent_evaluation.provenance import canonical_digest
from gwent_evaluation.records import decision_sample_to_dict, parse_record_mapping, record_to_dict
from gwent_evaluation.reporting import scored_cases
from gwent_evaluation.schedule import schedule_blocks, schedule_suite
from gwent_evaluation.storage import RunConflictError, RunStore, atomic_write_text
from gwent_evaluation.tuning.models import StudyMode, StudySpec
from gwent_evaluation.tuning.parameters import encode_parameters
from gwent_evaluation.validation import LoadedRun

SCORE_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class ObservationCase:
    case_id: str
    sample: DecisionSample

    def identity(self) -> dict[str, object]:
        payload = decision_sample_to_dict(self.sample)
        del payload["duration_seconds"]
        return {"case_id": self.case_id, "sample": payload}


@dataclass(frozen=True, slots=True)
class DecisionDiagnostic:
    """Production choice and scores; all-action scores are diagnostic only."""

    scores: tuple[tuple[str, float], ...]
    all_scores: tuple[tuple[str, float], ...]
    chosen_action: str
    override_reason: str | None
    legal_count: int
    retained_count: int
    shortlisted_count: int

    @property
    def best_action_omitted(self) -> bool:
        return bool(self.all_scores) and self.all_scores[0][0] not in dict(self.scores)


@dataclass(frozen=True, slots=True)
class ScoreGapWitness:
    first_action: str
    second_action: str
    reference_gap: float
    changed_gap: float


@dataclass(frozen=True, slots=True)
class DecisionDelta:
    relative_gap: ScoreGapWitness | None
    all_action_gap: ScoreGapWitness | None
    ranking_changed: bool
    all_action_ranking_changed: bool
    final_action_changed: bool


@dataclass(frozen=True, slots=True)
class SensitivityWitness:
    case_id: str
    sample_index: int
    observation_digest: str
    coordinate: float
    gap: ScoreGapWitness
    reference: DecisionDiagnostic
    changed: DecisionDiagnostic


@dataclass(frozen=True, slots=True)
class DimensionSensitivity:
    name: str
    observations: int
    relative_score_witnesses: int
    all_action_witnesses: int
    ranking_changes: int
    all_action_ranking_changes: int
    final_action_changes: int
    overridden_rank_changes: int
    best_action_omitted: int
    maximum_omitted_actions: int
    override_reasons: tuple[str, ...]
    witness: SensitivityWitness | None


@dataclass(frozen=True, slots=True)
class ControlResult:
    name: str
    configuration_digest: str
    execution_identity: str
    planned: int
    completed: int
    balanced_score: float | None
    block_scores: tuple[tuple[str, float | None], ...]
    changed_action_traces: int
    changed_match_outcomes: int
    changed_blocks: int


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    schema_version: int
    study_digest: str
    implementation_digest: str | None
    incumbent_digest: str
    parameter_space_digest: str
    suite_digests: tuple[str, ...]
    observations_digest: str
    observation_count: int
    dimensions: tuple[DimensionSensitivity, ...]
    controls: tuple[ControlResult, ...]
    planned_matches: int
    executed_matches: int
    match_execution_seconds: float
    disk_bytes: int
    reasons: tuple[str, ...]

    @property
    def status(self) -> str:
        return "insufficient_sensitivity" if self.reasons else "sufficient_sensitivity"

    def to_dict(self) -> dict[str, object]:
        payload = {**record_to_dict(self), "status": self.status}
        return {**payload, "report_digest": canonical_digest(payload)}

    @classmethod
    def from_dict(cls, value: object) -> SensitivityReport:
        """Decode a frozen report, checking its complete canonical representation."""
        raw = _report_mapping(value)
        payload = dict(raw)
        digest = payload.pop("report_digest", None)
        if canonical_digest(payload) != digest:
            raise SpecError("Sensitivity report digest mismatch.")
        dimensions = tuple(
            _dimension_from_dict(item) for item in _report_sequence(raw["dimensions"])
        )
        controls = tuple(_control_from_dict(item) for item in _report_sequence(raw["controls"]))
        report = cls(
            schema_version=_report_int(raw["schema_version"]),
            study_digest=_report_string(raw["study_digest"]),
            implementation_digest=None
            if raw["implementation_digest"] is None
            else _report_string(raw["implementation_digest"]),
            incumbent_digest=_report_string(raw["incumbent_digest"]),
            parameter_space_digest=_report_string(raw["parameter_space_digest"]),
            suite_digests=tuple(
                _report_string(item) for item in _report_sequence(raw["suite_digests"])
            ),
            observations_digest=_report_string(raw["observations_digest"]),
            observation_count=_report_int(raw["observation_count"]),
            dimensions=dimensions,
            controls=controls,
            planned_matches=_report_int(raw["planned_matches"]),
            executed_matches=_report_int(raw["executed_matches"]),
            match_execution_seconds=_report_float(raw["match_execution_seconds"]),
            disk_bytes=_report_int(raw["disk_bytes"]),
            reasons=tuple(_report_string(item) for item in _report_sequence(raw["reasons"])),
        )
        canonical = report.to_dict()
        del canonical["report_digest"]
        if canonical != payload:
            raise SpecError("Sensitivity report fields or digest differ from canonical evidence.")
        return report


def _report_mapping(value: object) -> Mapping[str, object]:
    return expect_mapping(value, context="sensitivity report", error_factory=SpecError)


def _report_sequence(value: object) -> tuple[object, ...]:
    return tuple(expect_sequence(value, context="sensitivity report", error_factory=SpecError))


def _report_string(value: object) -> str:
    return expect_str(value, context="sensitivity report", error_factory=SpecError)


def _report_int(value: object) -> int:
    return expect_int(value, context="sensitivity report", error_factory=SpecError)


def _report_float(value: object) -> float:
    return expect_finite_float(value, context="sensitivity report", error_factory=SpecError)


def _diagnostic_from_dict(value: object) -> DecisionDiagnostic:
    raw = _report_mapping(value)

    def scores(name: str) -> tuple[tuple[str, float], ...]:
        pairs = tuple(_report_sequence(item) for item in _report_sequence(raw[name]))
        if any(len(pair) != 2 for pair in pairs):
            raise SpecError("Sensitivity scores require action/value pairs.")
        return tuple((_report_string(pair[0]), _report_float(pair[1])) for pair in pairs)

    return DecisionDiagnostic(
        scores("scores"),
        scores("all_scores"),
        _report_string(raw["chosen_action"]),
        None if raw["override_reason"] is None else _report_string(raw["override_reason"]),
        _report_int(raw["legal_count"]),
        _report_int(raw["retained_count"]),
        _report_int(raw["shortlisted_count"]),
    )


def _dimension_from_dict(value: object) -> DimensionSensitivity:
    raw = _report_mapping(value)
    witness = None
    if raw["witness"] is not None:
        item = _report_mapping(raw["witness"])
        gap = _report_mapping(item["gap"])
        witness = SensitivityWitness(
            _report_string(item["case_id"]),
            _report_int(item["sample_index"]),
            _report_string(item["observation_digest"]),
            _report_float(item["coordinate"]),
            ScoreGapWitness(
                _report_string(gap["first_action"]),
                _report_string(gap["second_action"]),
                _report_float(gap["reference_gap"]),
                _report_float(gap["changed_gap"]),
            ),
            _diagnostic_from_dict(item["reference"]),
            _diagnostic_from_dict(item["changed"]),
        )
    return DimensionSensitivity(
        _report_string(raw["name"]),
        _report_int(raw["observations"]),
        _report_int(raw["relative_score_witnesses"]),
        _report_int(raw["all_action_witnesses"]),
        _report_int(raw["ranking_changes"]),
        _report_int(raw["all_action_ranking_changes"]),
        _report_int(raw["final_action_changes"]),
        _report_int(raw["overridden_rank_changes"]),
        _report_int(raw["best_action_omitted"]),
        _report_int(raw["maximum_omitted_actions"]),
        tuple(_report_string(item) for item in _report_sequence(raw["override_reasons"])),
        witness,
    )


def _control_from_dict(value: object) -> ControlResult:
    raw = _report_mapping(value)
    pairs = tuple(_report_sequence(item) for item in _report_sequence(raw["block_scores"]))
    if any(len(pair) != 2 for pair in pairs):
        raise SpecError("Sensitivity blocks require identity/score pairs.")
    return ControlResult(
        _report_string(raw["name"]),
        _report_string(raw["configuration_digest"]),
        _report_string(raw["execution_identity"]),
        _report_int(raw["planned"]),
        _report_int(raw["completed"]),
        None if raw["balanced_score"] is None else _report_float(raw["balanced_score"]),
        tuple(
            (_report_string(pair[0]), None if pair[1] is None else _report_float(pair[1]))
            for pair in pairs
        ),
        _report_int(raw["changed_action_traces"]),
        _report_int(raw["changed_match_outcomes"]),
        _report_int(raw["changed_blocks"]),
    )


def diagnose_decision(
    sample: DecisionSample,
    configuration: HeuristicConfiguration,
    assets: ResolvedAssets,
) -> DecisionDiagnostic:
    if sample.kind is not MatchDecisionKind.ACTION or sample.failure is not None:
        raise SpecError("Sensitivity requires successful ordinary action observations.")
    plan = build_decision_plan(
        sample.observation,
        tuple(action_from_id(value) for value in sample.legal_option_ids),
        card_registry=assets.card_registry,
        leader_registry=assets.leader_registry,
        config=configuration.baseline,
        profile_definition=configuration.profile,
    )
    # Counterfactual scoring diagnoses pruning. It never feeds the production choice.
    all_scores = explain_ranked_actions(
        plan.candidate_actions,
        observation=plan.observation,
        assessment=plan.assessment,
        context=plan.context,
        profile=plan.profile,
        card_registry=assets.card_registry,
        leader_registry=assets.leader_registry,
        viewer_hand_definitions=plan.viewer_hand_definitions,
    )
    return DecisionDiagnostic(
        scores=tuple((action_to_id(item.action), item.total) for item in plan.ranked_actions),
        all_scores=tuple((action_to_id(item.action), item.total) for item in all_scores),
        chosen_action=action_to_id(plan.chosen_action),
        override_reason=None if plan.override is None else plan.override.reason,
        legal_count=len(plan.candidate_actions),
        retained_count=len(plan.candidates),
        shortlisted_count=len(plan.shortlisted_actions),
    )


def _relative_gap(
    reference: tuple[tuple[str, float], ...], changed: tuple[tuple[str, float], ...]
) -> ScoreGapWitness | None:
    before, after = dict(reference), dict(changed)
    common = sorted(before.keys() & after.keys())
    if len(common) < 2:
        return None
    deltas = {key: after[key] - before[key] for key in common}
    first = max(common, key=deltas.__getitem__)
    second = min(common, key=deltas.__getitem__)
    if deltas[first] - deltas[second] <= SCORE_TOLERANCE:
        return None
    return ScoreGapWitness(
        first, second, before[first] - before[second], after[first] - after[second]
    )


def compare_decisions(reference: DecisionDiagnostic, changed: DecisionDiagnostic) -> DecisionDelta:
    return DecisionDelta(
        relative_gap=_relative_gap(reference.scores, changed.scores),
        all_action_gap=_relative_gap(reference.all_scores, changed.all_scores),
        ranking_changed=tuple(key for key, _ in reference.scores)
        != tuple(key for key, _ in changed.scores),
        all_action_ranking_changed=tuple(key for key, _ in reference.all_scores)
        != tuple(key for key, _ in changed.all_scores),
        final_action_changed=reference.chosen_action != changed.chosen_action,
    )


def measure_dimensions(
    study: StudySpec, observations: tuple[ObservationCase, ...], assets: ResolvedAssets
) -> tuple[DimensionSensitivity, ...]:
    default = encode_parameters(
        study.parameter_space, study.incumbent, frozen_configuration=study.incumbent
    )
    references = tuple(
        diagnose_decision(item.sample, study.incumbent, assets) for item in observations
    )
    if any(
        reference.chosen_action != case.sample.chosen_option_id
        for case, reference in zip(observations, references, strict=True)
    ):
        raise SpecError("Incumbent diagnostics differ from the recorded production action.")
    dimensions: list[DimensionSensitivity] = []
    for index, parameter in enumerate(study.parameter_space.parameters):
        live: set[int] = set()
        all_live: set[int] = set()
        ranked: set[int] = set()
        all_ranked: set[int] = set()
        changed_actions: set[int] = set()
        overridden: set[int] = set()
        omitted: set[int] = set()
        reasons: set[str] = set()
        max_omitted = 0
        witness = None
        for coordinate in (0.0, 1.0):
            vector = (*default[:index], coordinate, *default[index + 1 :])
            configuration = study.bind(vector)
            for sample_index, (case, reference) in enumerate(
                zip(observations, references, strict=True)
            ):
                changed = diagnose_decision(case.sample, configuration, assets)
                delta = compare_decisions(reference, changed)
                if delta.relative_gap is not None:
                    live.add(sample_index)
                    if witness is None:
                        witness = SensitivityWitness(
                            case.case_id,
                            case.sample.index,
                            canonical_digest(case.identity()),
                            coordinate,
                            delta.relative_gap,
                            reference,
                            changed,
                        )
                if delta.all_action_gap is not None:
                    all_live.add(sample_index)
                if delta.ranking_changed:
                    ranked.add(sample_index)
                if delta.all_action_ranking_changed:
                    all_ranked.add(sample_index)
                if delta.final_action_changed:
                    changed_actions.add(sample_index)
                if (
                    delta.ranking_changed
                    and not delta.final_action_changed
                    and changed.override_reason is not None
                ):
                    overridden.add(sample_index)
                for decision in (reference, changed):
                    if decision.override_reason is not None:
                        reasons.add(decision.override_reason)
                    if decision.best_action_omitted:
                        omitted.add(sample_index)
                    max_omitted = max(
                        max_omitted, decision.legal_count - decision.shortlisted_count
                    )
        dimensions.append(
            DimensionSensitivity(
                parameter.name,
                len(observations),
                len(live),
                len(all_live),
                len(ranked),
                len(all_ranked),
                len(changed_actions),
                len(overridden),
                len(omitted),
                max_omitted,
                tuple(sorted(reasons)),
                witness,
            )
        )
    return tuple(dimensions)


def sensitivity_controls(study: StudySpec) -> tuple[tuple[str, HeuristicConfiguration], ...]:
    """Protocol 1: incumbent and two endpoints, fixed before any outcomes exist."""
    size = len(study.parameter_space.parameters)
    return (
        ("incumbent", study.incumbent),
        ("lower-bounds", study.bind((0.0,) * size)),
        ("upper-bounds", study.bind((1.0,) * size)),
    )


def sensitivity_suite(study: StudySpec) -> SuiteSpec:
    suite = replace(
        study.optimization.suite,
        suite_id=f"{study.optimization.suite.suite_id}-sensitivity",
        purpose=SuitePurpose.DIAGNOSTIC,
        seeds=study.sensitivity.pilot_seeds,
    )
    planned = len(schedule_suite(suite)) * len(sensitivity_controls(study))
    if planned > study.sensitivity.max_pilot_matches:
        raise SpecError(f"Sensitivity panel requires {planned} matches, exceeding its pilot cap.")
    return suite


def sample_observations(run: LoadedRun, limit: int) -> tuple[ObservationCase, ...]:
    observations: list[ObservationCase] = []
    for match in run.matches:
        samples = tuple(
            sample
            for sample in run.samples[match.case_id]
            if sample.actor == match.candidate_seat
            and sample.kind is MatchDecisionKind.ACTION
            and sample.failure is None
        )
        # Spread a bounded deterministic sample through each match, including its end.
        count = min(limit, len(samples))
        indices = (
            (0,)
            if count == 1
            else tuple(index * (len(samples) - 1) // (count - 1) for index in range(count))
        )
        observations.extend(ObservationCase(match.case_id, samples[index]) for index in indices)
    return tuple(observations)


def _control_result(
    name: str, run: LoadedRun, reference: LoadedRun, study: StudySpec
) -> ControlResult:
    cases = scored_cases(schedule_blocks(run.manifest.suite), run.results)
    baseline_cases = scored_cases(schedule_blocks(reference.manifest.suite), reference.results)
    metrics = compute_run_metrics(cases, bootstrap=study.bootstrap)
    blocks = block_outcomes(cases)
    baseline_blocks = {block.block_id: block.mean_score for block in block_outcomes(baseline_cases)}
    changed_traces = 0
    changed_outcomes = 0
    for match in reference.matches:
        before, after = reference.results.get(match.case_id), run.results.get(match.case_id)
        if before is None or after is None:
            continue
        before_trace = tuple(
            (sample.actor, sample.kind, sample.chosen_option_id)
            for sample in reference.samples[match.case_id]
        )
        after_trace = tuple(
            (sample.actor, sample.kind, sample.chosen_option_id)
            for sample in run.samples[match.case_id]
        )
        changed_traces += before_trace != after_trace
        changed_outcomes += before.candidate_score != after.candidate_score
    return ControlResult(
        name,
        run.manifest.candidate.digest,
        run.execution_identity,
        metrics.planned,
        metrics.completed,
        metrics.balanced_score,
        tuple((block.block_id, block.mean_score) for block in blocks),
        changed_traces,
        changed_outcomes,
        sum(block.mean_score != baseline_blocks[block.block_id] for block in blocks),
    )


def _sensitivity_reasons(
    study: StudySpec,
    dimensions: tuple[DimensionSensitivity, ...],
    controls: tuple[ControlResult, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if tuple(item.name for item in dimensions) != tuple(
        item.name for item in study.parameter_space.parameters
    ):
        reasons.append("Parameter evidence does not cover the complete declared space.")
    for dimension in dimensions:
        if dimension.relative_score_witnesses < study.sensitivity.minimum_relative_score_witnesses:
            reasons.append(
                f"{dimension.name}: insufficient relative-score sensitivity on shortlisted actions."
            )
    if (
        sum(item.final_action_changes for item in dimensions)
        < study.sensitivity.minimum_changed_actions
    ):
        reasons.append("No sufficient final-action variation across in-range parameter controls.")
    expected = tuple(
        (
            name,
            resolve_agent(
                replace(study.optimization.suite.candidate, heuristic_configuration=configuration)
            ).digest(),
        )
        for name, configuration in sensitivity_controls(study)
    )
    if tuple((item.name, item.configuration_digest) for item in controls) != expected:
        reasons.append("Control panel differs from the prespecified configurations.")
    planned_per_control = len(schedule_suite(sensitivity_suite(study)))
    if not controls or any(
        item.completed != item.planned or item.planned != planned_per_control for item in controls
    ):
        reasons.append("Control panel does not contain complete match evidence.")
    if (
        sum(item.changed_match_outcomes for item in controls)
        < study.sensitivity.minimum_changed_outcomes
    ):
        reasons.append("No sufficient match-outcome variation in the control panel.")
    return tuple(reasons)


def require_sensitivity(study: StudySpec, report: SensitivityReport) -> None:
    """Fail closed before scientific optimization; adequacy is not policy improvement."""
    if report.schema_version != 1 or report.study_digest != study.digest():
        raise SpecError("Sensitivity evidence belongs to a different study or implementation.")
    reasons = _sensitivity_reasons(study, report.dimensions, report.controls)
    if reasons or report.reasons:
        raise SpecError("insufficient_sensitivity: " + "; ".join(reasons or report.reasons))
    if (
        study.mode is not StudyMode.SCIENTIFIC
        or not study.optimization.repository.is_clean_checkout
    ):
        raise SpecError(
            "Scientific optimization requires sensitivity evidence from a clean scientific study."
        )


def run_sensitivity(
    study: StudySpec, *, output_root: Path, repository_root: Path
) -> SensitivityReport:
    suite = sensitivity_suite(study)
    assets = resolve_assets()
    validate_run_environment(study.optimization, repository_root=repository_root)
    snapshot = record_to_dict(study)
    snapshot_path = output_root / "snapshot.json"
    if snapshot_path.exists():
        if (
            parse_record_mapping(
                snapshot_path.read_text(encoding="utf-8"), context=str(snapshot_path)
            )
            != snapshot
        ):
            raise RunConflictError("Sensitivity directory belongs to a different frozen study.")
    else:
        atomic_write_text(snapshot_path, dump_pretty_json(snapshot))
    runs: list[tuple[str, LoadedRun]] = []
    executed = 0
    for name, configuration in sensitivity_controls(study):
        candidate = replace(suite.candidate, heuristic_configuration=configuration)
        run = execute_run(
            suite=replace(suite, candidate=candidate),
            run_id=name,
            output_root=output_root / "runs",
            repository_root=repository_root,
            evidence_policy=EvidencePolicy.FAILURES,
        )
        executed += len(run.executed_case_ids)
        store = RunStore.from_root(run.root)
        loaded = store.load(sample_cases=tuple(item.case_id for item in run.results))
        if (loaded.manifest.repository, loaded.manifest.runtime, loaded.manifest.assets) != (
            study.optimization.repository,
            study.optimization.runtime,
            study.optimization.assets,
        ):
            raise RunConflictError("Sensitivity run provenance differs from the frozen study.")
        runs.append((name, loaded))
        if any(item.termination.value != "completed" for item in run.results):
            break
    advance("checking relative action scores and control outcomes")
    incumbent = runs[0][1]
    observations = sample_observations(incumbent, study.sensitivity.observations_per_match)
    dimensions = measure_dimensions(study, observations, assets)
    controls = tuple(_control_result(name, run, incumbent, study) for name, run in runs)
    validate_run_environment(study.optimization, repository_root=repository_root)
    report = SensitivityReport(
        schema_version=1,
        study_digest=study.digest(),
        implementation_digest=study.optimization.repository.implementation_digest,
        incumbent_digest=study.incumbent.digest(),
        parameter_space_digest=study.parameter_space.digest(),
        suite_digests=tuple(
            canonical_digest(manifest.suite)
            for manifest in (study.optimization, study.validation, study.test)
        ),
        observations_digest=canonical_digest(tuple(item.identity() for item in observations)),
        observation_count=len(observations),
        dimensions=dimensions,
        controls=controls,
        planned_matches=len(schedule_suite(suite)) * len(sensitivity_controls(study)),
        executed_matches=executed,
        match_execution_seconds=sum(
            result.execution_seconds for _, run in runs for result in run.results.values()
        ),
        disk_bytes=sum(
            path.stat().st_size for path in (output_root / "runs").rglob("*") if path.is_file()
        ),
        reasons=_sensitivity_reasons(study, dimensions, controls),
    )
    atomic_write_text(output_root / "report.json", dump_pretty_json(report.to_dict()))
    return report
