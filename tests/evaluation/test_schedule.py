from __future__ import annotations

from pathlib import Path

import pytest
from gwent_evaluation import (
    AgentSpec,
    ScheduleError,
    SeedNamespace,
    SuiteSpec,
    derive_seed,
    load_suite_spec,
    schedule_suite,
)

from tests.evaluation.support import (
    DECK_A,
    DECK_B,
    heuristic_agent,
    suite_spec,
)

VALID_SUITE_PATH = Path(__file__).parent / "fixtures" / "specs" / "suites" / "smoke-valid.json"


def _agent(agent_id: str, *, profile: str | None = "neutral") -> AgentSpec:
    return heuristic_agent(agent_id, profile=profile)


def _suite(
    *,
    candidate: AgentSpec | None = None,
    opponents: tuple[AgentSpec, ...] | None = None,
    deck_pairs: tuple[tuple[str, str], ...] = ((DECK_A, DECK_B),),
    seeds: tuple[int, ...] = (3,),
) -> SuiteSpec:
    return suite_spec(
        suite_id="schedule-test",
        candidate=candidate,
        opponents=opponents,
        deck_pairs=deck_pairs,
        seeds=seeds,
    )


def test_asymmetric_deck_block_has_eight_legs() -> None:
    matches = schedule_suite(_suite())

    assert len(matches) == 8


def test_identical_deck_block_has_four_legs() -> None:
    matches = schedule_suite(_suite(deck_pairs=((DECK_A, DECK_A),)))

    assert len(matches) == 4


def test_legs_cover_every_seat_starter_and_deck_combination() -> None:
    matches = schedule_suite(_suite())

    combinations = {
        (
            match.candidate_seat,
            match.requested_starting_player,
            match.candidate_deck_id,
            match.opponent_deck_id,
        )
        for match in matches
    }

    assert len(combinations) == 8
    assert len({match.case_id for match in matches}) == 8


def test_scheduling_is_stable() -> None:
    suite = _suite(seeds=(3, 11))

    assert schedule_suite(suite) == schedule_suite(suite)


def test_candidate_configuration_does_not_change_setup_identities() -> None:
    neutral = schedule_suite(_suite(candidate=_agent("candidate", profile="neutral")))
    conservative = schedule_suite(_suite(candidate=_agent("candidate", profile="conservative")))

    assert tuple(match.case_id for match in neutral) == tuple(
        match.case_id for match in conservative
    )
    assert tuple(match.environment_seed for match in neutral) == tuple(
        match.environment_seed for match in conservative
    )
    assert neutral[0].candidate_agent.profile == "neutral"
    assert conservative[0].candidate_agent.profile == "conservative"


def test_changing_root_seed_changes_streams() -> None:
    first = schedule_suite(_suite(seeds=(3,)))
    second = schedule_suite(_suite(seeds=(11,)))

    assert {match.case_id for match in first}.isdisjoint({match.case_id for match in second})
    assert {match.environment_seed for match in first}.isdisjoint(
        {match.environment_seed for match in second}
    )


def test_duplicate_cases_are_rejected() -> None:
    duplicated = _agent("opponent")

    with pytest.raises(ScheduleError, match="Duplicate scheduled case id"):
        _ = schedule_suite(_suite(opponents=(duplicated, duplicated)))


def test_seed_namespaces_are_independent() -> None:
    environment = derive_seed(namespace=SeedNamespace.ENVIRONMENT, identity="case", root_seed=3)
    candidate = derive_seed(namespace=SeedNamespace.CANDIDATE_POLICY, identity="case", root_seed=3)
    opponent = derive_seed(namespace=SeedNamespace.OPPONENT_POLICY, identity="case", root_seed=3)

    assert len({environment, candidate, opponent}) == 3
    assert (
        derive_seed(namespace=SeedNamespace.ENVIRONMENT, identity="case", root_seed=3)
        == environment
    )


def test_smoke_fixture_schedules_balanced_legs() -> None:
    suite = load_suite_spec(VALID_SUITE_PATH)

    matches = schedule_suite(suite)

    # 2 opponents * 1 asymmetric deck pair * 2 seeds * 8 legs.
    assert len(matches) == 32
    assert len({match.case_id for match in matches}) == 32
