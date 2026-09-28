# Gwent

![Happy geralt](./assets/image.jpg)

_Fancy a game of card?_

## Description

Engine for the Witcher 3 Gwent minigame.

## Prerequisites

- Python `3.12+`
- `uv`
- `make`

Create the workspace environment from the repository root:

```bash
make sync
```

## Commands

Show available commands:

```bash
make help
```

Verification:

```bash
make pytest
make ruff
make mypy
make basedpyright
make check
```

Run tests with coverage:

```bash
make test:cov
```

Notes:
- `make pytest` is the fast default and does not generate coverage output.
- coverage XML is generated alongside the test run when using `make test:cov`
- tool caches are kept under the repository cache directory

Run an interactive AI match:

```bash
make ai-play
```

## Evaluation

Plan and run heuristic tuning with the bounded pilot defaults:

```bash
uv run --locked tune plan
# Commit implementation/spec changes before scientific execution:
uv run --locked tune run
uv run --locked tune report
# Only when validation selects a challenger:
uv run --locked tune verify
uv run --locked tune finalize
```

Read `.output/tuning/weight-pilot/report.md` for the stage, sensitivity findings,
optimizer work, validation evidence, and promotion verdict. The matching
`report.json` contains the full settings and measurements. `run` stops after
validation; `finalize` explicitly consumes held-out evidence. Repeating a command
verifies and reuses recorded work. An inconclusive study retains the incumbent.

Terminal progress updates in place; `--no-progress` disables it, and `--json`
prints machine-readable output. Paths have defaults and can be overridden with
`GWENT_TUNING_SPEC`, `GWENT_TUNING_OUTPUT_ROOT`, and `GWENT_TUNING_STUDY_ID`.
Use a new study ID after changing code, settings, or dependencies.

`make ai-tune-smoke` runs bounded diagnostic sensitivity checks on synthetic
smoke seeds, including from a dirty checkout. It cannot establish improvement
or produce optimizer fitness. `make pilot` retains the earlier optimization-only
workflow under `.output/pilot/`.

See the [tuning command guide](experiments/README.md#tuning-command-guide)
for defaults, recovery, report interpretation, and policy loading.


### Range investigations

Plan, run, and read the benchmark and weight-range investigation:

```bash
uv run --locked tune ranges plan
# Commit source changes, then use a new output directory for the new version:
uv run --locked tune ranges run --output .output/ranges-parallel
uv run --locked tune ranges report --output .output/ranges-parallel
```

Games within each candidate run concurrently. Candidates retain their declared
order; screening finishes and saves its nominations before rechecks start.
Sensitivity remains serial. Progress shows the stage, saved games and actual
worker count, updating in place in a terminal and sparsely in redirected logs.
Read `.output/ranges-parallel/report.html` for the stage reports and charts.

The worker default is automatic: half the CPUs available to the process, capped
at 16 and at least one. On a machine with 32 available logical CPUs this selects
16 workers. `GWENT_RANGE_WORKERS` overrides that default; `-j` / `--workers`
overrides the environment. Use `-j 1` for serial execution. Worker settings apply
to `ranges run`; `plan` and `report` play no games and ignore the worker environment.

```bash
export GWENT_RANGE_WORKERS=8
uv run --locked tune ranges run -j 16 --output .output/ranges-parallel
# Resume after Ctrl-C, with the same committed source/runtime and protocol:
uv run --locked tune ranges run -j 8 --output .output/ranges-parallel
```

Ctrl-C stops dispatch and waits for running games before releasing the writer
lock. Saved games survive; unsaved games may run again on resume. The worker
count can change between invocations. After process death, use `--recover-lock`
only for an abandoned writer; it cannot displace a live writer. Source or protocol
changes require a new output directory. Regenerating reports verifies saved
evidence and starts no workers.

Measure throughput with the actual screening/recheck game counts and separate
diagnostic seeds. The command writes HTML charts, JSON, game records and a
checksummed measurement journal under `.output/range-throughput`:

```bash
uv run --locked python -m gwent_evaluation.tuning.throughput
uv run --locked python -m gwent_evaluation.tuning.throughput --report-only
```

It compares 1, 4, 8, 16 and 32 workers twice, checks identical outcomes and
statistics, and includes process startup and file writes in wall time. These
measurements can run from a dirty checkout; they measure execution throughput
without using scientific or held-out seeds. Use a new `--output` for another
measurement. The complete investigation also includes serial sensitivity and
candidate/stage reporting, so its speedup depends on those additional costs.

Run reproducible agent benchmarks:

```bash
uv run python -m gwent_evaluation run --suite smoke-v1
uv run python -m gwent_evaluation report .output/manual/evaluations/<run-id>
uv run python -m gwent_evaluation replay .output/manual/evaluations/<run-id> --case <case-id>
uv run python -m gwent_evaluation compare <reference-run> <candidate-run>
```

`make ai-eval-smoke` and `make ai-eval-core` wrap the smoke and core suites.
Benchmark inputs and suite partitions are documented in
[experiments/README.md](experiments/README.md).

Run the HTTP service:

```bash
make service
```

Run the HTTP service with durable SQLite storage:

```bash
make service-sqlite
```

## Modules

`engine`: Runtime states, typed actions/events, reducer, legality checks, scoring

`service`: HTTP service, match lifecycles, player identity mappings, persistence, transports

`shared`: low-level helpers that can be shared across modules

`evaluation`: reproducible suite/spec definitions, match execution, and reports for AI evaluation
