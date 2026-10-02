"""Ordinary evaluation tests may inspect holdout definitions, never their outcomes."""

from collections.abc import Mapping
from typing import cast

import pytest
from gwent_evaluation.models import RunManifest, ScheduledMatch, SuitePurpose
from gwent_evaluation.specs import load_agent_catalog, load_suite_catalog
from gwent_evaluation.storage import RunStore, read_record_mapping
from gwent_evaluation.validation import LoadedRun

from tests.evaluation.support import REPOSITORY_ROOT


@pytest.fixture(scope="session")
def registered_holdouts() -> frozenset[str]:
    root = REPOSITORY_ROOT
    agents = load_agent_catalog(root / "experiments/agents.json")
    suites = load_suite_catalog(root / "experiments/suites.json", agents=agents)
    inline: set[str] = set()
    for path in (root / "experiments/tuning").glob("*.json"):
        definition = read_record_mapping(path)
        if definition.get("schema_version") == 2 and "suites" in definition:
            for suite in cast(Mapping[str, object], definition["suites"]).values():
                if isinstance(suite, dict):
                    item = cast(Mapping[str, object], suite)
                    if item.get("purpose") == "test":
                        inline.add(cast(str, item["suite_id"]))
    return frozenset(
        {suite.suite_id for suite in suites.values() if suite.purpose is SuitePurpose.TEST} | inline
    )


@pytest.fixture(autouse=True)
def protect_registered_holdouts(
    registered_holdouts: frozenset[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare = RunStore.prepare
    read_manifest = RunStore.read_manifest

    def check(manifest: RunManifest) -> None:
        if manifest.suite.suite_id in registered_holdouts:
            raise AssertionError("CI cannot execute or inspect registered held-out outcomes.")

    def guarded_prepare(
        store: RunStore, manifest: RunManifest, *, matches: tuple[ScheduledMatch, ...]
    ) -> LoadedRun:
        check(manifest)
        return prepare(store, manifest, matches=matches)

    def guarded_manifest(store: RunStore) -> RunManifest:
        manifest = read_manifest(store)
        check(manifest)
        return manifest

    monkeypatch.setattr(RunStore, "prepare", guarded_prepare)
    monkeypatch.setattr(RunStore, "read_manifest", guarded_manifest)
