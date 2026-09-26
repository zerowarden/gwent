from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from shutil import copyfile
from typing import NoReturn, cast

import pytest
from gwent_evaluation import EvidencePolicy, SuitePurpose, replay_case
from gwent_evaluation import execution as execution_module
from gwent_evaluation import validation as validation_module
from gwent_evaluation.models import SpecError, SuiteSpec
from gwent_evaluation.provenance import (
    RepositoryProvenance,
    canonical_digest,
    file_digest,
    read_repository_provenance,
)
from gwent_evaluation.records import CorruptRecordError
from gwent_evaluation.reporting import build_run_comparison, build_run_report, load_run
from gwent_evaluation.storage import RunConflictError, RunStore

from tests.evaluation.support import (
    DECK_A,
    REPOSITORY_ROOT,
    execute_suite,
    heuristic_agent,
    suite_spec,
)


def tiny_suite() -> SuiteSpec:
    return suite_spec(action_budget=1, deck_pairs=((DECK_A, DECK_A),))


@pytest.mark.parametrize("changed", ["implementation", "runtime", "manifest", "schedule"])
def test_incompatible_resume_fails_before_executing_missing_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    suite = tiny_suite()
    execution = execute_suite(tmp_path, suite=suite)
    store = RunStore.from_root(execution.root)
    store.result_path(execution.results[0].case_id).unlink()
    if changed == "implementation":
        provenance = store.read_manifest().repository

        def changed_provenance(_root: Path) -> RepositoryProvenance:
            return replace(provenance, implementation_digest="changed")

        monkeypatch.setattr(execution_module, "read_repository_provenance", changed_provenance)
    elif changed == "runtime":
        runtime = store.read_manifest().runtime
        monkeypatch.setattr(
            execution_module,
            "read_runtime_provenance",
            lambda: replace(runtime, python_version="changed"),
        )
    elif changed == "manifest":
        payload = cast(dict[str, object], json.loads(store.manifest_path.read_text()))
        cast(dict[str, object], payload["repository"])["commit"] = "changed"
        _ = store.manifest_path.write_text(json.dumps(payload))
    else:
        lines = store.schedule_path.read_text().splitlines()
        payload = cast(dict[str, object], json.loads(lines[0]))
        payload["environment_seed"] = cast(int, payload["environment_seed"]) + 1
        lines[0] = json.dumps(payload)
        _ = store.schedule_path.write_text("\n".join(lines) + "\n")

    def unexpected(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("Executed a case before validating all persisted inputs")

    monkeypatch.setattr(execution_module, "execute_case", unexpected)
    with pytest.raises((RunConflictError, CorruptRecordError)):
        _ = execute_suite(tmp_path, suite=suite)


def test_intact_result_cannot_be_copied_between_candidate_configurations(tmp_path: Path) -> None:
    suite = tiny_suite()
    a = execute_suite(
        tmp_path,
        run_id="a",
        suite=replace(suite, candidate=heuristic_agent(profile="conservative")),
    )
    b = execute_suite(
        tmp_path, run_id="b", suite=replace(suite, candidate=heuristic_agent(profile="aggressive"))
    )
    assert a.results[0].case_id == b.results[0].case_id
    source, destination = RunStore.from_root(a.root), RunStore.from_root(b.root)
    _ = copyfile(
        source.result_path(a.results[0].case_id), destination.result_path(b.results[0].case_id)
    )
    with pytest.raises(CorruptRecordError, match="execution identity"):
        _ = load_run(b.root)
    with pytest.raises(CorruptRecordError, match="execution identity"):
        _ = execute_suite(
            tmp_path,
            run_id="b",
            suite=replace(suite, candidate=heuristic_agent(profile="aggressive")),
        )


def test_benchmark_requires_resolved_opponent_and_implementation_identity(tmp_path: Path) -> None:
    execution = execute_suite(tmp_path, suite=tiny_suite())
    original = load_run(execution.root)
    # No results: isolate benchmark compatibility from result binding.
    original = replace(original, results={})
    opponent = replace(original.manifest.opponents[0], digest="different-weights")
    changed = replace(original, manifest=replace(original.manifest, opponents=(opponent,)))
    assert not build_run_comparison(original, changed).compatible
    changed = replace(
        original,
        manifest=replace(
            original.manifest,
            repository=replace(
                original.manifest.repository, implementation_digest="other-dirty-tree"
            ),
        ),
    )
    assert not build_run_comparison(original, changed).compatible


@pytest.mark.parametrize(
    "purpose", [SuitePurpose.OPTIMIZE, SuitePurpose.VALIDATION, SuitePurpose.TEST]
)
def test_evidence_runs_require_clean_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: SuitePurpose
) -> None:
    provenance = read_repository_provenance(REPOSITORY_ROOT)

    def dirty_provenance(_root: Path) -> RepositoryProvenance:
        return replace(provenance, dirty=True)

    monkeypatch.setattr(execution_module, "read_repository_provenance", dirty_provenance)
    with pytest.raises(RunConflictError, match="clean checkout"):
        _ = execute_suite(tmp_path, suite=replace(tiny_suite(), purpose=purpose))
    assert not (tmp_path / "run").exists()


