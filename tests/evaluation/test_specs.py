from __future__ import annotations

import json
from pathlib import Path

import pytest
from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_evaluation import (
    SUPPORTED_SCHEMA_VERSION,
    AgentResolver,
    AgentSpec,
    BotFamily,
    SchedulingPolicy,
    SpecError,
    SuitePurpose,
    SuiteSpec,
    load_agent_spec,
    load_suite_spec,
    parse_agent_spec,
    parse_suite_spec,
)

FIXTURES = Path(__file__).parent / "fixtures" / "specs"
AGENTS_DIR = FIXTURES / "agents"
VALID_SUITE_PATH = FIXTURES / "suites" / "smoke-valid.json"


def _stub_resolver(reference: str) -> AgentSpec:
    return parse_agent_spec(
        {"schema_version": SUPPORTED_SCHEMA_VERSION, "agent_id": reference, "family": "random"},
        context=reference,
    )


def _suite_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "suite_id": "smoke-v1",
        "purpose": "smoke",
        "candidate": "../agents/heuristic-neutral.json",
        "opponents": ["../agents/random.json", "../agents/greedy.json"],
        "deck_pairs": [["monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict"]],
        "seeds": [3, 11],
        "scheduling": "balanced",
        "action_budget": 512,
    }
    payload.update(overrides)
    return payload


def _parse_suite(payload: object, *, resolve_agent: AgentResolver = _stub_resolver) -> SuiteSpec:
    return parse_suite_spec(payload, resolve_agent=resolve_agent, context="suite.json")


def test_load_valid_suite_resolves_relative_agent_references() -> None:
    suite = load_suite_spec(VALID_SUITE_PATH)

    assert suite.schema_version == SUPPORTED_SCHEMA_VERSION
    assert suite.suite_id == "smoke-v1"
    assert suite.purpose is SuitePurpose.SMOKE
    assert suite.candidate == load_agent_spec(AGENTS_DIR / "heuristic-neutral.json")
    assert suite.candidate.family is BotFamily.HEURISTIC
    assert suite.candidate.profile == "neutral"
    assert [agent.agent_id for agent in suite.opponents] == ["random", "greedy"]
    assert suite.deck_pairs == (
        ("monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict"),
    )
    assert suite.seeds == (3, 11)
    assert suite.scheduling is SchedulingPolicy.BALANCED
    assert suite.action_budget == 512
    assert suite.observation_contract_version == OBSERVATION_CONTRACT_VERSION


@pytest.mark.parametrize("profile_id", ["does-not-exist", "tempo", "baseline", "aggro"])
def test_rejects_unrecognized_profile_ids(profile_id: str) -> None:
    with pytest.raises(SpecError, match="not a recognized profile"):
        _ = parse_agent_spec(
            {
                "schema_version": SUPPORTED_SCHEMA_VERSION,
                "agent_id": "heuristic-unknown",
                "family": "heuristic",
                "profile": profile_id,
            },
            context="agent.json",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("purpose", "unknown"),
        ("scheduling", "random"),
        ("action_budget", 0),
        ("action_budget", -1),
        ("seeds", []),
        ("seeds", [3, 3]),
        ("opponents", []),
        ("opponents", ["a.json", "a.json"]),
        ("deck_pairs", []),
        ("deck_pairs", [["only-one"]]),
        ("deck_pairs", [["a", "b"], ["a", "b"]]),
        ("candidate", ""),
        ("suite_id", ""),
    ],
)
def test_rejects_invalid_suite_fields(field: str, value: object) -> None:
    with pytest.raises(SpecError):
        _ = _parse_suite(_suite_payload(**{field: value}))


def test_rejects_unknown_suite_field() -> None:
    with pytest.raises(SpecError, match="unknown field"):
        _ = _parse_suite(_suite_payload(extra_option=True))


def test_suite_cannot_declare_observation_contract_version() -> None:
    with pytest.raises(SpecError, match="observation_contract_version"):
        _ = _parse_suite(_suite_payload(observation_contract_version=99))


def test_rejects_unknown_agent_field() -> None:
    with pytest.raises(SpecError, match="unknown field"):
        _ = parse_agent_spec(
            {
                "schema_version": SUPPORTED_SCHEMA_VERSION,
                "agent_id": "random",
                "family": "random",
                "config": {},
            },
            context="agent.json",
        )


def test_rejects_profile_override_for_profileless_family() -> None:
    with pytest.raises(SpecError, match="does not support a profile override"):
        _ = parse_agent_spec(
            {
                "schema_version": SUPPORTED_SCHEMA_VERSION,
                "agent_id": "random",
                "family": "random",
                "profile": "neutral",
            },
            context="agent.json",
        )


def test_rejects_unsupported_agent_schema_version() -> None:
    with pytest.raises(SpecError, match="schema_version"):
        _ = parse_agent_spec(
            {"schema_version": 99, "agent_id": "random", "family": "random"},
            context="agent.json",
        )


def test_rejects_non_finite_json_constant(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    _ = path.write_text('{"schema_version": 1, "seeds": [NaN]}', encoding="utf-8")

    with pytest.raises(SpecError, match="non-finite"):
        _ = load_suite_spec(path)


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    _ = path.write_text(
        '{"schema_version": 1, "agent_id": "a", "agent_id": "b", "family": "random"}',
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="duplicate key"):
        _ = load_agent_spec(path)


def test_rejects_unresolvable_agent_reference(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    _ = suite_path.write_text(
        json.dumps(_suite_payload(candidate="missing.json")),
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="cannot resolve agent reference"):
        _ = load_suite_spec(suite_path)
