# Experiments

Version-controlled inputs for reproducible agent evaluation. Every benchmark
input is either a bundled engine asset (`cards.yaml`, `leaders.yaml`,
`sample_decks.yaml` under `packages/engine/src/gwent_engine/data/`) or one of
the catalogs in this directory. Nothing here is fetched from the internet or
regenerated as an expectation.

## Layout

```text
experiments/
  agents.json   # named benchmark participants (agent catalog)
  suites.json   # scheduled benchmark suites (suite catalog)
```

Benchmarks are full matches from initial deck/seed setups; every in-game
decision belongs to the agent under test. Specific positions are investigated
with `replay`/`--reproduce` from recorded runs, and rules or
observation-invariance properties live in engine tests.

## Agents

`agents.json` lists every named participant once. Entries are strict JSON;
`agent_id` follows `<family>` or `<family>-<canonical-profile>`. Profiles use
posture names only (`neutral`, `conservative`, `aggressive`);
`baseline`/`reference` are reserved for comparison roles in suites and reports.

| Agent id | Family | Profile |
| --- | --- | --- |
| `random` | `random` | — |
| `greedy` | `greedy` | — |
| `heuristic-neutral` | `heuristic` | `neutral` |
| `heuristic-conservative` | `heuristic` | `conservative` |
| `heuristic-aggressive` | `heuristic` | `aggressive` |
| `search-neutral` | `search` | `neutral` |

## Suites

`suites.json` lists every suite once; `candidate` and `opponents` reference
agent ids from `agents.json`. A suite expands into balanced blocks
`(opponent, deck pair, root seed)`; each block covers candidate seat, requested
starter, and deck assignment (8 legs, or 4 when both deck ids are identical).

Suite ids are immutable presets: bump the `-vN` suffix whenever declared
contents change, because case ids, manifests, and comparisons refer to the id.

| Suite id | Purpose | Blocks | Matches | Seeds |
| --- | --- | --- | --- | --- |
| `smoke-v1` | `smoke` | 4 | 32 | 3, 11 |
| `core-optimize-v1` | `optimize` | 12 | 96 | 101, 202 |
| `core-validation-v1` | `validation` | 12 | 96 | 303, 404 |
| `core-test-v1` | `test` | 18 | 144 | 606, 707, 808 |
| `search-diagnostic-v1` | `diagnostic` | 2 | 8 | 17, 23 |

The `core-*` partitions share candidate, opponents, and deck pairs so only the
declared seeds differ; their seed sets and scheduled case ids are disjoint.
`core-test-v1` is reserved held-out evidence: do not use it while tuning or
debugging. M2 evaluates candidates against `core-optimize-v1`, selects with
`core-validation-v1`, and reports with `core-test-v1`.

Deck pairs used by the core suites:

- `monsters_muster_swarm_strict` vs `nilfgaard_spy_medic_control_strict`
- `scoiatael_high_stakes` vs `northern_realms_spy_siege_bond_strict`

## Running

```bash
uv run python -m gwent_evaluation run --suite smoke-v1
uv run python -m gwent_evaluation report .output/experiments/<run-id>
uv run python -m gwent_evaluation replay .output/experiments/<run-id> --case <case-id>
uv run python -m gwent_evaluation compare <reference-run> <candidate-run>
```

`run` reads `experiments/agents.json` and `experiments/suites.json` by default;
pass a catalog path and/or `--agents-catalog` to use others, and `--suite` to
select an id when the catalog declares several. Equivalent make targets:
`make ai-eval-smoke` and `make ai-eval-core`.

`run` defaults to `--evidence-policy all` so completed cases are replayable;
`failures` and `none` reduce evidence size for bulk runs. Reusing `--run-id`
resumes an interrupted run after verifying existing records; conflicting
manifests are rejected. Exit codes: `0` success, `1` reproduced divergence or
incompatible comparison, `2` invalid input.

A run directory contains `manifest.json`, `schedule.jsonl`, `matches/`,
`evidence/`, `report.json`, and `report.md`.

## Reproducibility rules

- Inputs are pinned in `manifest.json`: repository commit/lockfile, runtime,
  resolved agent identities, asset digests, observation-contract version, seed
  derivation version, and the fully materialized schedule.
- Persistent identities use canonical JSON plus SHA-256; never process-salted
  hashes or `repr()`. File layout is not part of any case id or digest.
- Authoritative benchmark runs require a clean tree unless a complete source
  bundle is captured.
- `report.json` only claims `valid_for_comparison` when every planned case
  completed; `compare` refuses to present an inferential interval otherwise.
