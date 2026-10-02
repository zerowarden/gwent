from __future__ import annotations

from pathlib import Path
from typing import cast

from gwent_evaluation import load_agent_catalog, load_suite_catalog
from gwent_evaluation.schedule import schedule_suite
from gwent_shared.json_payloads import canonical_digest

from tests.evaluation.support import REPOSITORY_ROOT, read_json_object

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
        "weights-optimize",
        "weights-validation",
        "weights-test",
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


def test_expanded_weight_suites_preserve_existing_presets_and_disjoint_partitions() -> None:
    document = read_json_object(SUITES_CATALOG)
    entries = cast(list[dict[str, object]], document["suites"])
    originals = [entry for entry in entries if not str(entry["suite_id"]).startswith("weights-")]
    assert (
        canonical_digest(originals)
        == "sha256:f19b903c0ad52ae3501ec65cd5cf9a55cfa45cbd5c7ae3bbeebd93709d94e628"
    )
    suites = load_suite_catalog(SUITES_CATALOG, agents=load_agent_catalog(AGENTS_CATALOG))
    roots: set[int] = set()
    for purpose, count in (("optimize", 1024), ("validation", 2048), ("test", 4096)):
        suite = suites[f"weights-{purpose}"]
        assert suite.purpose.value == purpose
        assert not roots.intersection(suite.seeds)
        roots.update(suite.seeds)
        assert tuple(agent.agent_id for agent in suite.opponents) == (
            "greedy",
            "heuristic-neutral",
            "heuristic-conservative",
            "heuristic-aggressive",
        )
        assert len(schedule_suite(suite)) == count


def test_benchmarks_do_not_copy_runtime_assets() -> None:
    copied = sorted(
        path.name
        for path in Path(EXPERIMENTS).rglob("*")
        if path.is_file() and path.name in _RUNTIME_ASSET_NAMES
    )

    assert copied == []
