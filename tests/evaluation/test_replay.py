from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.agents import BotAgent, GreedyBot
from gwent_engine.ai.arena.models import TerminationReason
from gwent_evaluation import AgentSpec, EvidencePolicy, SuiteSpec, replay_case, reproduce_case
from gwent_evaluation import execution as execution_module
from gwent_evaluation.agents import ResolvedAgent
from gwent_evaluation.assets import ResolvedAssets
from gwent_evaluation.models import BotFamily, RunExecution
from gwent_evaluation.provenance import RepositoryProvenance
from gwent_evaluation.replay import ReplayError
from gwent_evaluation.storage import RunStore

from tests.engine.ai.bots import AlwaysPassBot, FailingAfterBot
from tests.evaluation.support import (
    DECK_A,
    DECK_B,
    agent_spec,
    evaluation_suite,
    execute_evaluation_suite,
    heuristic_agent,
    read_json_object,
    write_json_object,
)


def _suite(
    *,
    candidate: AgentSpec | None = None,
    opponents: tuple[AgentSpec, ...] | None = None,
    deck_pairs: tuple[tuple[str, str], ...] = ((DECK_A, DECK_B),),
) -> SuiteSpec:
    return evaluation_suite(
        "replay-test",
        candidate=candidate,
        opponents=opponents,
        deck_pairs=deck_pairs,
    )


def _execute(
    output_root: Path,
    *,
    suite: SuiteSpec | None = None,
    run_id: str = "run",
    evidence_policy: EvidencePolicy = EvidencePolicy.ALL,
) -> RunExecution:
    return execute_evaluation_suite(
        output_root,
        suite=suite or _suite(),
        run_id=run_id,
        evidence_policy=evidence_policy,
    )


def _tamper_step_events(run_root: Path, case_id: str, *, index: int) -> None:
    path = run_root / "evidence" / f"{case_id}.trajectory.json"
    document = dict(read_json_object(path))
    steps = cast(list[dict[str, object]], document["steps"])
    steps[index - 1]["event_fingerprints"] = ["tampered"]
    write_json_object(path, document)


def test_completed_cases_reproduce_and_replay(tmp_path: Path) -> None:
    execution = _execute(
        tmp_path,
        suite=_suite(
            candidate=heuristic_agent("candidate"),
            opponents=(heuristic_agent("opponent"),),
        ),
    )

    assert any(result.pending_choice_occurred for result in execution.results)
    for result in execution.results:
        reproduction = reproduce_case(execution.root, result.case_id)
        assert reproduction.execution_identity_matches is True
        assert reproduction.semantics_reproduced is True
        assert reproduction.reproduced is True
        assert reproduction.divergences == ()

        replay = replay_case(execution.root, result.case_id)
        assert replay.reproduced is True
        assert replay.replayed_steps == replay.total_steps
        assert replay.prefix_only is False


def test_stochastic_case_reproduces_and_replays(tmp_path: Path) -> None:
    execution = _execute(
        tmp_path,
        suite=_suite(
            candidate=agent_spec("candidate", family=BotFamily.RANDOM),
            deck_pairs=((DECK_A, DECK_A),),
        ),
    )
    result = execution.results[0]

    reproduction = reproduce_case(execution.root, result.case_id)
    assert reproduction.reproduced is True

    replay = replay_case(execution.root, result.case_id)
    assert replay.reproduced is True
    assert replay.replayed_steps == replay.total_steps


def test_tampered_trajectory_is_detected(tmp_path: Path) -> None:
    execution = _execute(tmp_path, suite=_suite(deck_pairs=((DECK_A, DECK_A),)))
    case_id = execution.results[0].case_id
    _tamper_step_events(execution.root, case_id, index=3)

    from gwent_evaluation.records import CorruptRecordError

    with pytest.raises(CorruptRecordError, match="Evidence digest mismatch"):
        _ = replay_case(execution.root, case_id)


