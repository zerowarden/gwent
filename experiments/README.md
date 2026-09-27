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
  tuning/
    weights.json  # scientific study planning inputs
    smoke.json    # tiny synthetic study planning inputs
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

Agent catalogs and entries use schema version 2. A heuristic entry may supply
`heuristic_configuration` (the complete baseline and actual profile snapshot)
instead of `profile`. Other families reject that field. Runs embed every
heuristic participant's resolved configuration, so reproduction does not depend
on the authoring file or current named-profile defaults. Configuration identity
excludes display labels; changing candidate weights preserves scheduled pairings.

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

Suite ids are immutable presets: choose a new descriptive id whenever declared
contents change, because case ids, manifests, and comparisons refer to the id.
Existing version-suffixed ids remain unchanged; new suites use domain names.

| Suite id | Purpose | Blocks | Matches | Seeds |
| --- | --- | --- | --- | --- |
| `smoke-v1` | `smoke` | 4 | 32 | 3, 11 |
| `core-optimize-v1` | `optimize` | 12 | 96 | 101, 202 |
| `core-validation-v1` | `validation` | 12 | 96 | 303, 404 |
| `core-test-v1` | `test` | 18 | 144 | 606, 707, 808 |
| `search-diagnostic-v1` | `diagnostic` | 2 | 8 | 17, 23 |
| `weights-optimize` | `optimize` | 128 | 1,024 | 10001–10016 |
| `weights-validation` | `validation` | 256 | 2,048 | 20001–20032 |
| `weights-test` | `test` | 512 | 4,096 | 30001–30064 |

The `core-*` partitions share candidate, opponents, and deck pairs so only the
declared seeds differ; their seed sets and scheduled case ids are disjoint.
The `weights-*` partitions add fixed greedy, neutral, conservative, and aggressive
opponents with the same two deck pairs below and disjoint root seeds. The weight
study uses these expanded suites; the five original presets retain their exact
contents. Both `core-test-v1` and `weights-test` are reserved held-out evidence:
do not use them while tuning or debugging.

Deck pairs used by the core suites:

- `monsters_muster_swarm_strict` vs `nilfgaard_spy_medic_control_strict`
- `scoiatael_high_stakes` vs `northern_realms_spy_siege_bond_strict`

## Running