def test_diagnostic_run_is_not_optimization_evidence(tmp_path: Path) -> None:
    execution = execute_suite(
        tmp_path, suite=replace(tiny_suite(), purpose=SuitePurpose.DIAGNOSTIC)
    )
    assert not build_run_report(load_run(execution.root)).optimization_evidence


@pytest.mark.parametrize("mutation", ["empty", "truncated", "duplicate", "reordered", "foreign"])
def test_replay_rejects_invalid_trace_even_with_updated_checksums(
    tmp_path: Path, mutation: str
) -> None:
    suite = suite_spec(deck_pairs=((DECK_A, DECK_A),))
    execution = execute_suite(tmp_path, suite=suite)
    result = execution.results[0]
    store = RunStore.from_root(execution.root)
    path = store.trajectory_path(result.case_id)
    payload = cast(dict[str, object], json.loads(path.read_text()))
    steps = cast(list[dict[str, object]], payload["steps"])
    if mutation == "empty":
        payload["steps"] = []
    elif mutation == "truncated":
        _ = steps.pop()
    elif mutation == "duplicate":
        steps[1]["index"] = 1
    elif mutation == "reordered":
        steps[1], steps[2] = steps[2], steps[1]
    else:
        payload["execution_identity"] = "another-execution"
    _ = path.write_text(json.dumps(payload))
    store.write_result(
        replace(result, evidence=replace(result.evidence, trajectory_digest=file_digest(path)))
    )
    with pytest.raises(CorruptRecordError):
        _ = replay_case(execution.root, result.case_id)


def test_summary_and_diagnostic_paths_have_identical_semantics_without_evidence_files(
    tmp_path: Path,
) -> None:
    suite = suite_spec(deck_pairs=((DECK_A, DECK_A),))
    summary = execute_suite(
        tmp_path, suite=suite, run_id="summary", evidence_policy=EvidencePolicy.NONE
    )
    rich = execute_suite(tmp_path, suite=suite, run_id="rich", evidence_policy=EvidencePolicy.ALL)
    assert [r.semantic_digest for r in summary.results] == [r.semantic_digest for r in rich.results]
    assert list((summary.root / "evidence").iterdir()) == []
    assert all(r.evidence.samples_path is None and r.decision_seconds > 0 for r in summary.results)


