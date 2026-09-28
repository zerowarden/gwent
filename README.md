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