```bash
uv run python -m gwent_evaluation run --suite smoke-v1
uv run python -m gwent_evaluation report .output/manual/evaluations/<run-id>
uv run python -m gwent_evaluation replay .output/manual/evaluations/<run-id> --case <case-id>
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

`replay --reproduce` re-executes the declared agents and reports two independent
flags: `execution_identity_matches` compares the current implementation, runtime,
resolved configurations, and assets against the recorded execution identity;
`semantics_reproduced` compares the outcome and semantic trace. Identity drift
can coexist with reproduced semantics. The existing `reproduced` verdict and
exit status continue to reflect semantic reproduction. Python callers can pass
`repository_root` to `reproduce_case()` when using a non-default checkout.

A run directory contains `manifest.json`, `schedule.jsonl`, `matches/`,
`evidence/`, `report.json`, and `report.md`.

Suite catalogs/entries remain schema version 1; persisted evaluation records
use version 3. Incompatible historical agent/record versions fail explicitly
and require their pinned checkout for reproduction.

## Study planning

```bash
uv run python -m gwent_evaluation tune plan experiments/tuning/smoke.json
uv run python -m gwent_evaluation tune plan experiments/tuning/weights.json
```

Planning resolves full immutable snapshots and reports exact scheduled match
counts without playing games. The tiny study budgets at most 40 evaluation
matches plus a separate 12-match sensitivity panel. The weight study budgets
279,552 evaluation matches (263,168 optimization, 8,192 validation, 8,192 test)
plus a separate 192-match sensitivity panel. Counts include shared incumbents
and assume all proposal slots and allowed finalists are evaluated, before cache
reuse or early retention.

The study fixes all eleven weight bounds/order, frozen settings, disjoint stage
roots, random/CMA proposal budgets and seeds, bootstrap settings, promotion
thresholds, and repository/runtime/asset identities. Catalogs are authoring
conveniences; `study_to_dict()` snapshots reload with `study_from_dict()` without
the original catalogs. Resolve a new study whenever pinned inputs change.

Study authoring and snapshots use schema version 2, which requires explicit CMA
backend, RNG, boundary, and stopping settings. Older snapshots are historical
records; resolve a new study from the current authoring file instead of filling
in missing pins. Changing the dependency environment also requires a new study
and matching sensitivity evidence.

Planning reports `sensitivity_status: "not_assessed"` because it does not load
diagnostic evidence. `execution_available` identifies scientific studies that
can use the Python study runner; execution still requires clean provenance and
passing sensitivity evidence. Smoke studies remain diagnostic only. Use the
separate sensitivity command to assess the frozen study. A successful diagnostic does not claim policy improvement.

Authoring filenames are stable names; compatibility versions remain inside the
JSON. `tune plan` prints a zero-game preview to stdout. The complete pilot saves
its plan at `.output/pilot/reports/plan.json` and its frozen inputs under
`.output/pilot/inputs/`. Existing suite IDs stay fixed because they participate
in case IDs and seed derivation. Historical previews are not prerequisites.

## Sensitivity diagnostics

```bash
uv run python -m gwent_evaluation tune sensitivity experiments/tuning/smoke.json
uv run python -m gwent_evaluation tune sensitivity experiments/tuning/weights.json
```

Protocol 1 fixes three complete-match controls before execution: the incumbent,
all weights at their lower bounds, and all weights at their upper bounds. These
use the optimization opponents and decks with pilot root 9001; no validation or
test matches are played. Numeric lower bounds are not presumed to weaken play.

Each incumbent match contributes up to eight evenly spaced, player-safe action
observations. Each weight is separately set to both endpoints while other
weights stay at incumbent values. Engine decision plans supply shortlisted and
all-action scores, rankings, production choices, shortlist counts, and tactical
override reasons. Common score offsets do not qualify as relative sensitivity;
scoring omitted actions never widens the production shortlist.

The report requires relative-score witnesses on shortlisted actions for every
dimension, some changed final decisions, complete controls, and changed paired
match outcomes. Failure records `insufficient_sensitivity`. `require_sensitivity`
also rejects mismatched studies and evidence from a dirty or non-scientific
study before future optimizer execution. All execution uses the ordinary
evaluator, recording, integrity checks, and block-score arithmetic.

By default, artifacts live under `.output/manual/sensitivity/<study>/`:
`snapshot.json`, `report.json`, and `runs/<control>/`. The snapshot freezes inputs
before games; the report pins study, code, incumbent, space, suites, observations,
and control execution identities. Successful matches retain decision samples;
failed matches also retain trajectories. Repeating the command reuses completed
matches. A conflicting snapshot is rejected; use `--output <new-directory>`
for a newly resolved study after changing inputs or code.

Exit codes are `0` for sufficient sensitivity, `1` for insufficient sensitivity,
and `2` for invalid inputs or conflicting evidence. Measurements belong to the
specific recorded source, environment, and study. Generate current evidence with
`make pilot`; historical diagnostic success cannot authorize changed inputs.

## Candidate evaluation

The objective adapter evaluates one complete candidate on the study's
optimization schedule. It uses the existing evaluator and balanced-block score;
optimizer fitness is `1 - score`. Bounds remain provisional engineering choices:
sensitivity demonstrates observable effects, not that the bounds contain an
optimum. Candidate evaluation preserves those declared bounds and frozen settings.

```python
from pathlib import Path
from gwent_evaluation.tuning.objective import evaluate_candidate
from gwent_evaluation.tuning.specs import load_study_spec

