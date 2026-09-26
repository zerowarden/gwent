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

Run reproducible agent benchmarks:

```bash
uv run python -m gwent_evaluation run --suite smoke-v1
uv run python -m gwent_evaluation report .output/experiments/<run-id>
uv run python -m gwent_evaluation replay .output/experiments/<run-id> --case <case-id>
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