@pytest.mark.parametrize(
    "field,value",
    [
        ("opponents", ()),
        ("seeds", (1, 1)),
        ("deck_pairs", ()),
        ("action_budget", 0),
        ("observation_contract_version", 999),
    ],
)
def test_python_suite_construction_enforces_domain_invariants(field: str, value: object) -> None:
    with pytest.raises(SpecError):
        _ = replace(tiny_suite(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("accepted_transitions", -1),
        ("decision_seconds", -1.0),
        ("execution_seconds", float("inf")),
        ("candidate_score", 1.0),
    ],
)
def test_result_domain_validation_is_shared(tmp_path: Path, field: str, value: object) -> None:
    execution = execute_suite(tmp_path, suite=tiny_suite())
    with pytest.raises(ValueError):
        _ = replace(execution.results[0], **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_agent_id", "foreign-candidate"),
        ("opponent_agent_id", "foreign-opponent"),
        ("candidate_seat", "p2"),
        ("requested_starting_player", "p2"),
        ("environment_seed", -1),
        ("observation_contract_version", 999),
    ],
)
def test_checksums_do_not_replace_result_binding(tmp_path: Path, field: str, value: object) -> None:
    from gwent_evaluation.provenance import canonical_digest

    from tests.evaluation.support import read_json_object, write_json_object

    run = execute_suite(tmp_path, suite=tiny_suite())
    store = RunStore.from_root(run.root)
    path = store.result_path(run.results[0].case_id)
    payload = dict(read_json_object(path))
    del payload["record_digest"]
    assert payload[field] != value
    payload[field] = value
    write_json_object(path, {**payload, "record_digest": canonical_digest(payload)})
    with pytest.raises(CorruptRecordError):
        _ = store.read_result(run.results[0].case_id)


def test_intact_foreign_trajectory_is_rejected_even_when_its_digest_is_recorded(
    tmp_path: Path,
) -> None:
    suite = tiny_suite()
    first = execute_suite(tmp_path, run_id="first", suite=suite)
    second = execute_suite(
        tmp_path, run_id="second", suite=replace(suite, candidate=heuristic_agent())
    )
    result = second.results[0]
    source, destination = RunStore.from_root(first.root), RunStore.from_root(second.root)
    path = destination.trajectory_path(result.case_id)
    _ = copyfile(source.trajectory_path(result.case_id), path)
    destination.write_result(
        replace(result, evidence=replace(result.evidence, trajectory_digest=file_digest(path)))
    )
    with pytest.raises(CorruptRecordError, match="another execution"):
        _ = replay_case(second.root, result.case_id)


def test_identity_processing_scales_with_manifests_not_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark_sizes: list[int] = []
    execution_hashes: list[str] = []

    def track_identity(payload: object) -> str:
        digest = canonical_digest(payload)
        if isinstance(payload, Mapping):
            fields = cast(Mapping[str, object], payload)
            if "planned_case_ids" in fields:
                benchmark_sizes.append(len(cast(tuple[str, ...], fields["planned_case_ids"])))
            if "benchmark" in fields:
                execution_hashes.append(cast(str, fields["benchmark"]))
        return digest

    monkeypatch.setattr(validation_module, "canonical_digest", track_identity)
    counts: list[tuple[int, ...]] = []
    for seed_count in (1, 4):
        suite = replace(tiny_suite(), seeds=tuple(range(seed_count)))
        run_counts: list[int] = []
        for _attempt in range(2):
            benchmark_sizes.clear()
            execution_hashes.clear()
            execution = execute_suite(tmp_path / str(seed_count), suite=suite)
            run_counts.append(len(benchmark_sizes))
            assert len(benchmark_sizes) == len(execution_hashes)
            assert all(size == len(execution.results) for size in benchmark_sizes)
        benchmark_sizes.clear()
        execution_hashes.clear()
        loaded = load_run(tmp_path / str(seed_count) / "run")
        validation_module.validate_loaded_run(loaded)
        _ = build_run_report(loaded)
        _ = build_run_comparison(loaded, loaded)
        assert len(benchmark_sizes) == len(execution_hashes) == 1
        counts.append(tuple(run_counts))

    # Execution, evidence binding, resume, and reporting each reuse run identities.
    assert counts[0] == counts[1]
    assert all(0 < count <= 2 for count in counts[0])
