from __future__ import annotations

from pathlib import Path

from gwent_evaluation import (
    load_agent_catalog,
    load_suite_catalog,
    schedule_suite,
)

from tests.evaluation.support import REPOSITORY_ROOT

EXPERIMENTS = REPOSITORY_ROOT / "experiments"
AGENTS_CATALOG = EXPERIMENTS / "agents.json"
SUITES_CATALOG = EXPERIMENTS / "suites.json"

CORE_PARTITIONS = ("core-optimize-v1", "core-validation-v1", "core-test-v1")
_RUNTIME_ASSET_NAMES = {"cards.yaml", "leaders.yaml", "sample_decks.yaml"}


def test_experiment_catalogs_declare_expected_participants_and_suites() -> None:
    agents = load_agent_catalog(AGENTS_CATALOG)
    suites = load_suite_catalog(SUITES_CATALOG, agents=agents)

    assert set(agents) == {
        "random",
        "greedy",
        "heuristic-neutral",
        "heuristic-conservative",
        "heuristic-aggressive",
        "search-neutral",
    }
    assert set(suites) == {
        "smoke-v1",
        "core-optimize-v1",
        "core-validation-v1",
        "core-test-v1",
        "search-diagnostic-v1",
    }


def test_core_partitions_do_not_overlap_in_seeds_or_cases() -> None:
    agents = load_agent_catalog(AGENTS_CATALOG)
    suites = load_suite_catalog(SUITES_CATALOG, agents=agents)

    declared_seeds: dict[int, str] = {}
    case_ids: dict[str, str] = {}
    for suite_id in CORE_PARTITIONS:
        suite = suites[suite_id]
        for seed in suite.seeds:
            assert seed not in declared_seeds, f"seed {seed} shared by {suite_id}"
            declared_seeds[seed] = suite_id
        for match in schedule_suite(suite):
            assert match.case_id not in case_ids, f"case {match.case_id} shared by {suite_id}"
            case_ids[match.case_id] = suite_id

    # 12 optimize blocks + 12 validation blocks + 18 test blocks, 8 legs each.
    assert len(case_ids) == (12 + 12 + 18) * 8


def test_benchmarks_do_not_copy_runtime_assets() -> None:
    copied = sorted(
        path.name
        for path in Path(EXPERIMENTS).rglob("*")
        if path.is_file() and path.name in _RUNTIME_ASSET_NAMES
    )

    assert copied == []
