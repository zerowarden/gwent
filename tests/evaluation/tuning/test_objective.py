"""Synthetic arithmetic and tiny complete matches for the objective boundary."""

from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest
from gwent_engine.ai.arena.models import MatchFailure, MatchFailureStage
from gwent_evaluation import execution
from gwent_evaluation.agents import ResolvedAgent, resolve_agent
from gwent_evaluation.assets import ResolvedAssets, resolve_assets
from gwent_evaluation.execution import RunExecution
from gwent_evaluation.models import (
    RECORD_SCHEMA_VERSION,
    EvidenceRefs,
    MatchResult,
    RunManifest,
    ScheduledMatch,
    SpecError,
    SuitePurpose,
    TerminationReason,
)
from gwent_evaluation.provenance import RepositoryProvenance, RuntimeProvenance, canonical_digest
from gwent_evaluation.records import CorruptRecordError
from gwent_evaluation.replay import ReplayError, replay_case, reproduce_case
from gwent_evaluation.schedule import other_seat, schedule_blocks, schedule_suite
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning import objective
from gwent_evaluation.tuning.models import StudyMode, StudySpec
from gwent_evaluation.tuning.objective import (
    TrialReason,
    TrialStatus,
    candidate_evaluation_identity,
    evaluate_candidate,
    load_trial_evaluation,
)
from gwent_evaluation.tuning.sensitivity import (
    ControlResult,
    DimensionSensitivity,
    SensitivityReport,
    sensitivity_controls,
    sensitivity_suite,
)
from gwent_evaluation.validation import execution_identity

from tests.evaluation.support import (
    DECK_A,
    DECK_B,
    REPOSITORY_ROOT,
    read_json_object,
    write_json_object,
)

pytestmark = pytest.mark.allow_match_execution


def no_games(*_args: object, **_kwargs: object) -> NoReturn:
    pytest.fail("This check must reject or reuse evidence without playing matches")


@pytest.fixture
def scientific(study: StudySpec, monkeypatch: pytest.MonkeyPatch) -> StudySpec:
    """Synthetic clean provenance and mixed block sizes; never a real scientific suite."""
    repository = replace(study.optimization.repository, dirty=False)

    def clean_repository(_root: Path) -> RepositoryProvenance:
        return repository

    monkeypatch.setattr(execution, "read_repository_provenance", clean_repository)
    monkeypatch.setattr(execution, "execute_case", no_games)
    assets = resolve_assets()
    manifests: list[RunManifest] = []
    for manifest, purpose in zip(
        (study.optimization, study.validation, study.test),
        (SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST),
        strict=True,
    ):
        suite = replace(
            manifest.suite, purpose=purpose, deck_pairs=((DECK_A, DECK_A), (DECK_A, DECK_B))
        )
        manifests.append(
            execution.build_run_manifest(
                suite=suite,
                run_id=manifest.run_id,
                matches=schedule_suite(suite),
                candidate=resolve_agent(suite.candidate),
                opponents=tuple(resolve_agent(item) for item in suite.opponents),
                assets=assets,
                repository_root=REPOSITORY_ROOT,
            )
        )
    return replace(
        study,
        mode=StudyMode.SCIENTIFIC,
        optimization=manifests[0],
        validation=manifests[1],
        test=manifests[2],
        evaluation_match_budget=120,
        sensitivity=replace(study.sensitivity, max_pilot_matches=36),
    )


