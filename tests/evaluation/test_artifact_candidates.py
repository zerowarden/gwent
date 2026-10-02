from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from gwent_engine.ai.baseline.policy_artifacts import PolicyArtifact
from gwent_evaluation.agents import candidate_from_artifact
from gwent_evaluation.cli import EXIT_ERROR, EXIT_OK, main
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.replay import reproduce_case
from gwent_evaluation.reporting import load_run
from gwent_shared.json_payloads import dump_pretty_json

from tests.engine.ai.support import sample_policy_artifact
from tests.evaluation.support import (
    DECK_A,
    execute_suite,
    greedy_agent,
    heuristic_agent,
    suite_spec,
)


def test_cli_artifact_matches_direct_candidate_and_embeds_snapshot(tmp_path: Path) -> None:
    artifact = sample_policy_artifact()
    path = tmp_path / "policy.json"
    _ = path.write_text(dump_pretty_json(artifact.to_dict()))
    candidate, opponent = heuristic_agent("candidate"), greedy_agent("opponent")
    suite = suite_spec(
        suite_id="artifact-smoke",
        candidate=candidate,
        opponents=(opponent,),
        deck_pairs=((DECK_A, DECK_A),),
        seeds=(17,),
    )
    suites, agents = tmp_path / "suites.json", tmp_path / "agents.json"
    _ = agents.write_text(
        dump_pretty_json(
            {"schema_version": 2, "agents": [record_to_dict(candidate), record_to_dict(opponent)]}
        )
    )
    payload = record_to_dict(suite)
    payload.update(candidate=candidate.agent_id, opponents=[opponent.agent_id])
    del payload["observation_contract_version"]
    _ = suites.write_text(dump_pretty_json({"schema_version": 1, "suites": [payload]}))
    output = tmp_path / "runs"
    arguments = [
        "run",
        str(suites),
        "--agents-catalog",
        str(agents),
        "--suite",
        "artifact-smoke",
        "--output-root",
        str(output),
        "--run-id",
        "run",
    ]
    assert main([*arguments, "--candidate-artifact", str(path)]) == EXIT_OK
    loaded = load_run(output / "run")
    spec = loaded.manifest.suite.candidate
    assert spec.profile is None
    assert spec.heuristic_configuration == artifact.configuration
    direct = execute_suite(tmp_path / "direct", suite=loaded.manifest.suite)
    assert {item.case_id: item.semantic_digest for item in direct.results} == {
        case_id: item.semantic_digest for case_id, item in loaded.results.items()
    }
    path.unlink()
    result = reproduce_case(output / "run", next(iter(loaded.results)))
    assert result.execution_identity_matches and result.semantics_reproduced
    assert main([*arguments, "--candidate-artifact", str(path)]) == EXIT_ERROR


def test_candidate_artifact_preserves_opponents_and_case_ids(tmp_path: Path) -> None:
    from gwent_evaluation.schedule import schedule_suite

    path = tmp_path / "policy.json"
    _ = path.write_text(dump_pretty_json(sample_policy_artifact().to_dict()))
    suite = suite_spec(candidate=heuristic_agent(), opponents=(heuristic_agent(),))
    changed = replace(suite, candidate=candidate_from_artifact(suite.candidate, path))
    assert changed.opponents == suite.opponents
    assert [case.case_id for case in schedule_suite(changed)] == [
        case.case_id for case in schedule_suite(suite)
    ]
    assert changed.candidate.heuristic_configuration == PolicyArtifact.load(path).configuration