study = load_study_spec(
    Path("experiments/tuning/smoke.json"), repository_root=Path.cwd()
)
trial = evaluate_candidate(
    study,
    study.bind((0.5,) * 11),
    run_id="candidate",
    output_root=Path(".output/manual/objective/runs"),
)
print(trial.status, trial.score, trial.fitness)
```

This tiny example executes four synthetic smoke matches. It returns
`diagnostic_only`, a descriptive score, and `fitness=None`. A scientific call
also requires `sensitivity_report=<matching SensitivityReport>` from a clean
study; missing, stale, or insufficient preflight evidence fails before games.
Seeded random and bounded CMA proposal backends are available in Python. Durable
study orchestration and a CLI for complete optimization runs remain future work.

`TrialEvaluation` includes configuration/candidate identities, suite and benchmark
identities, verified result paths/checksums, coverage counts, status/reasons, and
the score. `trial.to_dict()` includes fitness for serialization. Status meanings:

| Status | Meaning | Fitness / next action |
| --- | --- | --- |
| `eligible` | Complete, comparison-valid scientific evidence with matching identities | `1 - score` |
| `diagnostic_only` | Complete smoke/diagnostic evidence | No fitness; descriptive score only |
| `incomplete` | Scheduled results are missing, with no recorded game failures | No fitness; resume missing cases |
| `failed` | At least one recorded game/agent failure or action-limit truncation | No fitness; stop the study and diagnose |

Identity conflicts, corrupt records, invalid candidates, and failed preflight
raise explicit exceptions. Interruptions propagate; already persisted match
results remain reusable. `load_trial_evaluation()` inspects an existing run
without executing games. Both paths recheck pinned conditions, and the execution
path checks the expected manifest before creating or resuming a run.

Bulk trials require `evidence_policy: "none"` and use summary recording. To
investigate a particular result with rich evidence, reproduce it separately:

```python
from gwent_evaluation.replay import reproduce_case

outcome = reproduce_case(
    Path(trial.run_root),
    trial.results[0].case_id,
    diagnostic_root=Path(".output/manual/objective/diagnostic"),
)
```

The diagnostic directory must be new and outside the source run. It records one
case of the original schedule, full samples/trajectory, and `reproduction.json`
linking the source execution, case, and original result checksum. Its case can
be inspected with ordinary `replay`. It never replaces the source result; an
incomplete diagnostic run cannot supply optimizer fitness.

## Seeded random proposals

`tuning/optimizers.py` provides the shared `ProposalOptimizer` interface and
`RandomSearch` implementation. The backend receives optimizer settings and a
dimension count; it has no evaluator, study-stage access, or filesystem work.

```python
from gwent_evaluation.tuning.optimizers import RandomSearch

optimizer = RandomSearch(
    study.optimizers[0], dimensions=len(study.parameter_space.parameters)
)
batch = optimizer.ask()
for proposal in batch:
    print(proposal.index, proposal.coordinates)
```

The caller binds each proposal to a complete configuration, obtains a verified
trial, and calls `tell()` with a tuple of `ProposalFitness(proposal, fitness)`
in the original batch order. Every value must be finite; partial, reordered, or
changed batches fail without advancing. Repeating `ask()` while a batch is
pending returns that same batch. After the last complete `tell()`, `ask()` returns
an empty tuple and `stop_reason` is `budget_exhausted`. Tied scores do not cause
random search to stop early or claim convergence.

Protocol 1 uses a private Python `Random(seed)` and consecutive `random()` draws,
one coordinate at a time within each proposal. Coordinates are uniform in
`[0, 1)` within the inclusive allowed domain. There is no clipping, rounding,
duplicate resampling, or global random seeding. The implementation/runtime pins
and seed make the ordered proposals reproducible.

`EvaluationCache` is a shared in-memory helper outside the proposal backend.
Before each lookup, the caller obtains `candidate_evaluation_identity(study,
configuration)`, which validates the candidate and rechecks current conditions.
The key includes the study, configuration, and complete execution identity.
On a miss, a callback invokes the ordinary objective adapter; only complete
eligible trials are cached. Diagnostic or failed trials are rejected, so the
smoke example's descriptive score cannot enter scientific selection. Durable
cache recovery and journal verification belong to the future study controller.

`summarize_search(incumbent, proposals)` ranks distinct evaluated configurations
by score, then incumbent on an exact tie, then normalized Euclidean distance
from incumbent, then canonical configuration digest. Its best candidate is the
best evaluated point. `optimization_score_gain` is a development score
difference, not a promotion decision. This rule never changes backend fitness.

The incumbent is evaluated separately from proposal slots. The summary tracks
proposal slots, distinct configurations, cache hits, and fresh matches separately;
all counts except proposal slots include incumbent work. A duplicate still uses
one proposal slot, and a cache hit adds zero fresh matches. `TrialEvaluation`
now reports `fresh_matches` from the evaluator's executed-case list, including
partial resumption; loading existing records reports zero.

The tests include a fixed numeric objective with a known ranking and forced
duplicates, with no game execution. These are algorithm checks. The pilot's
`reports/trials.csv` contains measured game results for every proposed configuration.

## Bounded CMA proposals

CMA-ES adapts its search using the completed population's fitness. It shares the
random backend's `ask()` / `tell()` interface, parameter binding, and objective.
Construct either method from its frozen study settings:

```python
from gwent_evaluation.tuning.backends import create_optimizer
from gwent_evaluation.tuning.models import OptimizerMethod

