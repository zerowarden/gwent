"""Selection and confirmation over small synthetic, checksummed match records."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from gwent_engine.ai.policy_artifacts import PolicyArtifact, PolicyStatus
from gwent_evaluation.execution import EvidencePolicy, RunExecution
from gwent_evaluation.models import (
    MatchResult,
    RunManifest,
    SpecError,
    SuitePurpose,
    SuiteSpec,
    TerminationReason,
)
from gwent_evaluation.reporting import build_run_report
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.storage import RunConflictError, RunStore
from gwent_evaluation.tuning import objective, selection, verification
from gwent_evaluation.tuning import study as controller
from gwent_evaluation.tuning.models import OptimizerMethod, StudySpec
from gwent_evaluation.tuning.optimizers import (
    OptimizerStop,
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
)
from gwent_evaluation.tuning.selection import finalize_study, select_challenger, verify_selection
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.storage import (
    StudyStore,
    read_checked_document,
    write_checked_document,
)
from gwent_evaluation.tuning.study import load_completed_study, run_study

from tests.evaluation.support import REPOSITORY_ROOT
from tests.evaluation.tuning.test_objective import completed_result
from tests.evaluation.tuning.test_objective import preflight as preflight
from tests.evaluation.tuning.test_objective import scientific as scientific


class FixedProposals:
    def __init__(self) -> None:
        self.done: bool = False

    @property
    def stop(self) -> OptimizerStop | None:
        return OptimizerStop(OptimizerStopReason.BUDGET_EXHAUSTED, 2) if self.done else None

    @property
    def stop_reason(self) -> OptimizerStopReason | None:
        return None if self.stop is None else self.stop.reason

    def ask(self) -> tuple[Proposal, ...]:
        return () if self.done else (Proposal(0, (0.0,) * 11), Proposal(1, (1.0,) * 11))

    def tell(self, results: tuple[ProposalFitness, ...]) -> None:
        assert tuple(item.proposal for item in results) == self.ask()
        self.done = True


@dataclass
class Experiment:
    study: StudySpec
    evidence: SensitivityReport
    root: Path
    scores: dict[tuple[SuitePurpose, str], float]
    played: list[tuple[SuitePurpose, str, str]]
    deck_scores: dict[tuple[SuitePurpose, str, str], float]

    def optimize(self) -> None:
        _ = run_study(
            self.study,
            output_root=self.root,
            repository_root=REPOSITORY_ROOT,
            sensitivity_report=self.evidence,
        )

    def select(self) -> selection.SelectionResult:
        return select_challenger(self.root, repository_root=REPOSITORY_ROOT)

    def verify(self) -> None:
        assert verify_selection(self.root, repository_root=REPOSITORY_ROOT)["passed"]

    def finalize(self) -> selection.ConfirmationResult:
        return finalize_study(self.root, repository_root=REPOSITORY_ROOT)

    @property
    def challenger(self) -> str:
        return self.study.bind((1.0,) * 11).digest()

    @property
    def alternative(self) -> str:
        return self.study.bind((0.0,) * 11).digest()


@pytest.fixture
def experiment(
    scientific: StudySpec,
    preflight: SensitivityReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Experiment:
    spec = replace(scientific, bootstrap=replace(scientific.bootstrap, minimum_blocks=2))
    fixture = Experiment(
        spec, replace(preflight, study_digest=spec.digest()), tmp_path / "study", {}, [], {}
    )
    for stage in (SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST):
        fixture.scores[stage, spec.incumbent.digest()] = 0.0
        fixture.scores[stage, fixture.challenger] = 1.0
        fixture.scores[stage, fixture.alternative] = 0.5

    def factory(_study: StudySpec, _method: OptimizerMethod) -> FixedProposals:
        return FixedProposals()

    def evaluate(
        *,
        suite: SuiteSpec,
        run_id: str,
        output_root: Path,
        repository_root: Path,
        evidence_policy: EvidencePolicy,
        expected_manifest: RunManifest,
    ) -> RunExecution:
        assert repository_root == REPOSITORY_ROOT
        assert expected_manifest.suite == suite
        assert evidence_policy is EvidencePolicy.NONE
        configuration = suite.candidate.heuristic_configuration
        assert configuration is not None
        digest = configuration.digest()
        if suite.purpose is SuitePurpose.TEST:
            assert (fixture.root / "selection/selection.json").is_file()
        store = RunStore(output_root, run_id)
        loaded = store.prepare(expected_manifest, matches=schedule_suite(suite))
        fresh: list[str] = []
        for match in loaded.matches:
            if match.case_id in loaded.results:
                continue
            score = fixture.deck_scores.get(
                (suite.purpose, digest, match.candidate_deck_id),
                fixture.scores[suite.purpose, digest],
            )
            store.write_result(completed_result(match, expected_manifest, score))
            fixture.played.append((suite.purpose, digest, match.case_id))
            fresh.append(match.case_id)
        loaded = store.load()
        return RunExecution(
            run_id,
            store.root,
            tuple(loaded.results.values()),
            tuple(fresh),
            tuple(loaded.results.keys() - set(fresh)),
            build_run_report(loaded),
        )

    monkeypatch.setattr(controller, "create_optimizer", factory)
    monkeypatch.setattr(objective, "execute_run", evaluate)
    monkeypatch.setattr(selection, "execute_run", evaluate)

    def checks(_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["make", "check"], 0, "passed\n", "")

    monkeypatch.setattr(verification, "run_correctness_checks", checks)
    return fixture


def test_frozen_selection_precedes_test_and_exports_verified_policy(experiment: Experiment) -> None:
    experiment.optimize()
    assert {item[0] for item in experiment.played} == {SuitePurpose.OPTIMIZE}
    result = experiment.select()
    assert result.selected is not None and result.selected.digest() == experiment.challenger
    assert len(result.finalist_digests) == 2  # Duplicates across methods are removed.
    assert SuitePurpose.TEST not in {item[0] for item in experiment.played}
    artifact = PolicyArtifact.load(experiment.root / "selection/selected-policy.json")
    assert artifact.status is PolicyStatus.UNPROMOTED
    with pytest.raises(SpecError, match="verify"):
        _ = experiment.finalize()
    experiment.verify()
    confirmation = experiment.finalize()
    assert confirmation.promoted and not confirmation.reasons
    assert {
        digest for purpose, digest, _case in experiment.played if purpose is SuitePurpose.TEST
    } == {
        experiment.study.incumbent.digest(),
        experiment.challenger,
    }
    exported = PolicyArtifact.load(experiment.root / "selection/confirmation/policy.json")
    assert exported.status is PolicyStatus.PROMOTED
    assert exported.configuration_digest == experiment.challenger
    assert exported.selection_digest == result.digest()
    count = len(experiment.played)
    assert experiment.finalize() == confirmation
    assert len(experiment.played) == count


@pytest.mark.parametrize("outcome", ["regression", "tie", "too_few_blocks", "no_optimization_gain"])
def test_ineligible_validation_retains_incumbent_without_test(
    experiment: Experiment, outcome: str
) -> None:
    if outcome == "regression":
        experiment.scores[SuitePurpose.VALIDATION, experiment.study.incumbent.digest()] = 1.0
        experiment.scores[SuitePurpose.VALIDATION, experiment.challenger] = 0.0
    elif outcome == "tie":
        experiment.scores[SuitePurpose.VALIDATION, experiment.alternative] = 1.0
    elif outcome == "too_few_blocks":
        experiment.study = replace(
            experiment.study, bootstrap=replace(experiment.study.bootstrap, minimum_blocks=8)
        )
        experiment.evidence = replace(experiment.evidence, study_digest=experiment.study.digest())
    else:
        experiment.scores[SuitePurpose.OPTIMIZE, experiment.study.incumbent.digest()] = 1.0
    experiment.optimize()
    result = experiment.select()
    assert result.selected is None and result.reasons
    confirmation = experiment.finalize()
    assert not confirmation.promoted
    assert SuitePurpose.TEST not in {item[0] for item in experiment.played}
    assert not (experiment.root / "selection/selected-policy.json").exists()


def test_rejected_confirmation_never_tests_a_runner_up(experiment: Experiment) -> None:
    experiment.optimize()
    _ = experiment.select()
    experiment.verify()
    experiment.scores[SuitePurpose.TEST, experiment.challenger] = 0.0
    result = experiment.finalize()
    assert not result.promoted
    assert "no_positive_improvement" in result.reasons
    assert all(
        digest != experiment.alternative
        for stage, digest, _ in experiment.played
        if stage is SuitePurpose.TEST
    )
    assert (
        PolicyArtifact.load(experiment.root / "selection/confirmation/policy.json").status
        is PolicyStatus.UNPROMOTED
    )
    count = len(experiment.played)
    assert experiment.finalize() == result
    assert len(experiment.played) == count


def test_subgroup_regression_blocks_positive_overall_confirmation(experiment: Experiment) -> None:
    experiment.optimize()
    _ = experiment.select()
    experiment.verify()
    reference = experiment.study.incumbent.digest()
    experiment.scores[SuitePurpose.TEST, reference] = 0.5
    deck = experiment.study.test.suite.deck_pairs[1][1]
    experiment.deck_scores[SuitePurpose.TEST, experiment.challenger, deck] = 0.0
    result = experiment.finalize()
    assert result.assessment is not None
    assert result.assessment.comparison.mean_difference is not None
    assert result.assessment.comparison.mean_difference > 0
    assert not result.promoted
    assert f"stratum_decline:candidate_deck:{deck}" in result.reasons


def test_confirmation_recovers_only_missing_matches(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment.optimize()
    selected = experiment.select()
    experiment.verify()
    original = RunStore.write_result
    committed: list[tuple[str, str]] = []

    def interrupt(store: RunStore, result: object) -> None:
        from gwent_evaluation.models import MatchResult

        assert isinstance(result, MatchResult)
        original(store, result)
        committed.append((store.run_id, result.case_id))
        if len(committed) == 15:
            raise KeyboardInterrupt

    monkeypatch.setattr(RunStore, "write_result", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _ = experiment.finalize()
    result = experiment.finalize()
    assert result.promoted and result.selection_digest == selected.digest()
    assert len(committed) == len(set(committed)) == 24


@pytest.mark.parametrize("target", ["artifact", "selection", "threshold", "result", "verification"])
def test_tampering_prevents_any_held_out_execution(experiment: Experiment, target: str) -> None:
    experiment.optimize()
    _ = experiment.select()
    experiment.verify()
    root = experiment.root / "selection"
    if target == "artifact":
        path = root / "selected-policy.json"
        _ = path.write_text(
            path.read_text()
            .replace('"promoted"', '"unpromoted"')
            .replace('"family": "heuristic"', '"family": "random"')
        )
    elif target == "verification":
        _ = (root / "verification.log").write_text("changed")
    elif target == "selection":
        payload = dict(read_checked_document(root / "selection.json"))
        payload["selected_digest"] = experiment.alternative
        _ = write_checked_document(root / "selection.json", payload)
    elif target == "threshold":
        payload = dict(read_checked_document(experiment.root / "snapshot.json"))
        from typing import cast

        snapshot = cast(dict[str, object], payload["snapshot"])
        study = cast(dict[str, object], snapshot["study"])
        policy = cast(dict[str, object], study["selection"])
        policy["minimum_test_improvement"] = 0.0
        _ = write_checked_document(experiment.root / "snapshot.json", payload)
    else:
        next((root / "runs").glob("*/matches/*.json")).unlink()
    with pytest.raises(ValueError):
        _ = experiment.finalize()
    assert SuitePurpose.TEST not in {item[0] for item in experiment.played}


def test_unfinished_optimization_and_selection_cannot_consume_test(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = StudyStore.record

    def interrupt(store: StudyStore, kind: str, payload: object) -> str:
        from collections.abc import Mapping
        from typing import cast

        if kind == "ask":
            raise KeyboardInterrupt
        return original(store, kind, cast(Mapping[str, object], payload))

    monkeypatch.setattr(StudyStore, "record", interrupt)
    with pytest.raises(KeyboardInterrupt):
        experiment.optimize()
    count = len(experiment.played)
    monkeypatch.setattr(StudyStore, "record", original)
    with pytest.raises(RunConflictError):
        _ = experiment.select()
    assert len(experiment.played) == count
    experiment.optimize()
    with pytest.raises(RunConflictError):
        _ = experiment.finalize()
    assert SuitePurpose.TEST not in {item[0] for item in experiment.played}


def test_completed_study_reload_checks_inputs_without_executing(experiment: Experiment) -> None:
    experiment.optimize()
    count = len(experiment.played)
    study, result = load_completed_study(experiment.root, repository_root=REPOSITORY_ROOT)
    assert study == experiment.study
    assert result.outcome.counts.distinct_configurations == 3
    assert len(experiment.played) == count


def test_failed_verification_preserves_holdout(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment.optimize()
    _ = experiment.select()

    def checks(_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["make", "check"], 1, "failure\n", "")

    monkeypatch.setattr(verification, "run_correctness_checks", checks)
    evidence = verify_selection(experiment.root, repository_root=REPOSITORY_ROOT)
    assert evidence["passed"] is False
    with pytest.raises(RunConflictError, match="verification"):
        _ = experiment.finalize()
    assert SuitePurpose.TEST not in {item[0] for item in experiment.played}


def test_positive_confirmation_below_declared_minimum_is_not_promoted(
    experiment: Experiment,
) -> None:
    experiment.study = replace(
        experiment.study,
        selection=replace(experiment.study.selection, minimum_test_improvement=0.75),
    )
    experiment.evidence = replace(experiment.evidence, study_digest=experiment.study.digest())
    experiment.optimize()
    _ = experiment.select()
    experiment.verify()
    experiment.scores[SuitePurpose.TEST, experiment.challenger] = 0.5
    result = experiment.finalize()
    assert not result.promoted
    assert result.reasons == ("improvement_below_threshold",)


def test_failed_validation_is_terminal_and_never_dropped(
    experiment: Experiment, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment.optimize()
    original = RunStore.write_result

    def fail(store: RunStore, result: MatchResult) -> None:
        if store.run_id.endswith(experiment.challenger.removeprefix("sha256:")):
            result = replace(
                result,
                termination=TerminationReason.ACTION_LIMIT,
                candidate_score=None,
                winner=None,
                accepted_transitions=experiment.study.validation.suite.action_budget,
            )
        original(store, result)

    monkeypatch.setattr(RunStore, "write_result", fail)
    selected = experiment.select()
    assert selected.selected is None
    assert selected.reasons == ("invalid_challenger_validation",)
    assert selected.assessments[0].reasons == ("invalid_or_incomplete_evidence",)
    count = len(experiment.played)
    assert experiment.select() == selected
    assert not experiment.finalize().promoted
    assert len(experiment.played) == count


def test_cli_selection_verification_and_confirmation(
    experiment: Experiment, capsys: pytest.CaptureFixture[str]
) -> None:
    from gwent_evaluation.cli import EXIT_OK, main

    experiment.optimize()
    assert main(["tune", "select", str(experiment.root)]) == EXIT_OK
    assert '"stage": "validation_complete"' in capsys.readouterr().out
    assert main(["tune", "verify", str(experiment.root)]) == EXIT_OK
    assert '"passed": true' in capsys.readouterr().out
    assert main(["tune", "finalize", str(experiment.root)]) == EXIT_OK
    assert '"promoted": true' in capsys.readouterr().out
