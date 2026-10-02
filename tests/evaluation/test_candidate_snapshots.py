from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from shutil import copyfile
from typing import cast

import pytest
from gwent_engine.ai.baseline import HeuristicBot
from gwent_engine.ai.baseline.heuristic_configuration import HeuristicConfiguration
from gwent_evaluation.agents import resolve_agent, snapshot_suite
from gwent_evaluation.execution import EvidencePolicy
from gwent_evaluation.models import (
    AGENT_SPEC_VERSION,
    AgentSpec,
    BotFamily,
    SpecError,
    TerminationReason,
)
from gwent_evaluation.records import (
    CorruptRecordError,
    StorageError,
    record_to_dict,
    run_manifest_from_dict,
)
from gwent_evaluation.replay import ReplayError, replay_case
from gwent_evaluation.reporting import load_run
from gwent_evaluation.schedule import schedule_suite
from gwent_evaluation.specs import parse_agent_spec
from gwent_evaluation.storage import RunStore

from tests.evaluation.support import DECK_A, execute_suite, heuristic_agent, suite_spec


def candidate(value: float = 3.125) -> AgentSpec:
    default = HeuristicConfiguration()
    configuration = replace(
        default,
        baseline=replace(
            default.baseline, weights=replace(default.baseline.weights, immediate_points=value)
        ),
    )
    return AgentSpec(
        AGENT_SPEC_VERSION, "candidate", BotFamily.HEURISTIC, heuristic_configuration=configuration
    )


def test_named_and_explicit_defaults_share_configuration_identity() -> None:
    named = resolve_agent(heuristic_agent())
    explicit = resolve_agent(named.snapshot())
    assert named.digest() == explicit.digest()
    assert explicit.spec.profile is None
    bot = explicit.build(bot_id="candidate")
    assert isinstance(bot, HeuristicBot)
    assert bot.configuration == HeuristicConfiguration()
    assert (
        resolve_agent(replace(explicit.spec, agent_id="display label")).digest() == named.digest()
    )


def test_candidate_changes_keep_pairing_and_reject_foreign_results(tmp_path: Path) -> None:
    suite = suite_spec(
        candidate=candidate(),
        opponents=(heuristic_agent("opponent", profile="neutral"),),
        action_budget=1,
    )
    assert [m.case_id for m in schedule_suite(suite)] == [
        m.case_id for m in schedule_suite(snapshot_suite(suite))
    ]
    a = execute_suite(tmp_path, suite=suite, run_id="a", evidence_policy=EvidencePolicy.NONE)
    b = execute_suite(
        tmp_path,
        suite=replace(suite, candidate=candidate(2.75)),
        run_id="b",
        evidence_policy=EvidencePolicy.NONE,
    )
    loaded_a, loaded_b = load_run(a.root), load_run(b.root)
    assert loaded_a.benchmark_identity == loaded_b.benchmark_identity
    assert loaded_a.execution_identity != loaded_b.execution_identity
    assert loaded_a.manifest.candidate.digest != loaded_b.manifest.candidate.digest
    for first, second in zip(loaded_a.matches, loaded_b.matches, strict=True):
        assert replace(first, candidate_agent=second.candidate_agent) == second
    source, target = RunStore.from_root(a.root), RunStore.from_root(b.root)
    _ = copyfile(source.result_path(a.results[0].case_id), target.result_path(b.results[0].case_id))
    with pytest.raises(CorruptRecordError, match="execution identity"):
        _ = load_run(b.root)


def test_snapshot_reproduces_in_a_fresh_process_without_authoring_file(tmp_path: Path) -> None:
    source = tmp_path / "candidate.json"
    _ = source.write_text(json.dumps(record_to_dict(candidate())))
    spec = parse_agent_spec(cast(object, json.loads(source.read_text())))
    suite = suite_spec(
        candidate=spec, opponents=(heuristic_agent("opponent"),), deck_pairs=((DECK_A, DECK_A),)
    )
    run = execute_suite(tmp_path, suite=suite, evidence_policy=EvidencePolicy.NONE)
    assert all(result.termination is TerminationReason.COMPLETED for result in run.results)
    source.unlink()
    manifest = RunStore.from_root(run.root).read_manifest()
    assert manifest.suite.candidate == spec
    assert manifest.suite.opponents[0].heuristic_configuration is not None
    assert run_manifest_from_dict(record_to_dict(manifest)) == manifest
    code = """
import json, sys
sys.path[:] = json.loads(sys.argv[3])
from pathlib import Path
from gwent_evaluation import agents
from gwent_evaluation.models import TerminationReason
from gwent_evaluation.replay import reproduce_case
def forbidden(*args, **kwargs):
    raise AssertionError('Stored profiles must not be resolved by name')
agents.get_base_profile_definition = forbidden
outcome = reproduce_case(Path(sys.argv[1]), sys.argv[2])
assert outcome.termination is TerminationReason.COMPLETED, outcome
assert outcome.execution_identity_matches, outcome
assert outcome.semantics_reproduced, outcome
"""
    _ = subprocess.run(
        [sys.executable, "-c", code, str(run.root), run.results[0].case_id, json.dumps(sys.path)],
        check=True,
        capture_output=True,
        text=True,
    )
    with pytest.raises(ReplayError, match="no persisted trajectory"):
        _ = replay_case(run.root, run.results[0].case_id)


@pytest.mark.parametrize("family", [BotFamily.RANDOM, BotFamily.GREEDY, BotFamily.SEARCH])
def test_configuration_rejected_on_other_families(family: BotFamily) -> None:
    with pytest.raises(SpecError):
        _ = replace(candidate(), family=family)
    payload = record_to_dict(candidate())
    payload["family"] = family.value
    with pytest.raises(SpecError):
        _ = parse_agent_spec(payload)


def test_ambiguous_and_historical_specs_fail_explicitly(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="mutually exclusive"):
        _ = replace(candidate(), profile="neutral")
    payload = record_to_dict(candidate())
    payload["schema_version"] = 1
    with pytest.raises(SpecError, match="schema_version"):
        _ = parse_agent_spec(payload)
    run = execute_suite(
        tmp_path, suite=suite_spec(action_budget=1), evidence_policy=EvidencePolicy.NONE
    )
    historical = record_to_dict(RunStore.from_root(run.root).read_manifest())
    historical["schema_version"] = 2
    with pytest.raises(StorageError, match="schema_version"):
        _ = run_manifest_from_dict(historical)


def test_persisted_heuristic_requires_full_snapshot(tmp_path: Path) -> None:
    run = execute_suite(
        tmp_path, suite=suite_spec(action_budget=1), evidence_policy=EvidencePolicy.NONE
    )
    payload = record_to_dict(RunStore.from_root(run.root).read_manifest())
    suite = cast(dict[str, object], payload["suite"])
    suite["candidate"] = record_to_dict(heuristic_agent())
    with pytest.raises(StorageError, match="snapshot"):
        _ = run_manifest_from_dict(payload)