@pytest.fixture
def preflight(scientific: StudySpec) -> SensitivityReport:
    """Hand-authored positive preflight for arithmetic fixtures, not measured evidence."""
    planned = len(schedule_suite(sensitivity_suite(scientific)))
    return SensitivityReport(
        schema_version=1,
        study_digest=scientific.digest(),
        implementation_digest=scientific.optimization.repository.implementation_digest,
        incumbent_digest=scientific.incumbent.digest(),
        parameter_space_digest=scientific.parameter_space.digest(),
        suite_digests=tuple(
            canonical_digest(manifest.suite)
            for manifest in (scientific.optimization, scientific.validation, scientific.test)
        ),
        observations_digest="synthetic-observations",
        observation_count=1,
        dimensions=tuple(
            DimensionSensitivity(item.name, 1, 1, 1, 1, 1, 1, 0, 0, 0, (), None)
            for item in scientific.parameter_space.parameters
        ),
        controls=tuple(
            ControlResult(
                name,
                resolve_agent(
                    replace(
                        scientific.optimization.suite.candidate,
                        heuristic_configuration=configuration,
                    )
                ).digest(),
                f"synthetic-{name}",
                planned,
                planned,
                0.5,
                (),
                int(name != "incumbent"),
                int(name != "incumbent"),
                int(name != "incumbent"),
            )
            for name, configuration in sensitivity_controls(scientific)
        ),
        planned_matches=planned * 3,
        executed_matches=0,
        match_execution_seconds=0,
        disk_bytes=0,
        reasons=(),
    )


def completed_result(match: ScheduledMatch, manifest: RunManifest, score: float) -> MatchResult:
    winner = None
    if score == 1:
        winner = match.candidate_seat
    elif score == 0:
        winner = other_seat(match.candidate_seat)
    return MatchResult(
        schema_version=RECORD_SCHEMA_VERSION,
        case_id=match.case_id,
        termination=TerminationReason.COMPLETED,
        candidate_agent_id=match.candidate_agent.agent_id,
        opponent_agent_id=match.opponent_agent.agent_id,
        candidate_seat=match.candidate_seat,
        requested_starting_player=match.requested_starting_player,
        actual_starting_player=match.requested_starting_player,
        winner=winner,
        candidate_score=score,
        accepted_transitions=1,
        decision_count=0,
        pending_choice_occurred=False,
        observation_contract_version=manifest.suite.observation_contract_version,
        semantic_digest="synthetic-semantic-digest",
        decision_seconds=0,
        execution_seconds=0,
        environment_seed=match.environment_seed,
        evidence=EvidenceRefs(),
        execution_identity=execution_identity(manifest),
        final_state_digest="synthetic-final-state",
    )


@pytest.fixture
def completed_store(scientific: StudySpec, tmp_path: Path) -> RunStore:
    manifest = replace(scientific.optimization, run_id="arithmetic")
    store = RunStore(tmp_path, manifest.run_id)
    _ = store.prepare(manifest, matches=schedule_suite(manifest.suite))
    scores_by_size = {4: (1.0, 0.5, 0.0, 0.0), 8: (1.0,) * 6 + (0.5, 0.5)}
    for block in schedule_blocks(manifest.suite):
        for match, score in zip(block.matches, scores_by_size[len(block.matches)], strict=True):
            store.write_result(completed_result(match, manifest, score))
    return store


def test_balanced_fitness_uses_equal_blocks_and_verified_result_references(
    scientific: StudySpec, preflight: SensitivityReport, completed_store: RunStore
) -> None:
    trial = load_trial_evaluation(
        scientific,
        scientific.incumbent,
        run_root=completed_store.root,
        sensitivity_report=preflight,
    )
    # Four-leg mean 0.375 and eight-leg mean 0.875: equal blocks give 0.625.
    assert trial.score == 0.625
    assert trial.fitness == 0.375
    assert trial.status is TrialStatus.ELIGIBLE
    assert trial.reasons == ()
    assert trial.planned == trial.completed == len(trial.results) == 12
    assert trial.failed == trial.missing == 0
    assert trial.valid_for_comparison and trial.optimization_evidence
    assert trial.to_dict()["fitness"] == 0.375
    for reference in trial.results:
        record = read_json_object(completed_store.root / reference.path)
        assert reference.record_digest == record["record_digest"]
    resumed = evaluate_candidate(
        scientific,
        scientific.incumbent,
        run_id=completed_store.run_id,
        output_root=completed_store.output_root,
        sensitivity_report=preflight,
    )
    assert resumed == trial


