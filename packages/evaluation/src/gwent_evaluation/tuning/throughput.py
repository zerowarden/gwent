"""Measure the production game runner at range-suite sizes using diagnostic seeds."""

from __future__ import annotations

import argparse
import os
import platform
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import cast

from gwent_engine.ai.heuristic_configuration import HeuristicConfiguration

from gwent_evaluation.execution import EvidencePolicy, execute_run, validate_worker_count
from gwent_evaluation.html_report import chart, table
from gwent_evaluation.models import SpecError, SuitePurpose, SuiteSpec
from gwent_evaluation.progress import TerminalProgress, advance, stage
from gwent_evaluation.provenance import canonical_digest, default_repository_root
from gwent_evaluation.records import record_to_dict
from gwent_evaluation.storage import RunConflictError
from gwent_evaluation.tuning.range_reports import write_report
from gwent_evaluation.tuning.specs import load_study_spec
from gwent_evaluation.tuning.storage import StudyStore, read_checked_document


def _hardware() -> dict[str, object]:
    cpu_info = Path("/proc/cpuinfo")
    model = platform.processor()
    if cpu_info.exists():
        model = next(
            (
                line.split(":", 1)[1].strip()
                for line in cpu_info.read_text().splitlines()
                if line.startswith("model name")
            ),
            model,
        )
    return {
        "cpu_model": model,
        "logical_cpus": os.cpu_count(),
        "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "python": platform.python_version(),
        "memory_kib": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal:")
            ),
            None,
        )
        if Path("/proc/meminfo").exists()
        else None,
    }


def workload_suite(
    suite: SuiteSpec, configuration: HeuristicConfiguration, *, name: str
) -> SuiteSpec:
    """Keep production game counts/agents/decks/budgets, bind separate diagnostic seeds."""
    seed_base = 470001 if name == "screening" else 480001
    return replace(
        suite,
        suite_id=f"range-throughput-{name}",
        purpose=SuitePurpose.SMOKE,
        seeds=tuple(seed_base + i for i in range(len(suite.seeds))),
        candidate=replace(suite.candidate, profile=None, heuristic_configuration=configuration),
    )


def write_throughput_report(
    root: Path, snapshot: Mapping[str, object], rows: Sequence[Mapping[str, object]], *, status: str
) -> None:
    grouped: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        key = cast(str, row["workload"]), cast(int, row["workers"])
        grouped.setdefault(key, []).append(cast(float, row["seconds"]))
    medians = {key: statistics.median(values) for key, values in grouped.items()}
    summary: list[dict[str, object]] = []
    for (name, workers), seconds in sorted(medians.items()):
        baseline = medians.get((name, 1))
        sample = next(r for r in rows if r["workload"] == name and r["workers"] == workers)
        summary.append(
            {
                "workload": name,
                "workers": workers,
                "games": sample["games"],
                "median_seconds": seconds,
                "samples": len(grouped[name, workers]),
                "games_per_second": cast(int, sample["games"]) / seconds,
                "speedup": None if baseline is None else baseline / seconds,
            }
        )
    sections = [
        (
            "Machine",
            table(
                ["Property", "Observed"], cast(Mapping[str, object], snapshot["hardware"]).items()
            ),
        ),
        (
            "Measurements",
            table(
                [
                    "Workload",
                    "Workers",
                    "Games/run",
                    "Repeats",
                    "Median seconds",
                    "Games/s",
                    "Speedup",
                ],
                [
                    (
                        r["workload"],
                        r["workers"],
                        r["games"],
                        r["samples"],
                        f"{cast(float, r['median_seconds']):.2f}",
                        f"{cast(float, r['games_per_second']):.2f}",
                        "pending" if r["speedup"] is None else f"{cast(float, r['speedup']):.2f}x",
                    )
                    for r in summary
                ],
            ),
        ),
        (
            "Scaling",
            chart(
                "Production-sized game throughput",
                [
                    (
                        name,
                        [
                            (float(cast(int, r["workers"])), cast(float, r["games_per_second"]))
                            for r in summary
                            if r["workload"] == name
                        ],
                    )
                    for name in ("screening", "recheck")
                ],
                xlabel="Workers",
                ylabel="Games / second",
            ),
        ),
        (
            "Interpretation",
            "<p>Measured wall time includes fresh manifest preparation, game execution, "
            + "worker startup/shutdown, validation, persistence and the run report. "
            + "Every worker count "
            + "must produce identical game semantics and statistical summaries. "
            + "Screening uses the incumbent; "
            + "recheck uses card advantage 8 and scorch exposure -0.75. "
            + "These synthetic-seed smoke runs "
            + "measure throughput and make no playing-strength claim. "
            + "They do not consume held-out games. "
            + "Sensitivity, candidate nomination, stage-level HTML and the complete "
            + "investigation were not "
            + "timed. Repeated runs give a local measurement, not a universal speed guarantee.</p>",
        ),
    ]
    write_report(
        root,
        "Range execution throughput",
        f"Production-sized diagnostic measurement: {status}.",
        {
            "status": status,
            "protocol": dict(snapshot),
            "measurements": list(rows),
            "summary": summary,
        },
        sections,
    )


