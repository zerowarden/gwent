"""Study orchestration over synthetic, checksummed match records."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import NoReturn, final

import pytest
from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration
from gwent_evaluation.agents import resolve_agent
from gwent_evaluation.execution import agent_identity
from gwent_evaluation.models import MatchResult, SpecError, TerminationReason
from gwent_evaluation.storage import RunStore
from gwent_evaluation.tuning import study as study_module
from gwent_evaluation.tuning.models import CmaSettings, CmaTermination, OptimizerMethod, StudySpec
from gwent_evaluation.tuning.objective import TrialEvaluation, load_trial_evaluation
from gwent_evaluation.tuning.optimizers import (
    OptimizerStop,
    OptimizerStopReason,
    Proposal,
    ProposalFitness,
    ProposalOptimizer,
)
from gwent_evaluation.tuning.parameters import encode_parameters
from gwent_evaluation.tuning.sensitivity import SensitivityReport
from gwent_evaluation.tuning.study import StudyResult, StudyStoppedError, run_study

from tests.evaluation.support import REPOSITORY_ROOT
from tests.evaluation.tuning.test_objective import completed_result
from tests.evaluation.tuning.test_objective import preflight as preflight
from tests.evaluation.tuning.test_objective import scientific as scientific


@pytest.fixture
def experiment(scientific: StudySpec) -> StudySpec:
    optimizers = (
        replace(scientific.optimizers[0], proposal_budget=4),
        replace(
            scientific.optimizers[1],
            proposal_budget=4,
            generations=2,
            cma=CmaSettings(
                termination=CmaTermination(
                    function_tolerance=0, history_tolerance=0, flat_generations=100
                )
            ),
        ),
    )
    return replace(scientific, optimizers=optimizers, evaluation_match_budget=168)


@pytest.fixture
def evidence(experiment: StudySpec, preflight: SensitivityReport) -> SensitivityReport:
    return replace(preflight, study_digest=experiment.digest())


@pytest.fixture
def played(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Write synthetic results through the real run store and objective verifier."""
    matches: list[tuple[str, str]] = []

    def evaluate(
        study: StudySpec,
        configuration: HeuristicConfiguration,
        *,
        run_id: str,
        output_root: Path,
        repository_root: Path | None = None,
        sensitivity_report: SensitivityReport | None = None,
    ) -> TrialEvaluation:
        from gwent_evaluation.schedule import schedule_suite

        candidate = replace(
            study.optimization.suite.candidate, heuristic_configuration=configuration
        )
        manifest = replace(
            study.optimization,
            run_id=run_id,
            suite=replace(study.optimization.suite, candidate=candidate),
            candidate=agent_identity(resolve_agent(candidate)),
        )
        store = RunStore(output_root, run_id)
        loaded = store.prepare(manifest, matches=schedule_suite(manifest.suite))
        newly_played = 0
        for index, match in enumerate(loaded.matches):
            if match.case_id in loaded.results:
                continue
            value = int(configuration.digest()[-8:], 16)
            score = ((value + index) % 3) / 2
            store.write_result(completed_result(match, manifest, score))
            matches.append((run_id, match.case_id))
            newly_played += 1
        trial = load_trial_evaluation(
            study,
            configuration,
            run_root=store.root,
            repository_root=repository_root,
            sensitivity_report=sensitivity_report,
        )
        return replace(trial, fresh_matches=newly_played)

    monkeypatch.setattr(study_module, "evaluate_candidate", evaluate)
    return matches


def execute(experiment: StudySpec, evidence: SensitivityReport, root: Path) -> StudyResult:
    return run_study(
        experiment,
        output_root=root,
        repository_root=REPOSITORY_ROOT,
        sensitivity_report=evidence,
    )


