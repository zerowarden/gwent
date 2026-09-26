from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from gwent_evaluation import execution as execution_module
from gwent_evaluation.cli import EXIT_DIVERGENCE, EXIT_ERROR, EXIT_OK, main
from gwent_evaluation.provenance import read_runtime_provenance

DECK_A = "monsters_muster_swarm_strict"
DECK_B = "nilfgaard_spy_medic_control_strict"


def _write_tiny_catalogs(
    tmp_path: Path,
    *,
    suite_id: str,
    deck_pairs: list[list[str]],
) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    agents_path = tmp_path / "agents.json"
    _ = agents_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agents": [
                    {
                        "schema_version": 1,
                        "agent_id": "heuristic-neutral",
                        "family": "heuristic",
                        "profile": "neutral",
                    },
                    {"schema_version": 1, "agent_id": "random", "family": "random"},
                ],
            }
        ),
        encoding="utf-8",
    )
    suites_path = tmp_path / "suites.json"
    _ = suites_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suites": [
                    {
                        "schema_version": 1,
                        "suite_id": suite_id,
                        "purpose": "smoke",
                        "candidate": "heuristic-neutral",
                        "opponents": ["random"],
                        "deck_pairs": deck_pairs,
                        "seeds": [3],
                        "scheduling": "balanced",
                        "action_budget": 512,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return suites_path, agents_path


def _run_arguments(
    suites_path: Path,
    agents_path: Path,
    *,
    suite_id: str,
    output_root: Path,
    run_id: str = "run",
) -> list[str]:
    return [
        "run",
        str(suites_path),
        "--agents-catalog",
        str(agents_path),
        "--suite",
        suite_id,
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--evidence-policy",
        "all",
    ]


def _first_case_id(run_root: Path) -> str:
    first_line = (run_root / "schedule.jsonl").read_text(encoding="utf-8").splitlines()[0]
    return str(cast(dict[str, object], json.loads(first_line))["case_id"])


def test_run_report_replay_and_compare_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    suites_path, agents_path = _write_tiny_catalogs(
        tmp_path, suite_id="cli-tiny", deck_pairs=[[DECK_A, DECK_B]]
    )
    output_root = tmp_path / "out"

    run_exit = main(
        _run_arguments(suites_path, agents_path, suite_id="cli-tiny", output_root=output_root)
    )

    run_root = output_root / "run"
    assert run_exit == EXIT_OK
    assert (run_root / "report.json").is_file()
    assert (run_root / "report.md").is_file()
    assert main(["report", str(run_root)]) == EXIT_OK

    case_id = _first_case_id(run_root)
    assert main(["replay", str(run_root), "--case", case_id]) == EXIT_OK
    assert main(["replay", str(run_root), "--case", case_id, "--reproduce"]) == EXIT_OK
    assert "execution_identity_matches=yes semantics_reproduced=yes" in capsys.readouterr().out
    runtime = read_runtime_provenance()
    monkeypatch.setattr(
        execution_module,
        "read_runtime_provenance",
        lambda: replace(runtime, python_version="drift"),
    )
    assert main(["replay", str(run_root), "--case", case_id, "--reproduce"]) == EXIT_OK
    assert "execution_identity_matches=no semantics_reproduced=yes" in capsys.readouterr().out
    assert main(["compare", str(run_root), str(run_root)]) == EXIT_OK


def test_run_resumes_an_existing_run(tmp_path: Path) -> None:
    suites_path, agents_path = _write_tiny_catalogs(
        tmp_path, suite_id="cli-tiny", deck_pairs=[[DECK_A, DECK_B]]
    )
    arguments = _run_arguments(
        suites_path, agents_path, suite_id="cli-tiny", output_root=tmp_path / "out"
    )

    assert main(arguments) == EXIT_OK
    assert main(arguments) == EXIT_OK


def test_incompatible_runs_exit_nonzero(tmp_path: Path) -> None:
    reference_catalogs = _write_tiny_catalogs(
        tmp_path / "reference", suite_id="cli-reference", deck_pairs=[[DECK_A, DECK_B]]
    )
    candidate_catalogs = _write_tiny_catalogs(
        tmp_path / "candidate", suite_id="cli-candidate", deck_pairs=[[DECK_A, DECK_A]]
    )
    reference = tmp_path / "reference-out"
    candidate = tmp_path / "candidate-out"
    _ = main(_run_arguments(*reference_catalogs, suite_id="cli-reference", output_root=reference))
    _ = main(_run_arguments(*candidate_catalogs, suite_id="cli-candidate", output_root=candidate))

    exit_code = main(["compare", str(reference / "run"), str(candidate / "run")])

    assert exit_code == EXIT_DIVERGENCE


def test_invalid_inputs_exit_with_error(tmp_path: Path) -> None:
    assert main(["run", str(tmp_path / "missing.json")]) == EXIT_ERROR

    suites_path, agents_path = _write_tiny_catalogs(
        tmp_path, suite_id="cli-tiny", deck_pairs=[[DECK_A, DECK_B]]
    )
    output_root = tmp_path / "out"
    _ = main(_run_arguments(suites_path, agents_path, suite_id="cli-tiny", output_root=output_root))

    assert main(["replay", str(output_root / "run"), "--case", "missing-case"]) == EXIT_ERROR