@pytest.mark.parametrize("termination", [None, *tuple(TerminationReason)[1:]])
def test_missing_or_failed_matches_never_supply_fitness(
    scientific: StudySpec,
    preflight: SensitivityReport,
    completed_store: RunStore,
    termination: TerminationReason | None,
) -> None:
    loaded = completed_store.load()
    match = loaded.matches[0]
    original = loaded.results[match.case_id]
    if termination is None:
        completed_store.result_path(match.case_id).unlink()
    else:
        failure = None
        if termination is not TerminationReason.ACTION_LIMIT:
            failure = MatchFailure(MatchFailureStage.REDUCE, match.candidate_seat, "Fault", "test")
        completed_store.write_result(
            replace(
                original,
                termination=termination,
                winner=None,
                candidate_score=None,
                failure=failure,
                accepted_transitions=match.action_budget,
            )
        )
    trial = load_trial_evaluation(
        scientific,
        scientific.incumbent,
        run_root=completed_store.root,
        sensitivity_report=preflight,
    )
    assert trial.fitness is None
    assert not trial.valid_for_comparison and not trial.optimization_evidence
    assert trial.completed == 11
    if termination is None:
        assert trial.status is TrialStatus.INCOMPLETE
        assert trial.missing == 1 and trial.failed == 0
        assert trial.reasons == (TrialReason.MISSING_RESULTS,)
    else:
        assert trial.status is TrialStatus.FAILED
        assert trial.failed == 1 and trial.missing == 0
        assert trial.reasons == (TrialReason.MATCH_FAILURE,)