def rebuild_throughput_report(root: Path) -> None:
    store = StudyStore(root, verification_only=True)
    with store.writer():
        snapshot = cast(
            Mapping[str, object], read_checked_document(root / "snapshot.json")["snapshot"]
        )
        store.prepare(snapshot)
        rows = [entry.payload for entry in store.entries if entry.kind == "measurement"]
        complete = any(entry.kind == "complete" for entry in store.entries)
        write_throughput_report(
            root, snapshot, rows, status="complete" if complete else "incomplete"
        )


def measure_throughput(spec: Path, root: Path, *, workers: tuple[int, ...], repeats: int) -> None:
    if type(repeats) is not int or repeats < 1:
        raise SpecError("Repeats must be a positive integer.")
    if not workers or len(set(workers)) != len(workers) or 1 not in workers:
        raise SpecError("Declare distinct worker counts including the serial baseline (1).")
    for count in workers:
        validate_worker_count(count)
    repository = default_repository_root()
    study = load_study_spec(spec, repository_root=repository)
    configuration = study.incumbent
    challenger = replace(
        configuration,
        baseline=replace(
            configuration.baseline,
            weights=replace(
                configuration.baseline.weights,
                card_advantage=8.0,
                scorch_exposure=-0.75,
            ),
        ),
    )
    suites = {
        "screening": workload_suite(study.optimization.suite, configuration, name="screening"),
        "recheck": workload_suite(study.validation.suite, challenger, name="recheck"),
    }
    snapshot: dict[str, object] = {
        "hardware": _hardware(),
        "repository": record_to_dict(study.optimization.repository),
        "runtime": record_to_dict(study.optimization.runtime),
        "workers": list(workers),
        "repeats": repeats,
        "suites": {name: record_to_dict(suite) for name, suite in suites.items()},
        "ordering": "declared counts then reversed counts on alternate repeats",
        "timing": "execute_run wall time including startup, persistence and run report",
    }
    store = StudyStore(root)
    rows: list[Mapping[str, object]] = []
    reference: dict[str, tuple[str, str]] = {}
    status = "interrupted"
    with store.writer():
        if (root / "snapshot.json").exists():
            raise RunConflictError(
                "Throughput measurements require a new output directory; "
                + "use --report-only to rebuild."
            )
        store.prepare(snapshot)
        write_throughput_report(root, snapshot, rows, status="running")
        try:
            for repetition in range(repeats):
                order = workers if repetition % 2 == 0 else tuple(reversed(workers))
                for count in order:
                    for name, suite in suites.items():
                        run_root = root / "runs" / f"{name}-repeat-{repetition + 1}-workers-{count}"
                        with stage(
                            f"throughput {name} / repeat {repetition + 1} / {count} workers"
                        ):
                            started = perf_counter()
                            run = execute_run(
                                suite=suite,
                                run_id="candidate",
                                output_root=run_root,
                                repository_root=repository,
                                evidence_policy=EvidencePolicy.NONE,
                                workers=count,
                            )
                            seconds = perf_counter() - started
                            if (
                                run.report.failed_matches
                                or run.report.missing_matches
                                or run.resumed_case_ids
                            ):
                                raise SpecError(
                                    "Timing requires fresh, complete and successful games."
                                )
                            semantics = canonical_digest(
                                [
                                    replace(r, decision_seconds=0.0, execution_seconds=0.0)
                                    for r in run.results
                                ]
                            )
                            stats = record_to_dict(run.report)
                            _ = stats.pop("latency")
                            statistics_digest = canonical_digest(stats)
                            identity = semantics, statistics_digest
                            if name in reference and reference[name] != identity:
                                raise RunConflictError(
                                    "Parallel outcomes or statistics differ from the reference."
                                )
                            reference[name] = identity
                            row: dict[str, object] = {
                                "workload": name,
                                "repeat": repetition + 1,
                                "workers": count,
                                "games": len(run.results),
                                "seconds": seconds,
                                "semantic_digest": semantics,
                                "statistics_digest": statistics_digest,
                                "run_root": str(run.root.relative_to(root)),
                            }
                            _ = store.record("measurement", row)
                            rows.append(row)
                            advance(
                                f"{len(run.results):,} games in {seconds:.2f}s "
                                + f"({len(run.results) / seconds:.2f} games/s)"
                            )
                            write_throughput_report(root, snapshot, rows, status="running")
            _ = store.record("complete", {"measurements": len(rows)})
            store.finish()
            status = "complete"
        except BaseException as error:
            status = (
                "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            )
            raise
        finally:
            write_throughput_report(root, snapshot, rows, status=status)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--spec",
        type=Path,
        default=default_repository_root() / "experiments/tuning/benchmark-v2.json",
    )
    _ = parser.add_argument(
        "--output", type=Path, default=default_repository_root() / ".output/range-throughput"
    )
    _ = parser.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8, 16, 32])
    _ = parser.add_argument("--repeats", type=int, default=2)
    _ = parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    root = cast(Path, args.output)
    if cast(bool, args.report_only):
        rebuild_throughput_report(root)
    else:
        import sys

        with TerminalProgress(sys.stderr).display():
            measure_throughput(
                cast(Path, args.spec),
                root,
                workers=tuple(cast(list[int], args.workers)),
                repeats=cast(int, args.repeats),
            )


if __name__ == "__main__":
    main()