optimizer = create_optimizer(study, OptimizerMethod.CMA_ES)
batch = optimizer.ask()
configurations = tuple(study.bind(proposal.coordinates) for proposal in batch)
```

The CMA mean starts at the encoded incumbent. `initial_sigma: 0.2` is the initial
spread in normalized coordinates, where every allowed weight interval maps to
`[0, 1]`. It is neither a raw weight increment nor a maximum distance. The backend
handles bounds; callers must evaluate the exact proposed coordinates and return
the complete population's fitness in proposal order. Invalid tells leave the
population pending. The backend never evaluates a final mean or other extra
candidate outside the declared proposal budget.

The study pins `cma` 4.5.0, a private NumPy PCG64 generator, `BoundTransform`, and
termination tolerances. The lockfile and existing runtime fingerprint also pin
NumPy. Zero is a deterministic seed; global NumPy and game RNGs are unaffected.
Protocol 1 disables file logging, plotting, external settings input, wall-clock
stopping, restarts, and additional stagnation/target criteria. It retains the
declared fitness/coordinate tolerances, covariance limit, backend numerical
limits, and population/generation cap. A tied population keeps its real scores.

After stopping, `ask()` returns an empty tuple. `stop` includes the reason, number
of proposals successfully told, backend criterion names, and any failure detail.
`flat_objective`, `numerical_limit`, `budget_exhausted`, and `backend_failure` are
distinct. When criteria coincide, numerical limits take precedence over flatness,
then budget; all backend criterion names remain visible. A plateau does not
establish optimality. Compare actual evaluated work using the shared search
counts, including fresh matches and cache hits, rather than assuming every
optimizer used its entire cap.

Recovery must reconstruct the backend and replay each recorded `ask()` followed
by its ordered `tell()`, checking exact proposals before advancing. A backend
exception ends that instance; do not retry a potentially mutated optimizer.
Durable journaling and recovery belong to the study controller.

The optional `gwent-evaluation[tuning]` extra installs CMA and NumPy. Workspace
development dependencies include it so `make sync` prepares the backend tests;
`uv sync --no-dev --group tuning` enables tuning without developer tools. Engine,
service, study decoding, and random proposals remain usable without that extra.

## Complete pilot workflow

```bash
make pilot
# Equivalent command:
uv run --locked --group tuning python -m gwent_evaluation tune pilot
```

The workflow runs the smoke suite, sensitivity gates, incumbent/random/CMA
optimization, verified study replay, and human-readable reports. It stops before
validation, held-out confirmation, or promotion. The authored pilot spec is
`experiments/tuning/pilot.json`; the larger `weights.json` study is not run.

Use a clean committed checkout with pinned dependencies. The command does not
copy source, create a nested environment, or commit changes. For isolation, use
a separate checkout outside `.output/` and install from its lockfile. Pass
`--output <directory>` (or `make pilot PILOT_OUTPUT=<directory>`) to place results
elsewhere. The default is `.output/pilot`.

```text
.output/
  README.md                  # generated navigation
  pilot/
    README.md                # status, interpretation, scores, weights, artifact guide
    workflow.json            # derived stage status and execution counts
    writer.lock              # ownership marker for the whole workflow
    inputs/                  # immutable checksummed study and smoke snapshots
    reports/                 # plan.json, trials.csv, configurations.json
    data/
      smoke/                 # ordinary summary-only evaluation run
      sensitivity/           # control runs, samples, snapshot, report
      optimization/          # durable study and candidate runs
    logs/events.jsonl        # operational events; not scientific evidence
  manual/                    # only separately requested standalone experiments