def test_smoke_trials_keep_diagnostic_scores_pairings_and_separate_rich_reproductions(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = study.bind((0.5,) * 11)
    first = evaluate_candidate(study, configuration, run_id="first", output_root=tmp_path)
    second = evaluate_candidate(study, configuration, run_id="renamed", output_root=tmp_path)
    assert first.planned == first.completed == 4
    assert first.status is TrialStatus.DIAGNOSTIC_ONLY
    assert first.reasons == (TrialReason.DIAGNOSTIC_PROVENANCE,)
    assert first.score is not None and first.fitness is None
    assert first.valid_for_comparison and not first.optimization_evidence
    assert first.candidate_digest == second.candidate_digest
    assert first.configuration_digest == second.configuration_digest == configuration.digest()
    assert candidate_evaluation_identity(study, configuration) == first.identity
    assert first.benchmark_identity == second.benchmark_identity
    assert first.execution_identity == second.execution_identity
    assert [r.semantic_digest for r in first.results] == [r.semantic_digest for r in second.results]
    store = RunStore.from_root(Path(first.run_root))
    assert not tuple(store.evidence_dir.iterdir())
    loaded = store.load()
    for actual, pinned in zip(
        loaded.matches, schedule_suite(study.optimization.suite), strict=True
    ):
        assert replace(actual, candidate_agent=pinned.candidate_agent) == pinned

    before = {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    diagnostic_root = tmp_path / "diagnostic"
    reference = first.results[0]
    reproduction = reproduce_case(store.root, reference.case_id, diagnostic_root=diagnostic_root)
    assert reproduction.execution_identity_matches and reproduction.semantics_reproduced
    assert replay_case(diagnostic_root, reference.case_id).reproduced
    diagnostic = RunStore.from_root(diagnostic_root)
    result = diagnostic.load().results.get(reference.case_id)
    assert result is not None
    assert result.semantic_digest == reference.semantic_digest
    assert result.evidence.samples_path and result.evidence.trajectory_path
    link = read_json_object(diagnostic_root / "reproduction.json")
    assert link["source_execution_identity"] == first.execution_identity
    assert link["source_result_digest"] == reference.record_digest
    assert link["source_case_id"] == reference.case_id
    assert before == {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    for destination in (store.root, store.root / "diagnostic", diagnostic_root):
        with pytest.raises(ReplayError, match="new directory"):
            _ = reproduce_case(store.root, reference.case_id, diagnostic_root=destination)

    monkeypatch.setattr(execution, "execute_case", no_games)
    assert first.fresh_matches == 4
    assert evaluate_candidate(
        study, configuration, run_id="first", output_root=tmp_path
    ) == replace(first, fresh_matches=0)
    store.result_path(reference.case_id).unlink()
    incomplete = load_trial_evaluation(study, configuration, run_root=store.root)
    assert incomplete.status is TrialStatus.INCOMPLETE
    assert incomplete.fitness is None


@pytest.mark.parametrize("change", ["opponent", "assets", "budget", "implementation", "runtime"])
def test_changed_execution_conditions_reject_new_trials_and_persisted_reuse(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    original = replace(study.optimization, run_id="drift")
    alternatives = {
        "opponent": replace(
            original, opponents=(replace(original.opponents[0], digest="changed"),)
        ),
        "assets": replace(original, assets=replace(original.assets, card_data_digest="changed")),
        "budget": replace(original, suite=replace(original.suite, action_budget=1)),
        "implementation": replace(
            original, repository=replace(original.repository, implementation_digest="changed")
        ),
        "runtime": replace(original, runtime=replace(original.runtime, python_version="changed")),
    }
    changed = alternatives[change]
    changed = replace(
        changed, planned_case_ids=tuple(match.case_id for match in schedule_suite(changed.suite))
    )

    def changed_manifest(**_kwargs: object) -> RunManifest:
        return changed

    monkeypatch.setattr(execution, "build_run_manifest", changed_manifest)
    monkeypatch.setattr(execution, "execute_case", no_games)
    with pytest.raises(RunConflictError, match="pinned manifest"):
        _ = evaluate_candidate(study, study.incumbent, run_id="drift", output_root=tmp_path)
    assert not (tmp_path / "drift").exists()
    store = RunStore(tmp_path, "drift")
    _ = store.prepare(changed, matches=schedule_suite(changed.suite))
    with pytest.raises(RunConflictError, match="frozen study"):
        _ = load_trial_evaluation(study, study.incumbent, run_root=store.root)


def test_environment_is_rechecked_after_match_execution(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run_then_drift(**_kwargs: object) -> RunExecution:
        run = execution.execute_run(
            suite=study.optimization.suite,
            run_id="post-drift",
            output_root=tmp_path,
            repository_root=REPOSITORY_ROOT,
            evidence_policy=execution.EvidencePolicy.NONE,
        )

        def changed_runtime() -> RuntimeProvenance:
            return replace(study.optimization.runtime, python_version="changed")

        monkeypatch.setattr(execution, "read_runtime_provenance", changed_runtime)
        return run

    monkeypatch.setattr(objective, "execute_run", run_then_drift)
    with pytest.raises(RunConflictError, match="pinned manifest"):
        _ = evaluate_candidate(study, study.incumbent, run_id="post-drift", output_root=tmp_path)


@pytest.mark.parametrize("change", ["bounds", "frozen"])
def test_invalid_candidate_executes_zero_matches(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    baseline = study.incumbent.baseline
    if change == "bounds":
        baseline = replace(baseline, weights=replace(baseline.weights, immediate_points=99))
    else:
        baseline = replace(baseline, candidates=replace(baseline.candidates, max_candidates=1))
    configuration = replace(study.incumbent, baseline=baseline)
    monkeypatch.setattr(execution, "execute_case", no_games)
    with pytest.raises(SpecError):
        _ = evaluate_candidate(study, configuration, run_id="invalid", output_root=tmp_path)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("kind", ["absent", "stale", "insufficient"])
def test_scientific_trials_require_matching_sufficient_preflight_before_games(
    scientific: StudySpec, preflight: SensitivityReport, tmp_path: Path, kind: str
) -> None:
    reports = {
        "absent": None,
        "stale": replace(preflight, study_digest="another-study"),
        "insufficient": replace(preflight, dimensions=()),
    }
    with pytest.raises(SpecError):
        _ = evaluate_candidate(
            scientific,
            scientific.incumbent,
            run_id="blocked",
            output_root=tmp_path,
            sensitivity_report=reports[kind],
        )
    assert not (tmp_path / "blocked").exists()


def test_corrupt_evidence_and_another_candidate_are_hard_conflicts(
    scientific: StudySpec, preflight: SensitivityReport, completed_store: RunStore
) -> None:
    with pytest.raises(RunConflictError, match="candidate"):
        _ = load_trial_evaluation(
            scientific,
            scientific.bind((0.5,) * 11),
            run_root=completed_store.root,
            sensitivity_report=preflight,
        )
    case_id = completed_store.read_manifest().planned_case_ids[0]
    path = completed_store.result_path(case_id)
    write_json_object(path, {**read_json_object(path), "semantic_digest": "changed"})
    with pytest.raises(CorruptRecordError):
        _ = load_trial_evaluation(
            scientific,
            scientific.incumbent,
            run_root=completed_store.root,
            sensitivity_report=preflight,
        )


def test_bulk_evidence_policy_must_be_declared_as_summary(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "execute_case", no_games)
    rich = replace(study, evidence_policy=execution.EvidencePolicy.ALL)
    with pytest.raises(SpecError, match="summary recording"):
        _ = evaluate_candidate(rich, rich.incumbent, run_id="invalid", output_root=tmp_path)
    assert not (tmp_path / "invalid").exists()


def test_interruption_resumes_only_missing_cases(
    study: StudySpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute_case = execution.execute_case
    calls: list[str] = []
    interrupt = True

    def tracked_case(
        match: ScheduledMatch,
        *,
        candidate: ResolvedAgent,
        opponent: ResolvedAgent,
        assets: ResolvedAssets,
        collect_evidence: bool = True,
    ) -> execution.CaseExecution:
        calls.append(match.case_id)
        if interrupt and len(calls) == 2:
            raise InterruptedError("simulated interruption")
        return execute_case(
            match,
            candidate=candidate,
            opponent=opponent,
            assets=assets,
            collect_evidence=collect_evidence,
        )

    monkeypatch.setattr(execution, "execute_case", tracked_case)
    with pytest.raises(InterruptedError):
        _ = evaluate_candidate(study, study.incumbent, run_id="interrupted", output_root=tmp_path)
    store = RunStore(tmp_path, "interrupted")
    incomplete = load_trial_evaluation(study, study.incumbent, run_root=store.root)
    assert incomplete.status is TrialStatus.INCOMPLETE
    assert incomplete.completed == 1 and incomplete.missing == 3
    assert incomplete.failed == 0 and incomplete.fitness is None
    committed = store.result_path(incomplete.results[0].case_id)
    original_bytes = committed.read_bytes()
    interrupt = False
    calls.clear()
    resumed = evaluate_candidate(study, study.incumbent, run_id="interrupted", output_root=tmp_path)
    assert resumed.completed == 4 and resumed.missing == 0
    assert resumed.fresh_matches == 3
    assert len(calls) == 3 and incomplete.results[0].case_id not in calls
    assert committed.read_bytes() == original_bytes


def test_failed_trial_can_be_diagnosed_without_replacing_its_failure(
    study: StudySpec,
    tmp_path: Path,
) -> None:
    manifests: list[RunManifest] = []
    for manifest in (study.optimization, study.validation, study.test):
        suite = replace(manifest.suite, action_budget=1)
        manifests.append(
            replace(
                manifest,
                suite=suite,
                planned_case_ids=tuple(match.case_id for match in schedule_suite(suite)),
            )
        )
    truncated = replace(
        study,
        optimization=manifests[0],
        validation=manifests[1],
        test=manifests[2],
    )
    trial = evaluate_candidate(
        truncated, truncated.incumbent, run_id="failed", output_root=tmp_path
    )
    assert trial.status is TrialStatus.FAILED and trial.fitness is None
    assert trial.failed == 4 and trial.completed == 0
    source = RunStore.from_root(Path(trial.run_root))
    reference = trial.results[0]
    before = source.result_path(reference.case_id).read_bytes()
    diagnostic_root = tmp_path / "failed-diagnostic"
    outcome = reproduce_case(source.root, reference.case_id, diagnostic_root=diagnostic_root)
    assert outcome.termination is TerminationReason.ACTION_LIMIT
    assert outcome.execution_identity_matches and outcome.semantics_reproduced
    assert replay_case(diagnostic_root, reference.case_id).prefix_verified
    assert source.result_path(reference.case_id).read_bytes() == before
    source.result_path(trial.results[1].case_id).unlink()
    partial = load_trial_evaluation(truncated, truncated.incumbent, run_root=source.root)
    assert partial.status is TrialStatus.FAILED
    assert partial.failed == 3 and partial.missing == 1
    assert TrialReason.MATCH_FAILURE in partial.reasons
    assert TrialReason.MISSING_RESULTS in partial.reasons
