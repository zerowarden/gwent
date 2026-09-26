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
    load_agent_catalog,
    load_suite_catalog,
    parse_agent_spec,
    parse_suite_spec,
)


def _stub_resolver(reference: str) -> AgentSpec:
    return parse_agent_spec(
        {"schema_version": SUPPORTED_SCHEMA_VERSION, "agent_id": reference, "family": "random"},
        context=reference,
    )


def _agent_payload(agent_id: str = "random", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "agent_id": agent_id,
        "family": "random",
    }
    payload.update(overrides)
    return payload


def _suite_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "suite_id": "smoke-v1",
        "purpose": "smoke",
        "candidate": "heuristic-neutral",
        "opponents": ["random", "greedy"],
        "deck_pairs": [["monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict"]],
        "seeds": [3, 11],
        "scheduling": "balanced",
        "action_budget": 512,
    }
    payload.update(overrides)
    return payload


def _parse_suite(payload: object, *, resolve_agent: AgentResolver = _stub_resolver) -> SuiteSpec:
    return parse_suite_spec(payload, resolve_agent=resolve_agent, context="suite catalog entry")


def _write_json(path: Path, payload: object) -> Path:
    _ = path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parse_suite_resolves_catalog_agent_ids() -> None:
    suite = _parse_suite(_suite_payload())

    assert suite.schema_version == SUPPORTED_SCHEMA_VERSION
    assert suite.suite_id == "smoke-v1"
    assert suite.purpose is SuitePurpose.SMOKE
    assert suite.candidate.agent_id == "heuristic-neutral"
    assert [agent.agent_id for agent in suite.opponents] == ["random", "greedy"]
    assert suite.deck_pairs == (
        ("monsters_muster_swarm_strict", "nilfgaard_spy_medic_control_strict"),
    )
    assert suite.seeds == (3, 11)
    assert suite.scheduling is SchedulingPolicy.BALANCED
    assert suite.action_budget == 512
    assert suite.observation_contract_version == OBSERVATION_CONTRACT_VERSION


def test_agent_catalog_loads_entries_and_rejects_duplicate_ids(tmp_path: Path) -> None:
    agents_path = _write_json(
        tmp_path / "agents.json",
        {
            "schema_version": 1,
            "agents": [
                _agent_payload("greedy", family="greedy"),
                _agent_payload("heuristic-neutral", family="heuristic", profile="neutral"),
            ],
        },
    )

    catalog = load_agent_catalog(agents_path)

    assert set(catalog) == {"greedy", "heuristic-neutral"}
    assert catalog["heuristic-neutral"].family is BotFamily.HEURISTIC
    assert catalog["heuristic-neutral"].profile == "neutral"

    duplicate_path = _write_json(
        tmp_path / "duplicates.json",
        {"schema_version": 1, "agents": [_agent_payload("greedy"), _agent_payload("greedy")]},
    )
    with pytest.raises(SpecError, match="duplicate agent id"):
        _ = load_agent_catalog(duplicate_path)


def test_suite_catalog_resolves_agent_ids_and_rejects_unknown_ids(tmp_path: Path) -> None:
    agents_path = _write_json(
        tmp_path / "agents.json",
        {"schema_version": 1, "agents": [_agent_payload()]},
    )
    agents = load_agent_catalog(agents_path)
    suites_path = _write_json(
        tmp_path / "suites.json",
        {
            "schema_version": 1,
            "suites": [_suite_payload(candidate="random", opponents=["random"])],
        },
    )

    catalog = load_suite_catalog(suites_path, agents=agents)

    assert catalog["smoke-v1"].candidate.agent_id == "random"

    missing_path = _write_json(
        tmp_path / "missing.json",
        {"schema_version": 1, "suites": [_suite_payload(candidate="missing")]},
    )
    with pytest.raises(SpecError, match="cannot resolve agent reference"):
        _ = load_suite_catalog(missing_path, agents=agents)


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
        ("opponents", ["random", "random"]),
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
    path = tmp_path / "agents.json"
    _ = path.write_text(
        '{"schema_version": 1, "agents": [{"schema_version": 1, "agent_id": "a", '
        + '"family": "random"}], "extra": NaN}',
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="non-finite"):
        _ = load_agent_catalog(path)


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    _ = path.write_text(
        '{"schema_version": 1, "agents": [], "agents": []}',
        encoding="utf-8",
    )

    with pytest.raises(SpecError, match="duplicate key"):
        _ = load_agent_catalog(path)
