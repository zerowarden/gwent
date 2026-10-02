"""Integrated acceptance on synthetic benchmark identities, never registered holdouts."""

from dataclasses import replace
from pathlib import Path

import pytest
from gwent_engine.ai.arena.catalog import load_policy_bot
from gwent_engine.ai.baseline.bot import HeuristicBot
from gwent_engine.ai.baseline.policy_artifacts import PolicyArtifact, PolicyStatus
from gwent_evaluation import execution
from gwent_evaluation.agents import candidate_from_artifact
from gwent_evaluation.execution import EvidencePolicy, execute_case, execute_run
from gwent_evaluation.models import MatchResult, SpecError, SuitePurpose
from gwent_evaluation.replay import reproduce_case
from gwent_evaluation.storage import RunStore
from gwent_evaluation.tuning.models import OptimizerMethod, StudySpec
from gwent_evaluation.tuning.selection import finalize_study, select_challenger
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.study import StudyResult, run_study

from tests.engine.ai.support import verified_decision_plan
from tests.evaluation.support import REPOSITORY_ROOT
from tests.evaluation.tuning.test_selection import Experiment
from tests.evaluation.tuning.test_selection import experiment as experiment
from tests.evaluation.tuning.test_selection import preflight as preflight
from tests.evaluation.tuning.test_selection import scientific as scientific

pytestmark = pytest.mark.allow_match_execution


def test_actual_optimizers_recover_then_select_identically(
    scientific: StudySpec,
    preflight: SensitivityReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only provenance/preflight are synthetic. Both proposal backends, the engine,
    # match storage, fitness, selection, and recovery execute normally.
    monkeypatch.setattr(execution, "execute_case", execute_case)

    def run(root: Path) -> StudyResult:
        return run_study(
            scientific,
            output_root=root,
            repository_root=REPOSITORY_ROOT,
            sensitivity_report=preflight,
        )

    uninterrupted = run(tmp_path / "uninterrupted")
    original = RunStore.write_result
    writes: list[tuple[str, str]] = []

    def interrupt(store: RunStore, result: MatchResult) -> None:
        original(store, result)
        writes.append((str(store.root), result.case_id))
        if len(writes) == 17:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _ = run(tmp_path / "recovered")
    recovered = run(tmp_path / "recovered")
    assert recovered.to_dict() == uninterrupted.to_dict()
    assert {method.method for method in recovered.methods} == {
        OptimizerMethod.RANDOM,
        OptimizerMethod.CMA_ES,
    }
    assert len(writes) == len(set(writes)) == 60
    decisions = [
        select_challenger(tmp_path / name, repository_root=REPOSITORY_ROOT)
        for name in ("uninterrupted", "recovered")
    ]
    assert decisions[0] == decisions[1]
    for method, other in zip(recovered.methods, uninterrupted.methods, strict=True):
        for trial, reference in zip(method.trials, other.trials, strict=True):
            assert [
                (r.case_id, r.semantic_digest, r.termination)
                for r in trial.evaluation.trial.results
            ] == [
                (r.case_id, r.semantic_digest, r.termination)
                for r in reference.evaluation.trial.results
            ]
    assert not list(tmp_path.glob("*/selection/confirmation"))


def test_synthetic_confirmation_exports_nondefault_policy_for_actual_m1_reproduction(
    experiment: Experiment,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment.optimize()
    selection = experiment.select()
    assert selection.selected is not None
    with pytest.raises(SpecError, match="verify"):
        _ = experiment.finalize()
    experiment.verify()  # Synthetic receipt; this fixture never claims scientific improvement.
    confirmation = experiment.finalize()
    assert confirmation.promoted
    artifact_path = experiment.root / "selection/confirmation/policy.json"
    artifact = PolicyArtifact.load(artifact_path)
    assert artifact.status is PolicyStatus.PROMOTED
    assert artifact.configuration.digest() != experiment.study.incumbent.digest()
    bot = load_policy_bot(artifact_path, bot_id="reloaded")
    assert isinstance(bot, HeuristicBot)
    assert verified_decision_plan(bot).chosen_action is not None

    # Evaluate the exported configuration through the evaluation match loop.
    monkeypatch.setattr(execution, "execute_case", execute_case)
    base = experiment.study.optimization.suite
    suite = replace(
        base,
        suite_id="artifact-acceptance",
        purpose=SuitePurpose.SMOKE,
        candidate=candidate_from_artifact(base.candidate, artifact_path),
        deck_pairs=(base.deck_pairs[0],),
        seeds=(91201,),
    )
    run = execute_run(
        suite=suite,
        run_id="reload",
        output_root=tmp_path / "runtime",
        repository_root=REPOSITORY_ROOT,
        evidence_policy=EvidencePolicy.ALL,
    )
    assert run.report.failed_matches == 0 and run.report.missing_matches == 0
    # The run manifest records the full configuration; replay does not consult the artifact.
    artifact_path.unlink()
    outcome = reproduce_case(run.root, run.results[0].case_id, repository_root=REPOSITORY_ROOT)
    assert outcome.execution_identity_matches and outcome.semantics_reproduced


def test_equal_candidates_finish_with_incumbent_and_no_holdout(experiment: Experiment) -> None:
    for key in experiment.scores:
        experiment.scores[key] = 0.5
    experiment.optimize()
    selected = experiment.select()
    assert selected.selected is None
    confirmation = finalize_study(experiment.root, repository_root=REPOSITORY_ROOT)
    assert not confirmation.promoted
    assert confirmation.reasons == ("incumbent_retained_after_validation",)
    assert all(purpose is SuitePurpose.OPTIMIZE for purpose, _, _ in experiment.played)


def test_nomination_is_validation_only_and_deterministic(experiment: Experiment) -> None:
    from gwent_evaluation.tuning.assessment import nominate

    experiment.optimize()
    selected = experiment.select()
    before = len(experiment.played)
    assert nominate({"seed-b": selected, "seed-a": selected}) == "seed-a"
    assert nominate({"seed-a": replace(selected, selected=None)}) is None
    assert len(experiment.played) == before
    assert all(purpose is not SuitePurpose.TEST for purpose, _, _ in experiment.played)


def test_ci_storage_guard_prevents_registered_holdout_execution_and_reads(
    scientific: StudySpec,
    tmp_path: Path,
    registered_holdouts: frozenset[str],
) -> None:
    from gwent_evaluation.records import record_to_dict
    from gwent_evaluation.schedule import schedule_suite
    from gwent_evaluation.storage import run_manifest_identity
    from gwent_shared.json_payloads import dump_pretty_json

    assert {"core-test-v1", "weights-test", "pilot-test"} <= registered_holdouts
    suite = replace(scientific.test.suite, suite_id="weights-test")
    manifest = replace(scientific.test, suite=suite)
    store = RunStore(tmp_path, "guard")
    with pytest.raises(AssertionError, match="registered held-out"):
        _ = store.prepare(manifest, matches=schedule_suite(suite))
    store.root.mkdir()
    _ = store.manifest_path.write_text(
        dump_pretty_json(
            {"manifest_identity": run_manifest_identity(manifest), **record_to_dict(manifest)}
        )
    )
    with pytest.raises(AssertionError, match="registered held-out"):
        _ = store.load()
