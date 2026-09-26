from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from gwent_engine.ai.agents import BotAgent, GreedyBot
from gwent_engine.ai.arena.models import TerminationReason
from gwent_evaluation import (
    AgentSpec,
    BotFamily,
    EvidencePolicy,
    ReplayError,
    ResolvedAgent,
    RunExecution,
    SuiteSpec,
    replay_case,
    reproduce_case,
)

from tests.engine.ai.bots import AlwaysPassBot, FailingAfterBot
from tests.evaluation.support import (
    DECK_A,
    DECK_B,
    agent_spec,
    execute_suite,
    heuristic_agent,
    read_json_object,
    suite_spec,
    write_json_object,
)


def _suite(
    *,
    candidate: AgentSpec | None = None,
    opponents: tuple[AgentSpec, ...] | None = None,
    deck_pairs: tuple[tuple[str, str], ...] = ((DECK_A, DECK_B),),
) -> SuiteSpec:
    return suite_spec(
        suite_id="replay-test",
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
    return execute_suite(
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

    replay = replay_case(execution.root, case_id)

    assert replay.reproduced is False
    assert replay.replayed_steps == 2
    assert len(replay.divergences) == 1
    divergence = replay.divergences[0]
    assert divergence.index == 3
    assert divergence.field == "event_fingerprints"


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
    assert len(reproduction.divergences) == 1
    divergence = reproduction.divergences[0]
    assert divergence.index == 3
    assert divergence.field == "action_id"


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
    assert replay.reproduced is True
    assert replay.prefix_only is True
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