def test_reproduction_detects_policy_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execute(tmp_path, suite=_suite(deck_pairs=((DECK_A, DECK_A),)))
    case_id = execution.results[0].case_id

    def build(_self: ResolvedAgent, *, bot_id: str, seed: int | None = None) -> BotAgent:
        del seed
        return AlwaysPassBot(delegate=GreedyBot(bot_id=bot_id))

    monkeypatch.setattr(ResolvedAgent, "build", build)

    reproduction = reproduce_case(execution.root, case_id)

    assert reproduction.reproduced is False
    assert reproduction.execution_identity_matches is True
    assert reproduction.semantics_reproduced is False
    assert len(reproduction.divergences) == 1
    divergence = reproduction.divergences[0]
    assert divergence.index == 3
    assert divergence.field == "action_id"


@pytest.mark.parametrize(
    "changed", ["implementation", "runtime", "candidate", "opponent", "decks", "cards", "leaders"]
)
def test_reproduction_reports_identity_drift_independently_of_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    execution = _execute(tmp_path, suite=replace(_suite(), action_budget=1))
    manifest = RunStore.from_root(execution.root).read_manifest()
    if changed == "implementation":

        def changed_provenance(_root: Path) -> RepositoryProvenance:
            return replace(manifest.repository, implementation_digest="changed")

        monkeypatch.setattr(execution_module, "read_repository_provenance", changed_provenance)
    elif changed == "runtime":
        monkeypatch.setattr(
            execution_module,
            "read_runtime_provenance",
            lambda: replace(manifest.runtime, python_version="changed"),
        )
    elif changed in {"candidate", "opponent"}:
        original_digest = ResolvedAgent.digest
        agent_id = (
            manifest.candidate.agent_id
            if changed == "candidate"
            else manifest.opponents[0].agent_id
        )

        def changed_digest(agent: ResolvedAgent) -> str:
            return "changed" if agent.agent_id == agent_id else original_digest(agent)

        monkeypatch.setattr(ResolvedAgent, "digest", changed_digest)
    else:

        def changed_asset_digest(_assets: ResolvedAssets, *_args: str) -> str:
            return "changed"

        method = {
            "decks": "deck_digest",
            "cards": "card_data_digest",
            "leaders": "leader_data_digest",
        }[changed]
        monkeypatch.setattr(ResolvedAssets, method, changed_asset_digest)

    reproduction = reproduce_case(execution.root, execution.results[0].case_id)

    assert reproduction.execution_identity_matches is False
    assert reproduction.semantics_reproduced is True
    assert reproduction.reproduced is True
    assert reproduction.divergences == ()


def test_failure_prefix_reproduces_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build(_self: ResolvedAgent, *, bot_id: str, seed: int | None = None) -> BotAgent:
        del seed
        return FailingAfterBot(delegate=GreedyBot(bot_id=bot_id), fail_after=2)

    monkeypatch.setattr(ResolvedAgent, "build", build)

    execution = _execute(
        tmp_path,
        suite=_suite(deck_pairs=((DECK_A, DECK_A),)),
        evidence_policy=EvidencePolicy.FAILURES,
    )
    result = execution.results[0]
    assert result.termination is TerminationReason.AGENT_ERROR
    assert result.evidence.trajectory_path is not None

    reproduction = reproduce_case(execution.root, result.case_id)
    assert reproduction.reproduced is True

    replay = replay_case(execution.root, result.case_id)
    assert replay.reproduced is False
    assert replay.prefix_only is True
    assert replay.prefix_verified is True
    assert replay.replayed_steps == replay.total_steps
    assert replay.total_steps >= 3


def test_replay_requires_trajectory_evidence(tmp_path: Path) -> None:
    execution = _execute(
        tmp_path,
        suite=_suite(deck_pairs=((DECK_A, DECK_A),)),
        evidence_policy=EvidencePolicy.FAILURES,
    )
    result = execution.results[0]
    assert result.evidence.trajectory_path is None

    with pytest.raises(ReplayError, match="no persisted trajectory"):
        _ = replay_case(execution.root, result.case_id)


def test_unknown_case_is_rejected(tmp_path: Path) -> None:
    execution = _execute(tmp_path, suite=_suite(deck_pairs=((DECK_A, DECK_A),)))

    with pytest.raises(ReplayError, match="not part of run"):
        _ = replay_case(execution.root, "missing-case")
