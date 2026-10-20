# Shared optimization job API 0.2

This repository holds `crates/optimization-job-api` and
`crates/optimization-runner`, which [fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust),
[LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) and [SQP-craft](https://github.com/dietmarwo/SQP-craft) share. Each
of them builds its own native worker. One runner can register all three
executables and schedule them against one CPU budget. Each worker repository
builds independently: Cargo fetches this repository at the revision the worker
pins; no sibling checkout or Python extension is needed.

Start with a runnable tutorial: [fcmaes](https://github.com/dietmarwo/fcmaes-rust/blob/main/tutorials/job-api/README.md),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/blob/main/tutorials/job-api/README.md) or
[SQP](https://github.com/dietmarwo/SQP-craft/blob/main/tutorials/job-api/README.md). The
[implementation plan](job-api/PLAN.md) records the implementation and its
acceptance gates; each worker repository keeps its validation report
([fcmaes](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/job-api/VALIDATION.md),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/blob/main/docs/job-api/VALIDATION.md),
[SQP](https://github.com/dietmarwo/SQP-craft/blob/main/docs/job-api/VALIDATION.md)). The job envelope and the
result manifest are published as JSON Schemas:
[`optimization.job-0.1.schema.json`](job-api/schemas/optimization.job-0.1.schema.json)
and [`optimization.result-0.2.schema.json`](job-api/schemas/optimization.result-0.2.schema.json).

## Architecture and compatibility

| Layer | Responsibility |
| --- | --- |
| `optimization-job-api` | Strict versioned envelope, resources, input hashes, checked journals, result contract and worker SDK |
| `optimization-runner` / `optimization-run` | Worker discovery, staging, idempotency, admission, process supervision, cancellation, deadlines, journal recovery and coded errors |
| `optimization-runner` / `optimization-mcp` | MCP server over stdio for agents: tools and tasks over `optimization-run` ([Agents and MCP](#agents-and-mcp)) |
| `fcmaes-job-worker` | `fcmaes.retry/1` (BiteOpt or DE, serial or with parallel delayed-feedback batches, CMA-ES with optional IPOP/BIPOP restarts, CR-FM-NES or PGPE retries on registered scalar models), `fcmaes.mode/1` (MODE Pareto fronts), `fcmaes.map-elites/1` (MAP-Elites grid or CVT archives, optional CMA-ME/CMA-MAE emitters) and `fcmaes.evaluate/1` (given points): deterministic task seeds, exact or declared evaluation budgets, parallel population evaluation; application workers register their own models with parameters and hashed inputs |
| `lp-ip-job-worker` | `lp-ip.solve/1`: sparse LP/MIP artifacts, candidate starts, node/pivot budgets and numerical checks; `lp-ip.evaluate/1`: given points |
| `sqp-job-worker` | `sqp.solve/1`: registered smooth Rust models, initial points, active-set/Clarabel backends and independent KKT checks; `sqp.evaluate/1`: given points |

The shared crates, this guide, the plan, the schemas and the shared test
scripts live in this repository; until October 2026 the three worker
repositories carried identical copies. The crates are source packages,
version 0.2.0, with publishing disabled. Worker repositories depend on them
through git at a pinned revision, which their `Cargo.lock` records (see the
[README](../README.md)). 0.2.0 adds the result contract 0.2 (evidence,
refutations, objective bounds, infeasibility and certified claims), worker
protocol 0.2, coded runner errors and the JSON Schemas to the 0.1.1
synchronization. Solver dependencies remain in the individual worker crates;
the runner never links all three engines.

The runner accepts workers of protocol `optimization.worker/0.1` and `/0.2`.
Every 0.1 result record is a valid 0.2 record, so a registered 0.1 worker keeps
working; its records simply carry no evidence. A runner built before 0.2
rejects 0.2 workers at registration instead of failing on their journals.

In fcmaes-rust, the original contract is the `legacy` module of
`optimization-job-api`, and `fcmaes-run` is a compatibility entry point into
the common runner. The original `fcmaes-native-worker`, `fcmaes.job/0.1` inputs,
retry journals, evaluation accounting, comparison rules and benchmark command
remain supported. Register that worker as `native`. Register the new adapter
as `fcmaes` for the common envelope. These are separate profiles; old jobs are
not silently converted.

The new runner defaults to `.optimization-jobs`; `fcmaes-run` retains
`.fcmaes-jobs`. `--root` takes precedence over `OPTIMIZATION_RUN_ROOT`, then the
legacy `FCMAES_RUN_ROOT`. Always use the same absolute root when sharing a node.

## Build and discover

Linux and Rust 1.88 or newer are required for the job layer. Python 3 is needed
only for the tutorials and integration tests. The solver libraries retain their
own requirements. Use the repository's lockfile:

```sh
# In a worker repository; replace WORKER_PACKAGE with its worker. In this
# repository, -p optimization-runner alone builds the runner and the MCP server.
cargo build --release --locked -p optimization-runner -p WORKER_PACKAGE
./target/release/optimization-run --root /tmp/optimization-node node init --capacity 8
./target/release/optimization-run --root /tmp/optimization-node workers add \
  --id WORKER_ID --executable /absolute/path/to/worker
./target/release/optimization-run --root /tmp/optimization-node workers list
./target/release/optimization-run --root /tmp/optimization-node problems describe WORKER_ID
```

The same build makes `optimization-mcp`, the MCP server of
[Agents and MCP](#agents-and-mcp). `describe` on a worker prints its accepted profiles, registered models, engine
version, resource limits, claims and recovery capabilities. Executables are
trusted local programs: registration is explicit, and jobs cannot supply
executable paths or shell commands. This is a local single-user runner, not a
multi-tenant sandbox or remote service.

## Envelope

Every common job has these fields; see each tutorial for a complete valid file
and `job-api/schemas/optimization.job-0.1.schema.json` for the schema:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exactly `optimization.job/0.1` |
| `request_key` | Caller-chosen idempotency key, 1–200 bytes |
| `worker` | Registered worker ID |
| `payload_schema` | Versioned worker profile |
| `payload` | Strict solver-specific model/algorithm/budget options |
| `resources` | Positive `cpu_slots`, `outer_workers`, `inner_threads` |
| `limits` | Positive `wall_time_seconds`, nonnegative `grace_seconds` |
| `inputs` | Named relative files with mandatory SHA-256 hashes: an LP model, or data a registered model reads; empty otherwise |
| `task_count` | Normally omitted; the worker fills it during validation |

Unknown envelope and payload fields, unsupported profiles and unsupported thread
widths are errors. Validation resolves defaults through the selected worker;
it does not run an optimization. `validate` does not reserve slots. `run` and
`submit` also check the requested slots against the node capacity. The schema
cannot express four rules the runner enforces: `outer_workers * inner_threads
<= cpu_slots`, the 200-byte key limit, unique input names and contained input
paths.

Input paths are relative to the submitted specification (`model.json` or
`./model.json`). Absolute paths, parent traversal, duplicate names and symlinks
escaping that directory are rejected. Each file is limited to 64 MiB, with at
most 16 inputs. The runner checks hashes, copies inputs into the attempt
directory and validates using a staged copy of the registered executable, in a
`.staging-*` directory under the node root; the root must allow execution,
`TMPDIR` need not. The LP worker checks the model hash again when it starts. The
model is loaded once per worker execution and shared immutably by its tasks.
Worker validation output is capped at 4 MiB. Validation prints the resolved
specification, so this also bounds the specification itself: about 600,000
one-dimensional SQP starts fit, not the 1,000,000 tasks the envelope allows.

The JSON parser enables exact f64 round trips, preserving small numerical
values and reproducible content digests across journal/manifest reads.

The normalized specification and staged executable SHA-256 determine an
attempt's identity. Repeating a key with the same identity returns the existing
job; it never starts a second attempt. A conflicting identity is rejected
(`request_key_conflict`): unlike an idempotency key that only compares the key,
a retry never silently receives the result of different content. A new
experiment needs a new key. The experimental `spec_digest` excludes the request
key but includes the model hashes, solver settings and resource budget. The
worker binary digest and original path are recorded separately in provenance.

## Eight CPU slots

The runner requires:

```text
outer_workers * inner_threads <= cpu_slots <= 1024
```

For eight independent solves or fcmaes runs, use `8 / 8 / 1`. For one LP or
SQP solve with up to eight numerical workers, use `8 / 1 / 8`. `8 / 2 / 4` is
also valid. `8 / 8 / 8` is rejected. fcmaes evaluates the populations of
CMA-ES, CR-FM-NES, PGPE, MODE and MAP-Elites, and the candidate batches of
BiteOpt and DE with `batch`, on `inner_threads` threads per task, with
results that do not depend on the thread count; serial BiteOpt and DE and the
evaluation profiles require `inner_threads=1`. LP-IP and SQP solves support
1–8 inner workers.

Admission reserves `cpu_slots` for the whole attempt, not just the currently
busy tasks. A job asking for more slots than the node has is rejected
(`capacity_exceeded`, with both numbers). Otherwise it waits in state `waiting`
until enough slots are free; concurrent jobs on the same root never reserve
more than the node capacity. LP's component, packing-neighborhood and frontier
workers are forced to one; `Options::threads` controls its numerical kernels.
SQP models and QP backend instances are private to each task. The Clarabel
engine itself remains serial; an eight-thread allowance is not an eightfold
speedup promise.

Slots describe numerical work, not the exact operating-system thread count.
Supervisor, I/O and cancellation-monitor threads also exist. This is cooperative
accounting for these adapters, not CPU affinity or a kernel cgroup quota.
Small kernels may stay serial. No performance improvement is claimed from
adding this API.

## Run, inspect and stop

```sh
optimization-run --root NODE validate --spec JOB.json
optimization-run --root NODE run --spec JOB.json
optimization-run --root NODE jobs list
optimization-run --root NODE jobs get JOB_ID
optimization-run --root NODE jobs events JOB_ID
optimization-run --root NODE jobs wait JOB_ID --timeout 60
optimization-run --root NODE result JOB_DIRECTORY
optimization-run --root NODE jobs artifact JOB_ID results
optimization-run --root NODE jobs cancel JOB_ID
optimization-run --root NODE jobs cancel JOB_ID --now
```

The examples use the executable name for brevity; use `./target/release/optimization-run`
unless it is on your PATH. `run` blocks, prints a final JSON job object, and
captures bounded worker logs. Its exit code reports runner/protocol errors;
a normal cancellation, timeout or solver failure can still return a job object.
Always inspect job `state`, then each mathematical outcome. With a request key
that already names a job, `run` and `submit` start nothing and print that job's
current state, which need not be final; use `jobs wait`. A signal during
validation also stops the validator.

Lifecycle states are `submitted`, `starting` (detached only), `waiting`,
`running`, then `completed`, `cancelled`, `timed_out`, `failed` or `interrupted`.
The wall clock starts after CPU admission; queue time is separate. LP and SQP
also receive the remaining cooperative time limit. A graceful stop sets a
shared cancellation token in LP/SQP; fcmaes finishes active retries, while its
MODE and MAP-Elites runs stop after the current generation and return their
front or archive. Evaluation profiles stop between points. Workers stopped at
the wall deadline may report `termination: "cancelled"`; the job state says
`timed_out`. `--now` allows at most one further second before process-group
termination. The wall limit plus its declared grace always bounds process
supervision. Stop requests only escalate: `jobs cancel`, the launcher's
timeout and its signal handler publish `cancel.request` under a short-held
lock (`cancel.lock` in the job directory), so an immediate request is never
replaced by a graceful one that raced it, nor by the timeout marker.
Cancelling a job that has already ended is an error
(`already_terminal`, like HTTP 409) and writes nothing; a cancel that races
with the job's own end may still be accepted, without effect.

A completed job says that its tasks returned normally. It does not assert an
optimal solution. An infeasible LP is a completed job with claim `infeasible`.
SQP can complete with a local restoration failure. A time/iteration limit can
still retain a feasible candidate. Deadline classification is a lifecycle
decision, independent of a solver's termination reason.

### Errors

A runner error, including a malformed command line, exits with status 2 and
prints one JSON line on stderr (`--help` and `--version` print normally):

```json
{"error":{"code":"request_key_conflict","message":"...","retryable":false}}
```

| Code | Meaning | What helps |
| --- | --- | --- |
| `invalid_job` | The specification is missing or not a valid envelope; an input is missing, escapes its directory or fails its hash; the worker rejected the payload; or the resolved job exceeds the 4 MiB validation output or 30 s | Fix the job |
| `invalid_command` | The command line does not parse | See `--help` |
| `unknown_worker` | No worker is registered under that ID | `workers add` |
| `unsupported_profile` | The worker does not accept the `payload_schema` | Another worker or profile |
| `worker_changed` | The registered executable changed since registration | Register it again |
| `request_key_conflict` | The key names a job with different normalized content or worker | A new key |
| `capacity_exceeded` | `cpu_slots` exceed the node capacity | Fewer slots |
| `node_not_initialized` | The root has no `node.json` | `node init --capacity N` |
| `unknown_job` | No job with this ID on this root | Check the ID and root |
| `already_terminal` | Cancel or repair of a job that has already ended | Nothing to do |
| `attempt_active` | Repair while the attempt's launcher or worker still holds its lock | Wait, then repeat |
| `liveness_unknown` | Repair of an attempt whose locks are free, but whose process group still exists or whose detached unit may still start | Inspect it (`jobs get`, `systemctl --user`); an attempt recorded on an earlier boot counts as ended |
| `systemd_unavailable` | `submit` without a systemd user manager | Foreground `run` |
| `start_unknown` | `submit` could not confirm the unit start; repeating does not launch again | Inspect the unit |
| `runner_error` | Anything else (I/O, a corrupt node file, a worker protocol violation) | Read the message |

`retryable` is true only for `attempt_active`: a live process holds the
attempt, and repeating the identical command after it exits can succeed.
Every other error needs a changed request or operator action. At the job
level, `interrupted` (launcher or host lost) may be run again with a new
request key. A `failed` job needs its `runner.journal_error`, its worker's
`stderr.log` or the runner's message: a worker error repeats with the same
input and deterministic seeds, while a crash, an out-of-memory kill or an I/O
error need not.

## Results and durable recovery

`results.jsonl` commits one checked envelope per completed task. Each envelope
has a schema version and SHA-256 checksum of the exact `payload_json` bytes.
The common worker serializes appends and syncs them before reporting completion.
`events.jsonl` records durable lifecycle transitions. Atomic JSON snapshots
include `job.json`, `resolved.json`, `provenance.json` and final `run.json`.
`worker-process.json` records the process group for conservative liveness checks.

The result schema is `optimization.result/0.2`
(`job-api/schemas/optimization.result-0.2.schema.json`). `results` are ordered
by `task_id` even when tasks finish in a different order. Each contains an
outcome and named work counters. Counters from different solver profiles must
not be added as if they measured the same work.

### Termination, claim and evidence

Each outcome answers three separate questions:

- `termination`: why the task stopped, in the solver's words. Shared names are
  `evaluation_limit`, `iteration_limit`, `node_limit`, `time_limit`,
  `solution_limit`, `objective_limit`, `memory_limit`, `optimizer_stop` (the
  optimizer's own convergence test), `cancelled` and `evaluated` (evaluation
  profiles). Others are solver statuses such as `optimal`, `infeasible`,
  `converged`, `locally_infeasible` or `unsupported`. A termination is never a
  claim.
- `claim`: what the worker asserts about the answer.
- `evidence`: how much of the claim was verified.

| Claim | Meaning | Precedent |
| --- | --- | --- |
| `none` | No claim; inspect termination, details and `evidence.refuted` | MOI `NO_SOLUTION` |
| `feasible` | A point within the declared tolerances; `objective` may be absent (several objectives) | MathOpt `FEASIBLE` |
| `best_found` | fcmaes retry: the best point the optimizer evaluated, not a model mean or a recommendation; no global certificate | COIN-OR OSrL `bestSoFar` |
| `numerical_optimum` | LP/MIP optimal status within numerical tolerances; not an exact certificate | MathOpt, Gurobi `OPTIMAL` |
| `first_order` | SQP convergence whose KKT residuals pass a recomputation; no global or second-order certificate | MOI `LOCALLY_SOLVED` |
| `certified_optimum` | Optimality proven by a certificate that an independent checker verified; no worker emits it yet | SCIP exact mode with VIPR |
| `non_dominated_set` | fcmaes MODE: `details.front`; no single `x` or `objective`; no Pareto-optimality certificate | COCO bi-objective archive |
| `elite_archive` | fcmaes MAP-Elites: `details.elites`; `x`/`objective` are the best elite | none found |
| `infeasible` | The problem has no feasible point (LP; SQP linear rows) | MOI `INFEASIBLE` |
| `unbounded` | The objective is unbounded; a returned point is only a feasible point | MathOpt `UNBOUNDED` |
| `infeasible_or_unbounded` | One of the two holds; with a feasible point, the problem is unbounded if the claim holds | MOI `INFEASIBLE_OR_UNBOUNDED` |
| `locally_infeasible` | SQP elastic mode stopped at a minimizer of the constraint violation that violates constraints; not proof of infeasibility | Gurobi 13, MOI `LOCALLY_INFEASIBLE` |

`numerical_optimum` deliberately does not map to MathOptInterface's `OPTIMAL`,
which asserts a global optimum: like every floating-point solver status, it
holds within tolerances only.

`evidence.level` is one of:

- `claimed`: the claim rests on the solver's report alone. `none` without a
  refutation is `claimed` too; `checks` may still list what was recomputed.
- `rechecked`: the returned points were recomputed from the registered model
  outside the solver; `evidence.checks` lists what (`objective`, `bounds`,
  `constraints`, `integrality`, `kkt`, `non_dominance`, `niche`). Parts of a
  claim that concern points never returned (global optimality, a MIP's dual
  bound) remain the solver's. `infeasible`, `unbounded` and
  `infeasible_or_unbounded` concern the whole problem and are never
  `rechecked`.
- `certified`: an independent checker verified a proof; `evidence.certificate`
  gives its `format` (for example `vipr`, `lrat`, `veripb` or `farkas`),
  `sha256`, `checker`, `verdict` and optionally the `artifact` file. Only
  `certified_optimum` needs it. No worker produces certificates yet; LP-IP's
  native solver checks its infeasibility claims internally with a Farkas row
  but does not export it.

Workers of protocol 0.2 always report evidence. A record without it predates
0.2 and is only `claimed`.

When an independent check rejects the solver's claim, the worker records it
instead of failing the job. `evidence.refuted` names the rejected claim, a
verdict and a message; `claim` then states only what survived the check. The
verdicts are the solver competitions' categories of wrong answers:

| Verdict | Example | Surviving claim |
| --- | --- | --- |
| `infeasible_point` | LP optimal status, but the candidate violates a row; an fcmaes point outside the box | `none` |
| `objective_mismatch` | fcmaes reported a value its point does not evaluate to | `feasible` with the recomputed value, or `none` if that value is unusable; the reported one in `details.reported_objective` |
| `false_optimality` | SQP converged, or an LP is optimal, but the recomputed KKT residuals fail the acceptance (or overflow) | `feasible` |
| `false_infeasibility` | LP infeasible, but the returned point or the task's start is feasible (the outcome then reports that point); SQP locally or linearly infeasible at a feasible point | `feasible` |
| `invalid_certificate` | A checker rejected a certificate | what the other checks support |

A refutation needs a check that actually ran: a status with nothing to check
(LP optimal without a candidate, SQP converged without multipliers) is
neither confirmed nor refuted, and `details.note` says so. Failures that are
not mathematical claims still fail the task: wrong dimensions, non-finite
solver values, work counts outside the declared budget, and set members whose
stored values disagree with their re-evaluation. The SDK checks every outcome
against the rules before committing it, so a worker defect fails one task and
the job, but never discards the results already committed.

`objective_bounds` gives `primal` (the objective of the returned feasible
point) and `dual` (a bound on the optimum the solver proved: a lower bound when
minimizing, an upper bound when maximizing) in the model's `sense`; either may
be null. LP/MIP results and LP evaluations report it. `Outcome::check`
enforces their consistency with `BOUND_TOLERANCE` (relative 1e-6, against
max(1, |a|, |b|)): a `primal` needs `feasible: true` and equals `objective`,
and a `dual` may lie beyond the `primal` by at most the tolerance, so a
minimization with primal 7 and dual 8 is rejected. A worker that cannot
establish a bound leaves it null and keeps the solver's value in `details`
(LP-IP: `reported_best_bound`). `imprecise: true` marks
a claim the engine reached only at relaxed accuracy; it never qualifies `none`.
No current worker sets it.

The runner checks these rules on every journal record and writes manifests
in canonical form: optional objects are omitted rather than null. The schema
and the Rust validator agree, also on null and absent fields, except where a
rule compares two values (the bound rules above), which the schema cannot
express; such cases carry `schema_valid` in the shared list:
`scripts/job-api/outcome_cases.json`, a shared list of valid and invalid
outcomes, runs through `Outcome::check`, through the schema, and as journal
records through the runner.

### Details

LP details preserve objective sense, incumbent, best bound, gaps, warm-start
status and available LP residuals. Infinite gap values are explicit strings
`+infinity` / `-infinity`, not silently converted to JSON null. SQP details keep
KKT residuals, acceptance tolerances, the primal violation, QP backend and raw
status. fcmaes MODE details carry the front, `front_source:
"final_population"` (the feasible non-dominated part of the final population,
not an archive of every point evaluated) and its exact hypervolume with the
reference point and `normalization: "none"`; points outside the reference
point are counted, not clipped. MAP-Elites details carry the elites, coverage
and QD score. Native validation work is counted separately from solver
evaluations/iterations.

### Evaluating given points

`fcmaes.evaluate/1`, `lp-ip.evaluate/1` and `sqp.evaluate/1` evaluate points the
caller supplies, one task per point, without optimizing: an agent or another
solver can have its own candidates checked by the same model and rules. Each
outcome has `termination: "evaluated"`, claim `feasible` or `none`, the
recomputed objective (none for several objectives) and `rechecked` evidence.
fcmaes points must lie inside the model's box, where its registered models are
defined; LP and SQP points may lie outside the bounds and are then
infeasible. A finite point whose values overflow is `none` with no objective,
unknown feasibility, `claimed` evidence and the reason in `details.message`.
Points, like starts, are inline: the resolved job must stay below the 4 MiB
validation output, which bounds a job to far fewer points than the 1,000,000
tasks the envelope allows.

### Accounting and recovery

If a worker is killed, active work is unknown. `work` is null,
`runner.accounting_complete` is false, and `known_work_lower_bound` covers only
committed tasks. A normal cooperative stop accounts for its returned tasks.
No failed or truncated attempt receives fabricated zero-cost totals.

```sh
optimization-run --root NODE jobs reconcile
optimization-run --root NODE jobs repair JOB_ID
```

Reconciliation only releases slots when process termination is established.
Repair refuses a live launcher or worker (`attempt_active`) and unknown
liveness (`liveness_unknown`); an attempt recorded on an earlier boot has no
surviving processes. A launcher
that dies while its job is still queued never started a worker: repair then
seals the attempt as interrupted with zero work and complete accounting,
without a liveness proof. Detached `submitted`/`starting` attempts may still be
started by their unit and stay unknown. Repair tolerates a torn final journal
fragment, preserves a consistent final worker manifest if available, and
otherwise seals the attempt as interrupted. A journal with earlier corruption,
duplicate task IDs or a record that breaks the result rules is never trusted:
such an attempt, and any attempt whose worker wrote one, is sealed `failed` with
no results, `work` null and `runner.journal_error`, which names the task and the
rule. `jobs get` then reports the journal error, and `jobs list` shows it for
that job only. Appends end a torn final fragment first (a valid record gets its
newline, anything else is dropped), so a later record never joins it. After
launcher loss, elapsed time may be unknown. Repair never resumes solver state;
resuming stochastic optimizer state is neither deterministic nor cheap, so a
fresh solve needs a new request key. If the launcher dies between process
creation and durable process-group recording, reservations are conservatively
retained; reboot reconciliation can clear the old boot. Only unfinished jobs
are flagged after a reboot.

`compare` supports the legacy fcmaes behavior. Common results require identical
resolved experiment digests and payload profiles and never select a winner
automatically; it reads 0.1 and 0.2 manifests and warns when arms mix them.
Compare mathematical claims and work counters explicitly when changing
algorithms or resource widths.

## Agents and MCP

The CLI is one agent interface: every command prints JSON, every error has a
code, and the schemas describe the inputs and outputs. `optimization-mcp` is
the other: a Model Context Protocol server over stdio for one node. It is a
second binary of the `optimization-runner` package, so
`cargo build --release --locked -p optimization-runner` builds it next to
`optimization-run`, here and in every worker repository. Each tool drives the
`optimization-run` command line, so the runner's validation, idempotency,
admission and recovery rules apply unchanged.

### Connect a client

The owner of the node initializes it and registers its workers with the CLI
([Build and discover](#build-and-discover)); the server does neither. Then
point an MCP client at the server, with absolute paths:

```sh
# Claude Code
claude mcp add optimization-jobs -- /abs/target/release/optimization-mcp --root /abs/node
```

```json
{"mcpServers": {"optimization-jobs": {
  "command": "/abs/target/release/optimization-mcp",
  "args": ["--root", "/abs/node"]}}}
```

The second form fits clients configured with an `mcpServers` file, such as
Claude Desktop. The options are `--root` (or `OPTIMIZATION_RUN_ROOT`), the node;
`--runner`, the `optimization-run` executable (by default the one next to the
server); `--launch process|systemd` (see below); and `--input-dir`, the
directory that relative input files of inline jobs are read from (by default
the working directory). The server logs one line to stderr when it starts.

### Tools

| Tool | Runner command | Answer |
| --- | --- | --- |
| `describe_node` | `node doctor`, `workers list` | Capacity, launch mode, the workers with their profiles and builds |
| `describe_worker` | `problems describe` | The worker's full description: profiles, models, options, claims |
| `validate_job` | `validate` | The resolved job with its `task_count`, or `invalid_job` |
| `submit_job` | `run` (process) or `submit` (systemd) | The job's handle once it exists; a task for clients with the Tasks extension |
| `get_job` | `jobs get` | State, progress, directory, `observed_state` |
| `wait_job` | `jobs get`, repeated | Returns when the job ends or is observed interrupted, at most after `timeout_seconds` (600); progress notifications on request |
| `get_result` | `result` | A summary: accounting, claim and termination counts, one line per task (the first 100, without points); `tasks` returns complete records, `full` the manifest up to 1 MiB |
| `get_events` | `jobs events` | The last `limit` lifecycle events |
| `get_artifact` | `jobs artifact` | An artifact of the result, up to 1 MiB |
| `list_jobs` | `jobs list` | The jobs, newest first, optionally only active ones |
| `cancel_job` | `jobs cancel` | Graceful stop; completed tasks stay in the result |
| `kill_job` | `jobs cancel --now` | Immediate stop |
| `repair_job` | `jobs repair` | Finalizes a job whose launcher was lost or that a reboot interrupted |

A tool that takes a job accepts it inline, as `job` (an envelope object whose
relative input files are read from `input_dir`, by default the server's
`--input-dir`), or as `spec_path`, a job file whose inputs lie next to it. Its
input schema embeds the envelope schema. An input file is copied for staging
only after its SHA-256 matches, so a job can carry only files whose content
its author already knows.

Results carry `structuredContent` and the same JSON as text. A failed call is
a tool result with `isError: true` and `{"error":{"code","message","retryable"}}`:
one of the [runner's codes](#errors) or one of these:

| Code | Meaning | What helps |
| --- | --- | --- |
| `invalid_arguments` | The tool's arguments do not fit its input schema | Fix the call |
| `not_finished` | `get_result` before the job ended | `wait_job` |
| `result_too_large` | `full` on a manifest over 1 MiB, or any read of a manifest over 256 MiB | `tasks`, or `run.json` in the job directory |
| `mcp_timeout` | A runner call, or the confirmation that a submitted job exists, exceeded its deadline; retryable | `get_job` before submitting again |

### Protocol versions

The server is dual-era. A request that carries
`io.modelcontextprotocol/protocolVersion` in `_meta` is served statelessly
under revision 2026-07-28 (`server/discover` answers without a handshake); an
`initialize` request selects 2025-11-25, 2025-06-18, 2025-03-26 or 2024-11-05
for the process; after an `initialize` with 2025-03-26, JSON-RPC batches are
answered as batches. Another version
gets `UnsupportedProtocolVersion` (`-32022`) listing the supported ones. The
server offers tools only: no resources, prompts, sampling, elicitation or
logging, and `subscriptions/listen` delivers task notifications only.
`notifications/cancelled` stops a request that only reads, such as a long
`wait_job`, without stopping its job. A request that changes a job
(`submit_job`, `cancel_job`, `kill_job`, `repair_job`) runs to its end
regardless and only loses its response: stopping the runner halfway could
leave a job half created.

### Tasks

With the Tasks extension (`io.modelcontextprotocol/tasks`, 2026-07-28) declared
in a request's client capabilities, `submit_job` returns a task that completes
with the job's result, so the client can drive a whole optimization run as
one asynchronous tool call:

| Runner | MCP Tasks | This server |
| --- | --- | --- |
| `submit` / `run` an envelope | `tools/call` returning a task | `submit_job`; a submission that fails returns a tool error, not a task |
| `request_key` | Task IDs are minted by the server | Random 128-bit task IDs, stored in `NODE/mcp/tasks.json`; the same job resubmitted returns its task |
| Job states | `working`, `completed`, `failed`, `cancelled` | `submitted` to `running` → `working`; `completed`, `timed_out`, `failed` and `interrupted` → `completed`, with the summary of `get_result` (`isError` for `failed` and `interrupted`); `cancelled` → `cancelled`, and `get_result` returns its completed tasks. A job observed with a lost launcher or after a reboot stays `working`, with the reason in `statusMessage`, until no process may own the attempt; then `tasks/get` (or a task subscription) finalizes it as `repair_job` would, so a read can change the job, and a worker that outlived its launcher keeps its exact result |
| Graceful cancel | `tasks/cancel` (cooperative) | `cancel_job`; acknowledged also when the job has already ended |
| `--now` | Not defined | `kill_job` |
| Journals | Results may be deleted after the task's TTL | `ttlMs` is null: tasks do not expire, and the journal stays the durable record |
| `jobs list` | Removed from the extension | `list_jobs`, scoped to the node |
| `capacity_exceeded` | Servers should enforce per-requestor limits | A tool error with the slot arithmetic |
| `describe` | Tool input schemas | The envelope schema in the job tools; `describe_worker` for the profiles |
| Task notifications | `subscriptions/listen` with `taskIds` | One `notifications/tasks` per status change, checked every 2 s |

A client without the extension uses the handle pattern: `submit_job` returns
the job ID, then `wait_job` or `get_job`, `get_result` and `cancel_job`.

### Launch, durability and trust

With `--launch process`, the default, `submit_job` starts `optimization-run run`
in a session of its own: the job outlives the server and ends with its result,
its wall time, `cancel_job` or `kill_job`. It does not survive a reboot, which
`get_job` reports as `interrupted_after_reboot` (`repair_job` finalizes the
attempt), nor a logout whose login manager kills the user's processes. With
`--launch systemd`, `submit_job` uses `submit` and needs a systemd user
manager, with the caveats of [detached operation](#detached-operation-and-current-limits).
A killed or restarted server loses only the requests in flight: a new server
on the same root resolves the same jobs and task IDs. The server keeps its own
files in `NODE/mcp/`: the task store; staging copies of inline jobs, removed
once the runner has registered the job; and each launcher's stderr log,
removed when the launcher succeeds while the server runs. A server that
starts removes staging copies and empty logs older than a day. A job file
passed as `spec_path` must be a regular file of at most 64 MiB.

The server bounds what clients make it hold. A message is at most 64 MiB (a
job's input files are files, not part of the message); a longer line is
skipped and answered with `-32600`. At most 64 requests run at a time, of
which at most 32 may wait (`wait_job`, `subscriptions/listen`), so status
calls and cancellations always find room; a request beyond either limit gets
`-32000` with `data.retryable: true`. At most four `validate_job` and
`submit_job` calls run worker validation at a time, which happens before
CPU-slot admission; further ones queue, and a cancelled request leaves the
queue. Input files of an inline job are copied only when the envelope is
valid apart from them (at most 16 inputs of at most 64 MiB each).

The server cannot register or change workers, initialize the node or change
its capacity, and jobs reach only registered workers, admitted against the
node's CPU budget like any other job. Over stdio there is no per-client
authorization: every connected client acts for the node's owner, so connect
only clients that the owner trusts with the node. Like the runner, the
server assumes that a node root belongs to one host: liveness checks, and so
the finalization of interrupted jobs, look at this host's processes only.

## Detached operation and current limits

`submit` uses a real Linux systemd user manager with `KillMode=control-group`
and `Restart=no`, in unit `optimization-job-ID.service` (`fcmaes-ID.service` for
legacy fcmaes jobs); run `node doctor` first. Logout survival requires host-specific
user-manager lingering. Foreground execution and the refusal without a systemd
user manager are tested; detached execution has not yet been accepted on a real
service host. There is no simulated background-success fallback.

This release has no HTTP server (the MCP server speaks stdio), remote simulator plugins, arbitrary Python
callbacks, ask/tell sessions, distributed scheduler, solver checkpoint/resume or
cross-solver pipeline engine. New models are native code registered in a
worker (fcmaes application workers, SQP's extension seam), never callbacks a
job supplies. No worker emits certificates, sets `imprecise`, or records a
best-so-far trace for benchmark tools such as IOHanalyzer, and the LP model
artifact has no MathOptFormat conversion. SQP starts with three native
registered models and a documented extension seam. LP accepts the documented
CSR JSON profile, not arbitrary MPS or every native tuning option. Numerical
cores and their established scope are unchanged by this integration.

## Extending and testing

Implement `worker::Worker::prepare` to deserialize and validate a versioned
payload and resolve defaults. Return a `Prepared` object with task count,
cooperative cancellation and a task-local solve operation. A task must return
its numerical outcome, with evidence, and work counters; `Outcome::check`
states the rules. Record a claim that fails your independent check as a
refutation (`Evidence::refuting`), not as an error. The SDK handles
concurrency, journal commits and final manifests. Do not put solver-specific
assumptions in the runner. Bump a profile version when changing mathematical
input/result meaning.

In this repository, with the fake worker and any workers built elsewhere:

```sh
cargo test --release --locked
cargo build --release --locked -p optimization-runner
python3 scripts/job-api/test_review.py
python3 scripts/job-api/test_mcp.py
# A mixed node with independently built workers:
python3 scripts/job-api/test_integration.py \
  --fcmaes /path/to/fcmaes-job-worker \
  --lp-ip /path/to/lp-ip-job-worker --sqp /path/to/sqp-job-worker
```

In a worker repository, the same scripts run from Cargo's checkout of this
repository, with the binaries of the worker repository:

```sh
cargo build --release --locked -p optimization-runner -p WORKER_PACKAGE
SHARED=$(cargo metadata --format-version 1 --locked | python3 -c 'import json, pathlib, sys; m = json.load(sys.stdin); print(next(pathlib.Path(p["manifest_path"]).parents[2] for p in m["packages"] if p["name"] == "optimization-runner"))')
JOB_API_TARGET=$PWD/target/release python3 "$SHARED/scripts/job-api/test_integration.py"
JOB_API_TARGET=$PWD/target/release JOB_API_TUTORIALS=$PWD/tutorials/job-api \
  python3 "$SHARED/scripts/job-api/test_review.py"
JOB_API_TARGET=$PWD/target/release python3 "$SHARED/scripts/job-api/test_mcp.py"
```

The harness auto-detects the workers in `JOB_API_TARGET` and skips
unavailable solver-specific cases. `test_review.py` holds the runner
regression tests of the 0.1.1 review, the error codes and the schema checks;
it drives a protocol fixture (`fake_worker.py`, which speaks protocol 0.1) and
a real worker when one is built. `test_mcp.py` tests the MCP server in both
protocol eras, with tasks, cancellation, restarts and launch modes, against
the same fixture and a real worker. Its schema checks need the Python
`jsonschema` package; without it they are skipped, unless
`JOB_API_REQUIRE_SCHEMA=1`, as in CI. This repository's CI runs them with the
fake worker, again in a nested PID namespace whose /proc belongs to the
enclosing one, and on a mixed node with all three workers, built from their
repositories' `main` twice: with the shared revision each worker pins (this
runner with released workers), and with their shared dependencies patched to
the checkout under test (a change of the worker SDK inside the real workers,
before they move to it). `scripts/job-api/sdk_source.py` checks which
`optimization-job-api` each build resolved; the workflow also runs weekly.

A change to the shared crates lands here first. A worker repository then
moves to the new revision by changing `rev` in its `Cargo.toml` and running
`cargo update -p optimization-job-api -p optimization-runner`. To develop
both at once, point the worker repository at a local checkout:

```toml
[patch."https://github.com/dietmarwo/optimization-jobs"]
optimization-job-api = { path = "../optimization-jobs/crates/optimization-job-api" }
optimization-runner = { path = "../optimization-jobs/crates/optimization-runner" }
```