def test_complete_study_reuses_every_committed_trial_without_playing_again(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = execute(experiment, evidence, tmp_path)
    assert result.outcome.counts.proposals == 8
    assert len(played) == result.outcome.counts.fresh_matches == 108
    assert len(set(played)) == len(played)
    assert result.to_dict()["stage"] == "optimization_complete"
    assert result.to_dict()["promotion"] == "not_assessed"
    assert (tmp_path / "snapshot.json").exists()
    assert (tmp_path / "report.json").exists()

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Recovery must inspect committed evidence without evaluating candidates")

    monkeypatch.setattr(study_module, "evaluate_candidate", forbidden)
    replay = execute(experiment, evidence, tmp_path)
    assert replay == result


def test_smoke_or_stale_sensitivity_cannot_enter_optimization(
    study: StudySpec,
    experiment: StudySpec,
    evidence: SensitivityReport,
    tmp_path: Path,
) -> None:
    with pytest.raises(SpecError):
        _ = execute(study, replace(evidence, study_digest=study.digest()), tmp_path / "smoke")
    with pytest.raises(SpecError, match="different study"):
        _ = execute(experiment, replace(evidence, study_digest="stale"), tmp_path / "stale")
    assert not (tmp_path / "smoke").exists()
    assert not (tmp_path / "stale").exists()


def test_preflight_operational_costs_do_not_change_scientific_identity(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
) -> None:
    result = execute(experiment, evidence, tmp_path)
    replay = execute(
        experiment,
        replace(evidence, executed_matches=8, disk_bytes=9, match_execution_seconds=2),
        tmp_path,
    )
    assert replay == result
    assert len(played) == 108


def test_failed_trial_is_recorded_and_never_told_or_retried(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RunStore.write_result

    def fail(store: RunStore, result: MatchResult) -> None:
        original(
            store,
            replace(
                result,
                termination=TerminationReason.ACTION_LIMIT,
                winner=None,
                candidate_score=None,
                accepted_transitions=experiment.optimization.suite.action_budget,
            ),
        )

    monkeypatch.setattr(RunStore, "write_result", fail)
    with pytest.raises(StudyStoppedError, match="eligible"):
        _ = execute(experiment, evidence, tmp_path)
    count = len(played)
    with pytest.raises(StudyStoppedError, match="previously stopped"):
        _ = execute(experiment, evidence, tmp_path)
    assert len(played) == count
    assert '"kind": "tell"' not in "".join(
        path.read_text() for path in (tmp_path / "journal").glob("*.json")
    )


def test_duplicates_preserve_slots_and_reuse_across_populations_and_methods(
    experiment: StudySpec,
    evidence: SensitivityReport,
    played: list[tuple[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incumbent = encode_parameters(
        experiment.parameter_space,
        experiment.incumbent,
        frozen_configuration=experiment.incumbent,
    )
    repeated = (0.0,) * len(incumbent)
    tells: list[tuple[ProposalFitness, ...]] = []

    @final
    class RepeatedProposals:
        def __init__(self) -> None:
            self.completed = 0

        @property
        def stop(self) -> OptimizerStop | None:
            return (
                OptimizerStop(OptimizerStopReason.BUDGET_EXHAUSTED, self.completed)
                if self.completed == 4
                else None
            )

        @property
        def stop_reason(self) -> OptimizerStopReason | None:
            return None if self.stop is None else self.stop.reason

        def ask(self) -> tuple[Proposal, ...]:
            if self.stop is not None:
                return ()
            return (
                Proposal(self.completed, repeated),
                Proposal(self.completed + 1, incumbent if self.completed else repeated),
            )

        def tell(self, results: tuple[ProposalFitness, ...]) -> None:
            assert tuple(result.proposal for result in results) == self.ask()
            tells.append(results)
            self.completed += len(results)

    def factory(_study: StudySpec, _method: OptimizerMethod) -> ProposalOptimizer:
        return RepeatedProposals()

    monkeypatch.setattr(study_module, "create_optimizer", factory)
    result = execute(experiment, evidence, tmp_path)
    assert result.outcome.counts.distinct_configurations == 2
    assert result.outcome.counts.cache_hits == 7
    assert result.outcome.counts.fresh_matches == len(played) == 24
    assert len(tells) == 4
    assert tells[0][0].fitness == tells[0][1].fitness == tells[1][0].fitness
    assert execute(experiment, evidence, tmp_path) == result
    assert len(played) == 24