```

Every output family is explained in the generated reading guides. Match files
and optimizer journals remain evidence; reports are derived. Logs are never
used to reconstruct scientific results. A partial run records its failed or
interrupted stage and does not claim completion. A rerun verifies existing
inputs and evidence before reuse; it never trusts the stage-status file alone.

To reset intentionally, remove `.output/` only when no writer is active, then
run `make pilot`. No previous output is required. Generated files are not stored
in `docs/`; that directory contains durable explanations and design only.

The pilot preserves the full four-opponent, two-deck-pair panel and eleven weight
bounds, with two optimization roots (128 matches per candidate). Random search
gets 16 proposals; CMA gets two populations of eight. Including the incumbent,
optimization is capped at 4,224 matches, plus a separate 192-match sensitivity
panel. Validation/test budgets are declared but not executed by this runner.
These small optimization results are exploratory and cannot establish promotion.

Each study directory contains:

```text
snapshot.json              # frozen study and scientific preflight evidence
writer.lock                # persistent POSIX lock inode and ownership marker
journal/00000000.json       # ordered immutable checksummed events
runs/trial-<identity>/      # existing evaluation run format and match records
report.json                # derived summary; safe to regenerate by replay
```

Complete candidate populations and their full configurations are saved before
any candidate executes. Trial events bind scores to verified result references;
a complete ordered tell is committed before the optimizer advances. Recovery
reconstructs each backend from its seed, checking every proposal, trial, fitness,
and stop record against the journal. Missing results in an uncommitted trial are
resumed; missing or altered committed evidence is a conflict. Invalid trials or
backend failures stop the study without inventing a loss or changing its budget.

Run `make pilot` again to resume the same workflow or verify completed work.
The lower-level `run_study()` API remains available with explicit frozen inputs. No completed match is rerun. A live writer
always excludes other writers. After process death, explicitly pass
`tune pilot --recover-lock` (or `recover_lock=True` in Python); it only clears the abandoned marker after acquiring the
kernel lock, so it cannot displace a live writer. The store currently requires
POSIX `flock`. Corrupt journal/input records are never repaired automatically.

Study counts describe work over the study's lifetime, including matches saved
before an interruption. The first occurrence of an exact evaluation identity
owns its match count; duplicate proposal slots retain their positions but count
as cache hits with zero additional games. Overall counts include the shared
incumbent once; each method's comparison counts also include that incumbent,
so method totals must not be added together. This differs from the objective
adapter's per-invocation `fresh_matches` counter. Timings and preflight disk usage
do not enter the frozen scientific evidence used for journal replay.

## Reproducibility rules

- Inputs are pinned in `manifest.json`: repository commit/lockfile, runtime,
  resolved agent identities, asset digests, observation-contract version, seed
  derivation version, and the fully materialized schedule.
- Persistent identities use canonical JSON plus SHA-256; never process-salted
  hashes or `repr()`. File layout is not part of any case id or digest.
- Optimization, validation, and test runs require a clean Git checkout and a
  lockfile. Smoke and diagnostic runs permit local edits, fingerprint installed
  source files, and are marked `optimization_evidence: false`.
- `report.json` only claims `valid_for_comparison` when every planned case
  completed; `compare` refuses to present an inferential interval otherwise.
