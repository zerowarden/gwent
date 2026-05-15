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
