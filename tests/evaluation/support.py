from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from gwent_engine.ai.observations import OBSERVATION_CONTRACT_VERSION
from gwent_evaluation import (
    SUPPORTED_SCHEMA_VERSION,
    AgentSpec,
    BotFamily,
    CaseStatus,
    EvidencePolicy,
    RunExecution,
    SchedulingPolicy,
    ScoredCase,
    SuitePurpose,
    SuiteSpec,
    execute_run,
)
from gwent_shared.extract import expect_mapping, expect_sequence, expect_str

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
METRICS_FIXTURES = Path(__file__).parent / "fixtures" / "metrics"

DECK_A = "monsters_muster_swarm_strict"
DECK_B = "nilfgaard_spy_medic_control_strict"


@dataclass(frozen=True, slots=True)
class MetricsFixture:
    """A hand-authored metrics input plus its exact expected arithmetic."""

    description: str
    cases: tuple[ScoredCase, ...]
    reference: tuple[ScoredCase, ...]
    candidate: tuple[ScoredCase, ...]
    expected: Mapping[str, object]


def load_metrics_fixture(name: str) -> MetricsFixture:
    document = read_json_object(METRICS_FIXTURES / name)
    return MetricsFixture(
        description=expect_str(
            document["description"],
            context="description",
            error_factory=ValueError,
        ),
        cases=_fixture_cases(document.get("cases")),
        reference=_fixture_cases(document.get("reference")),
        candidate=_fixture_cases(document.get("candidate")),
        expected=expect_mapping(
            document["expected"],
            context="expected",
            error_factory=ValueError,
        ),
    )


def _fixture_cases(raw: object | None) -> tuple[ScoredCase, ...]:
    if raw is None:
        return ()
    cases: list[ScoredCase] = []
    for index, entry in enumerate(expect_sequence(raw, context="cases", error_factory=ValueError)):
        context = f"cases[{index}]"
        mapping = expect_mapping(entry, context=context, error_factory=ValueError)
        cases.append(
            ScoredCase(
                case_id=expect_str(
                    mapping["case_id"],
                    context=f"{context}.case_id",
                    error_factory=ValueError,
                ),
                block_id=expect_str(
                    mapping["block_id"],
                    context=f"{context}.block_id",
                    error_factory=ValueError,
                ),
                status=CaseStatus(
                    expect_str(
                        mapping["status"],
                        context=f"{context}.status",
                        error_factory=ValueError,
                    )
                ),
                score=_fixture_score(mapping.get("score"), context=context),
                strata=_fixture_strata(mapping.get("strata"), context=context),
            )
        )
    return tuple(cases)


def _fixture_score(raw: object | None, *, context: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{context} score must be numeric.")
    return float(raw)


def _fixture_strata(raw: object | None, *, context: str) -> dict[str, str]:
    if raw is None:
        return {}
    mapping = expect_mapping(raw, context=f"{context}.strata", error_factory=ValueError)
    return {
        str(key): expect_str(
            value,
            context=f"{context}.strata[{key!r}]",
            error_factory=ValueError,
        )
        for key, value in mapping.items()
    }


def agent_spec(
    agent_id: str = "agent",
    *,
    family: BotFamily,
    profile: str | None = None,
) -> AgentSpec:
    return AgentSpec(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        agent_id=agent_id,
        family=family,
        profile=profile,
    )


def greedy_agent(agent_id: str = "candidate") -> AgentSpec:
    return agent_spec(agent_id, family=BotFamily.GREEDY)


def heuristic_agent(agent_id: str = "candidate", *, profile: str | None = None) -> AgentSpec:
    return agent_spec(agent_id, family=BotFamily.HEURISTIC, profile=profile)


def suite_spec(
    *,
    suite_id: str = "evaluation-test",
    candidate: AgentSpec | None = None,
    opponents: tuple[AgentSpec, ...] | None = None,
    deck_pairs: tuple[tuple[str, str], ...] = ((DECK_A, DECK_B),),
    seeds: tuple[int, ...] = (3,),
    action_budget: int = 512,
) -> SuiteSpec:
    return SuiteSpec(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        suite_id=suite_id,
        purpose=SuitePurpose.SMOKE,
        candidate=candidate or greedy_agent(),
        opponents=opponents or (greedy_agent("opponent"),),
        deck_pairs=deck_pairs,
        seeds=seeds,
        scheduling=SchedulingPolicy.BALANCED,
        action_budget=action_budget,
        observation_contract_version=OBSERVATION_CONTRACT_VERSION,
    )


def execute_suite(
    output_root: Path,
    *,
    suite: SuiteSpec | None = None,
    run_id: str = "run",
    evidence_policy: EvidencePolicy = EvidencePolicy.ALL,
) -> RunExecution:
    return execute_run(
        suite=suite or suite_spec(),
        run_id=run_id,
        output_root=output_root,
        repository_root=REPOSITORY_ROOT,
        evidence_policy=evidence_policy,
    )


def read_json_object(path: Path) -> Mapping[str, object]:
    payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    return expect_mapping(payload, context=str(path), error_factory=ValueError)


def write_json_object(path: Path, payload: Mapping[str, object]) -> None:
    _ = path.write_text(json.dumps(payload), encoding="utf-8")


def int_field(mapping: Mapping[str, object], field: str) -> int:
    value = mapping[field]
    assert isinstance(value, int)
    return value


def bool_field(mapping: Mapping[str, object], field: str) -> bool:
    value = mapping[field]
    assert isinstance(value, bool)
    return value


def float_field(mapping: Mapping[str, object], field: str) -> float:
    value = mapping[field]
    assert isinstance(value, (int, float))
    return float(value)


def str_field(mapping: Mapping[str, object], field: str) -> str:
    value = mapping[field]
    assert isinstance(value, str)
    return value
