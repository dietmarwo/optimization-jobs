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
| `fcmaes-job-worker` | `fcmaes.retry/1` (BiteOpt or DE, serial or with parallel delayed-feedback batches, CMA-ES with optional IPOP/BIPOP restarts, CR-FM-NES or PGPE retries on registered scalar models), `fcmaes.mode/1` (MODE Pareto fronts), `fcmaes.map-elites/1` (MAP-Elites grid or CVT archives, optional CMA-ME/CMA-MAE emitters), `fcmaes.surrogate/1` (experimental exact-GP Bayesian optimization of expensive deterministic scalar models, including cancellable `Scalar::simulation` callbacks) and `fcmaes.evaluate/1` (given points): deterministic task seeds, exact or declared evaluation budgets, parallel population evaluation; application workers register their own models with parameters and hashed inputs |
| `lp-ip-job-worker` | `lp-ip.solve/1`: sparse LP/MIP artifacts, candidate starts, node/pivot budgets and numerical checks; `lp-ip.evaluate/1`: given points |
| `sqp-job-worker` | `sqp.solve/1`: registered smooth Rust models, initial points, active-set/Clarabel backends and independent KKT checks; `sqp.evaluate/1`: given points |

The shared crates, this guide, the plan, the schemas and the shared test
scripts live in this repository; until October 2026 the three worker
repositories carried identical copies. The crates are at version 0.3.0, the
first release on crates.io. Worker repositories depend on them
through git at a pinned revision, which their `Cargo.lock` records (see the
[README](../README.md)). 0.2.0 adds the result contract 0.2 (evidence,
refutations, objective bounds, infeasibility and certified claims), worker
protocol 0.2, coded runner errors and the JSON Schemas to the 0.1.1
synchronization. Solver dependencies remain in the individual worker crates;
the runner never links all three engines.

Inside the runner, private modules separate admission (the slot ledger),
supervision (process group, bounded logs, stop and deadline handling) and the
execution lifecycle. An adapter supplies the command and interprets how it
ended; the optimization adapter validates worker results, accounts for work
and builds the native manifest. These are implementation boundaries, not a
public Rust plugin API. The only execution kind is `optimization`; a neutral
adapter exists only in the Rust tests.

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

## Choosing a worker and profile

The profile follows from what is known about the problem, not from the
solver's popularity. Each worker repository's `ai-context.md` has the detailed
rules ([fcmaes](https://github.com/dietmarwo/fcmaes-rust/blob/main/ai-context.md),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/blob/main/ai-context.md),
[SQP](https://github.com/dietmarwo/SQP-craft/blob/main/ai-context.md)).

| Problem | Profile | Model |
| --- | --- | --- |
| Linear objective and constraints, continuous or integer variables | `lp-ip.solve/1` | Sparse LP/MIP model artifact (hashed JSON input) |
| Smooth nonlinear objective and constraints with usable derivatives, a local optimum suffices or good starts exist | `sqp.solve/1` | Smooth model registered in a Rust worker |
| Black-box, nonsmooth or multimodal scalar objective with box bounds, evaluations cheap enough for thousands of calls | `fcmaes.retry/1` (BiteOpt, DE, CMA-ES with optional IPOP/BIPOP restarts, CR-FM-NES or PGPE) | Scalar model registered in a Rust worker |
| Expensive deterministic scalar objective (seconds to a minute per call), 1–32 variables, at most 256 calls | `fcmaes.surrogate/1` (experimental) | Scalar or cancellable simulation model |
| Several objectives, a Pareto front is wanted | `fcmaes.mode/1` | Multi-objective model, optional constraints |
| Many diverse good solutions over behavior descriptors | `fcmaes.map-elites/1` | Model with descriptors |
| Check given points, recheck a claim | `fcmaes.evaluate/1`, `lp-ip.evaluate/1`, `sqp.evaluate/1` | As for the solve profiles |

`describe_worker` (MCP) or `problems describe` (CLI) lists each worker's
registered models, options and claims, the JSON Schemas of its payloads and
runnable examples ([Discovery for agents](#discovery-for-agents)); a profile
can only run what a worker registered. Combinations are separate jobs that pass points on explicitly.
For example, the best points of an `fcmaes.retry/1` job can be the `starts`
of an `sqp.solve/1` job when both workers register the same model, and a
result's points can be rechecked with the matching `evaluate` profile.

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
version, resource limits, claims and recovery capabilities, and the schemas
and examples of [Discovery for agents](#discovery-for-agents); registration
reads at most 1 MiB of it. Executables are
trusted local programs: registration is explicit, and jobs cannot supply
executable paths or shell commands. This is a local single-user runner, not a
multi-tenant sandbox or remote service.

### Discovery for agents

A client must be able to build and validate one job per profile from
`describe` (`problems describe`, MCP `describe_worker`) alone, without a
checkout of the worker's repository. Each worker lists three keys for that:

| Key | Content |
| --- | --- |
| `payload_schemas` | For each profile in `profiles`, a strict JSON Schema (draft 2020-12, with `$schema` and an `$id` such as `urn:optimization-jobs:payload:lp-ip.solve/1`) of its payload: `additionalProperties: false` where the worker rejects unknown fields, `required` as the worker requires, types, enums and simple ranges. An optional field the worker treats as absent when it is `null` allows `null` in the schema; one that rejects `null` does not. Rules a schema cannot express (cross-field rules, per-model dimensions, `inner_threads` limits) are in a `$comment` |
| `input_schemas` | Only for profiles that read input files of a fixed format: for each format, such as `lp-ip.model/1`, its JSON Schema |
| `examples` | At least one runnable example per profile, and one for each payload shape (a model with data inputs, say) |

```json
"examples": [{"profile": "lp-ip.solve/1", "description": "one short line",
  "resources": {"cpu_slots": 1, "outer_workers": 1, "inner_threads": 1},
  "limits": {"wall_time_seconds": 30.0, "grace_seconds": 1.0},
  "payload": {"model_input": "model", "...": "..."},
  "inputs": [{"name": "model", "file": "model.json", "format": "lp-ip.model/1", "content": {"...": "..."}}]}]
```

An example input holds a JSON value in `content` or a UTF-8 string
(CSV and other text) in `content_text`; `format`, if present, names a key of
`input_schemas`. A hash is never part of an example: the client writes each
input with any JSON serializer, hashes the bytes it wrote, and turns the
example into a job by adding `schema_version` (`optimization.job/0.1`), a
fresh `request_key`, the registered worker ID and `payload_schema` (the
example's `profile`). That job passes `validate` and `run` on a one-slot
node, unless its profile needs more, and completes with at least one task
in a few seconds. Over MCP, `put_input` stores each input and returns its
file and SHA-256 ([Tools](#tools)). Every payload a worker accepts must
validate against its schema; the worker's own tests and this repository's
harness check it ([Extending and testing](#extending-and-testing)).

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

`node doctor` reports in `host` what the host gives the runner's process,
which its workers inherit, with null for anything it cannot read:

| Field | Meaning and source |
| --- | --- |
| `logical_cpus` | Online CPUs (`/sys/devices/system/cpu/online`) |
| `affinity_cpus` | CPUs of the affinity mask (`Cpus_allowed_list` in `/proc/self/status`) |
| `cgroup_cpu_limit` | The cgroup CPU quota in CPUs (v2 `cpu.max`, v1 `cpu.cfs_quota_us` / `cpu.cfs_period_us`), the most restrictive from the process's cgroup to the root |
| `usable_cpus` | `max(1, floor(min(affinity_cpus, cgroup_cpu_limit)))` |
| `physical_cores` | Distinct (package, core) pairs among the allowed CPUs (sysfs `topology`) |
| `numa_nodes` | `/sys/devices/system/node/node*` |
| `memory_total_bytes`, `memory_available_bytes` | `MemTotal` and `MemAvailable` of `/proc/meminfo` |
| `cgroup_memory_limit_bytes` | v2 `memory.max`, v1 `memory.limit_in_bytes`, the most restrictive on the path; null without a limit |
| `usable_memory_bytes` | `min(memory_available_bytes, limit - usage)` over the cgroups with a limit |

Its `warnings` include a capacity above `usable_cpus` ("capacity 64 exceeds
the 8 CPUs usable by this process (affinity or cgroup quota)"). `node init
--capacity N` prints the same warning in its `warnings` but initializes the
node: its owner may mean it. LP and SQP inner threads beyond
`physical_cores` share cores. MCP `describe_node` includes `host` and
`warnings`.

## Run, inspect and stop

```sh
optimization-run --root NODE validate --spec JOB.json
optimization-run --root NODE run --spec JOB.json
optimization-run --root NODE jobs list
optimization-run --root NODE jobs get JOB_ID
optimization-run --root NODE jobs execution JOB_ID
optimization-run --root NODE jobs events JOB_ID
optimization-run --root NODE jobs wait JOB_ID --timeout 60
optimization-run --root NODE result JOB_DIRECTORY
optimization-run --root NODE jobs artifact JOB_ID results
optimization-run --root NODE jobs artifact JOB_ID NAME --offset 0 --limit 100
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

### Trusted local command jobs and binary files

These interfaces require source after 0.3.0. Command jobs use
[`execution.command/0.1`](job-api/schemas/execution.command-0.1.schema.json),
not an optimization envelope. Enable them explicitly on a node:

```sh
optimization-run --root NODE node init --capacity 8 --allow-commands
# For an existing node:
optimization-run --root NODE node commands --enable
optimization-run --root NODE validate --spec command.json
optimization-run --root NODE run --spec command.json
optimization-run --root NODE jobs execution JOB_ID
optimization-run --root NODE result JOB_DIRECTORY
optimization-run --root NODE jobs collect JOB_ID OUTPUT_NAME --destination NEW_FILE
```

`submit --spec` also accepts commands when the systemd user manager is available.
`node commands --disable` rejects new validation/submission; already accepted
attempts can finish. Commands share the optimization admission ledger, queue,
wall deadline, bounded logs, cancellation and conservative repair rules. They
receive SIGTERM as a process group on cancellation or wall expiry, followed by
SIGKILL after `grace_seconds` (`--now` caps the delay at one second). Optimizer
workers retain their cooperative cancellation protocol.

A complete minimal request:

```json
{
  "schema_version": "execution.command/0.1",
  "request_key": "inspect-001",
  "argv": ["/usr/bin/printf", "%s\n", "literal $(text); *"],
  "env": {},
  "resources": {"cpu_slots": 1},
  "limits": {"wall_seconds": 30, "grace_seconds": 1},
  "replay": "never",
  "inputs": [],
  "outputs": []
}
```

Arguments are passed literally, with no implicit shell. To run a script, declare
it as a hashed input and use an explicit interpreter, for example
`["/usr/bin/python3", "scripts/run.py"]`. An absolute executable is canonicalized,
hashed during staging, and checked again before launch. A relative executable
must be `./path` naming a declared input with `executable: true`. Interpreter
libraries, compiler dependencies and other host files are **not** snapshotted.
Changes between the final check and exec are outside the trusted-user model.

The environment is cleared, then initialized with `PATH=/usr/bin:/bin` and
`OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1`; explicit `env` entries
can override those defaults. No inherited HOME, secrets or interactive stdin is
provided. Unknown request fields are rejected. `argv` and environment values
are each limited to 64 KiB combined; an argument/value is at most 16 KiB.

An input is `{"path":"data/model.bin","file":"model.bin","bytes":123,
"sha256":"<64 lowercase hex digits>","executable":false}`. `file` is relative
to the request file's directory; omit it to use a verified node blob. Copies go
under the attempt's `work/`, which is the process working directory. Inputs are
checked again before launch. Both source and work paths reject absolute paths,
dot components, symlinks and reserved runtime names. Input/output paths cannot
overlap. There are at most 128 declarations total, 64 MiB per file and 256 MiB of
input bytes plus declared output limits per job.

An output is `{"name":"answer","path":"out/answer.bin","max_bytes":1024,
"required":true}`. After the process group is confirmed stopped, declared
regular files are copied into `.command-outputs/`. Missing required, oversized,
symlink or non-regular outputs are errors; missing optional outputs are omitted.
A zero exit plus valid required outputs means `completed`. Otherwise the result
is `failed`, unless cancellation, timeout or interruption already applies.
The separate
[`execution.command.result/0.1`](job-api/schemas/execution.command.result-0.1.schema.json)
attachment (`command-result.json`) records exit/signal, collected byte counts
and SHA-256 values and collection errors. It has no objective, feasibility,
claim or evaluation accounting. `result JOB_DIRECTORY` verifies the attachment
against the terminal execution record; `jobs collect` verifies a sealed output
before writing a new destination. Later changes to `work/` do not change a
sealed output. Failed collection can be retried without re-executing the command.

`replay: "never"` means no automatic execution retry. Repeating a request key
with the same normalized spec, executable and input digests returns the same
attempt, including a failed one. Moving a source file without changing its
staged path/content does not change identity. Changed work requires a new key;
command and optimizer keys share one namespace. A lost launcher requires
`jobs repair` after liveness checks succeed. Command repair reports
`interrupted`, never an invented successful exit or elapsed time; any verifiable
outputs may still be collected. It never replays side effects.

Generic binary staging is also available without command opt-in:

```sh
optimization-run --root NODE files put --source FILE --bytes N --sha256 SHA256
# --source - reads raw binary stdin; no base64 or JSON wrapping.
optimization-run --root NODE files get SHA256 --bytes N --destination NEW_FILE
optimization-run --root NODE files cleanup
```

Transfers stream through private temporary files, check exact length and hash,
fsync and publish without overwriting an existing destination. Re-uploading an
already verified blob is idempotent and does not consume stdin. A truncated or
corrupt transfer never publishes a verified blob. The node blob store has a
1 GiB quota including upload partials; `files cleanup` takes its upload lock and
removes only `.transfer-*` partials. Verified blobs, attempts and collected files
are retained until the owner explicitly removes them. A process killed during
a download/collection can leave `.transfer-*` beside the destination; after
confirming no writer is active, remove that partial and retry. A killed staging
process can similarly leave an unindexed `.command-*` directory; inspect it
before manual cleanup. No automatic garbage collection deletes finished work.

Commands are **trusted programs under the runner's Unix user**, not a sandbox.
Path checks protect materialization and collection; programs can still access
other host files and create undeclared/unbounded working data. CPU slots are
admission accounting, not kernel CPU/memory/disk enforcement. Descendants in the
original process group are terminated; a process that deliberately changes
session/group can escape it. Do not use this interface for hostile or daemonizing
programs. There is no remote transport or fleet scheduling in this interface.

The MCP server is optimization-only: `validate_job` and `submit_job` refuse
command requests with `unsupported_job_kind`. Every runner the server starts
refuses them too (the server sets `OPTIMIZATION_RUN_REFUSE_COMMANDS`), so a
`spec_path` that changes after the server read it cannot become a command.
Discovery advertises command/file support as CLI-only; MCP result summaries
reject command jobs with `unsupported_job_kind`. Use the CLI for command
results and binary outputs.
`compare` remains an optimization operation.

The executable [build–run–collect example](../examples/commands/build_run_collect.py)
compiles a declared C input, collects and uploads the resulting executable,
stages it into a second command and verifies the three-byte binary answer:

```sh
python3 examples/commands/build_run_collect.py \
  --runner target/release/optimization-run --output /tmp/command-example
```

### Execution discovery and terminal observations

These commands are not in 0.3.0: they need a runner built from `main`
after that release (see `[Unreleased]` in the changelog). The versions of the
job, worker and native result contracts are unchanged.

```sh
optimization-run node capabilities
optimization-run --root NODE jobs execution JOB_ID
```

`node capabilities` works without creating or initializing a node. Its
`execution.capabilities/0.2` object is also included as `capabilities` in
`node doctor` and MCP `describe_node`. It lists supported kinds (`optimization`
and `command`), enabled kinds, accepted job/worker schemas, result/record schemas,
and byte limits. Commands are disabled by default; generic binary file transfer
is implemented through the CLI. Fleet execution remains false. The
[capability schema](job-api/schemas/execution.capabilities-0.2.schema.json) is
separate from worker `describe`: solver profiles still come from each worker.
The previous capability schema remains available for older runners.

`jobs execution` reads the additive
[`execution.record/0.1`](job-api/schemas/execution.record-0.1.schema.json)
sidecar `.execution.json`. A normal finalization writes the native `run.json`
(or `command-result.json` for commands),
then the sidecar, then terminal `job.json`, all with atomic replacements.
A crash between these writes still needs the existing conservative `repair`;
reading a sidecar never authorizes a retry or frees a reservation.

The record contains attempt ID and content identity, execution kind, terminal
state, declared CPU slots (limits remain adapter-specific), timestamps, process exit code **or** signal when
observed, stop reason, containment, and references to bounded stdout/stderr.
It attaches the native result by relative filename, schema version, byte count
and SHA-256 of the finalized file. It contains no objective, feasibility,
claim, evidence or work counters: use the native result for these. An exit
code of zero without a valid optimization manifest still means a failed job.
Legacy `fcmaes.job/0.1` keeps its integer native result schema version `1`.
The hidden filename avoids collisions with existing named worker artifacts;
it is read through this CLI command, not `jobs artifact` or a new MCP tool.

`source: "launcher"` records the duration measured during launch (zero for
cancellation before admission). `source: "repair"` cannot recover an observed
exit code: `observation.process` is null. Its elapsed time is zero for an
unadmitted attempt, the validated worker duration for a recovered complete
manifest, or null if unknown. Old provenance without a content identity keeps
`identity: null`; its attempt ID can come from `job.json`. Unknown containment
retains slots, just as before extraction.

`jobs execution` serves a record only when `job.json` is terminal with the
same state and `finished_at`. An attempt that has not finished returns
`attempt_active` (retryable: call again after `jobs wait`, or repair the
attempt if its launcher was lost). A finished attempt without a matching record
returns `execution_unavailable`: it was finished by a runner without records,
or the file was not written by this attempt's finalization (the worker runs in
the job directory). Existing `jobs get`, result inspection and recovery
continue to work; old terminal attempts are not backfilled or rerun. A corrupt
sidecar returns `runner_error` and does not affect native inspection.

`source: "repair"` reports `containment: "not_started"` when the attempt never
reached `running` (the launcher writes it before it spawns the worker), and
`"stopped"` otherwise, since repair runs only after both locks are free.

### Errors

A runner error, including a malformed command line, exits with status 2 and
prints one JSON line on stderr (`--help` and `--version` print normally):

```json
{"error":{"code":"request_key_conflict","message":"...","retryable":false}}
```

| Code | Meaning | What helps |
| --- | --- | --- |
| `invalid_job` | The specification is missing or not a valid envelope; an input is missing, escapes its directory or fails its hash; the worker rejected the payload; or the resolved job exceeds the 4 MiB validation output or 30 s | Fix the job |
| `commands_disabled` | The node has not enabled trusted command jobs | Owner uses `node commands --enable` |
| `invalid_command_spec` | Malformed command, changed staged identity/executable or invalid declaration | Correct the request; use a new key for changed work |
| `file_transfer_failed` | Unsafe path, hash/size/quota failure, or destination already exists | Inspect inputs/partials and retry transfer to a new destination |
| `unsupported_job_kind` | Optimization-only operation given a command, including any command request over MCP | Use the CLI: `run`, `result`, `jobs collect` |
| `invalid_command` | The command line does not parse, asks for pages of an artifact that is not `records`, or a page `limit` outside 1–10,000 | See `--help` |
| `unknown_worker` | No worker is registered under that ID | `workers add` |
| `unsupported_profile` | The worker does not accept the `payload_schema` | Another worker or profile |
| `worker_changed` | The registered executable changed since registration | Register it again |
| `request_key_conflict` | The key names a job with different normalized content or worker | A new key |
| `capacity_exceeded` | `cpu_slots` exceed the node capacity | Fewer slots |
| `node_not_initialized` | The root has no `node.json` | `node init --capacity N` |
| `unknown_job` | No job with this ID on this root | Check the ID and root |
| `already_terminal` | Cancel or repair of a job that has already ended | Nothing to do |
| `execution_unavailable` | `jobs execution` of a finished attempt without a matching record (finished before records existed) | Use `jobs get` and the result |
| `unknown_artifact` | The job has no artifact of that name, or its file does not exist yet | A name from `artifact_index` (`jobs get` or the result) |
| `artifact_too_large` | A whole read of an artifact over 1 MiB, or a page whose first record exceeds 1 MiB | Pages (`--offset`, `--limit`) of a `records` artifact, or the file in the job directory |
| `attempt_active` | Repair while the attempt's launcher or worker still holds its lock; `jobs execution` before the attempt has finished | Wait (`jobs wait`), then repeat |
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
include `job.json`, `resolved.json`, `provenance.json`, final `run.json` and
the additive terminal `.execution.json` record.
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
| `best_found` | fcmaes retry and surrogate: the best point the optimizer evaluated, not a model mean or a recommendation; no global certificate | COIN-OR OSrL `bestSoFar` |
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

### Artifacts

Artifacts are files of a job attempt that agents read through the runner,
while the job runs and after it ends. `results` (the journal `results.jsonl`)
is always one. A worker adds its own, such as an evaluation log or a
warm-start snapshot, by declaring each before its first write:
`artifact::declare(base, &Declaration::records(name, file).task(task).describe(text))`
in `Prepared::solve`, where `base` is the directory `Worker::prepare`
received; never in `prepare`, which also runs for validation. A declaration
is a checked record (the journal framing, version 1) in `artifacts.jsonl` of
the attempt directory, with `name`, `file`, `format` and optionally
`task_id` and a `description` of at most 200 bytes, so workers written in
other languages declare artifacts the same way. Names and files are unique
plain names: not `results`, no file of the runner, nothing that starts with
`.` or ends in `.lock` or `.tmp`; at most 4096 per attempt.

| Format | Written with | Read |
| --- | --- | --- |
| `records` | `storage::append_checked`, any record version | Whole up to the last complete line, or in pages of complete records whose checksums hold |
| `json` | `storage::write_atomic_json` | Whole |

```sh
optimization-run --root NODE jobs get JOB_ID   # artifact_index: file, format, bytes, task, description
optimization-run --root NODE jobs artifact JOB_ID NAME
optimization-run --root NODE jobs artifact JOB_ID NAME --offset 0 --limit 100
```

A whole read returns `content`, `bytes` and `sha256`, at most 1 MiB. A page
returns the payloads of records `offset` to `offset + limit - 1` (`limit` 1 to
10,000, by default 100; at most 1 MiB of payload, but always one record),
`next_offset` and `available`, the number of complete (newline-terminated)
records in the file now. A page reads the file once and keeps only its own
records in memory, so long logs page in time proportional to their size and
constant memory.
Continue at `next_offset` while it is below `available`; while the job runs
(`final: false`), `available` grows. When the attempt is sealed, the manifest
lists every declared file that exists in `artifacts` (name to file), and
`runner.artifact_index` records its format, size, SHA-256, task and
description; a whole read after the end fails if the file no longer matches
its digest. Problems with declarations (a broken declaration file, a file
that is not a regular file) appear in `runner.artifact_errors` and in
`jobs get`; they never fail the job or change its results, and a broken
declaration file leaves `results` alone. A runner that predates declarations
ignores `artifacts.jsonl`, so workers that declare artifacts run on it
unchanged. Artifacts are what the worker reports, not rechecked claims.

An artifact can be an input of a later job, which is how a run continues
(the surrogate profile's warm start, for example): the input names the
artifact's `file` with the SHA-256 from `runner.artifact_index`. Over MCP,
pass the earlier job's `directory` (from `get_job` or `get_result`) as
`input_dir`, or, to combine it with other inputs, store it with `put_input`
and `from_artifact` ([Input files and the guide](#input-files-and-the-guide));
with the CLI, copy the file next to the job file. An input file holds at
most 64 MiB.

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
server); `--launch process|systemd` (see below); `--input-dir`, the
directory that relative input files of inline jobs are read from (by default
the working directory); and `--input-store-bytes`, the size limit of the
[input store](#input-files-and-the-guide) (1 GiB by default). The server
logs one line to stderr when it starts.

### Tools

The server has fifteen tools:

| Tool | Runner command | Answer |
| --- | --- | --- |
| `get_guide` | none (a copy of `ai-context.md` in the server) | The guide that chooses a solver and profile, whole or one section; call it first when none is chosen |
| `describe_node` | `node doctor`, `workers list` | Capacity, launch mode, the host's CPUs and memory with warnings, execution capabilities, the workers with their profiles and builds |
| `describe_worker` | `problems describe` | The worker's full description: profiles, models, options, claims, payload schemas and runnable examples |
| `put_input` | none (the input store); `jobs get` for an artifact | `file`, `sha256`, `bytes` and `input_dir` of a stored input file |
| `validate_job` | `validate` | The resolved job with its `task_count`, or `invalid_job` |
| `submit_job` | `run` (process) or `submit` (systemd) | The job's handle once it exists; a task for clients with the Tasks extension |
| `get_job` | `jobs get` | State, progress, directory, `artifact_index`, `observed_state` |
| `wait_job` | `jobs get`, repeated | Returns when the job ends or is observed interrupted, at most after `timeout_seconds` (600); progress notifications on request |
| `get_result` | `result` | A summary: accounting, claim and termination counts, one line per task (the first 100, without points) and the artifact index; `tasks` returns complete records, `full` the manifest up to 1 MiB |
| `get_events` | `jobs events` | The last `limit` lifecycle events |
| `get_artifact` | `jobs artifact` | An [artifact](#artifacts), also while the job runs: whole up to 1 MiB, or a page of records with `offset` and `limit` |
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
| `invalid_arguments` | The tool's arguments do not fit its input schema; invalid base64 or an input over 64 MiB (`put_input`); a section no heading contains (`get_guide`) | Fix the call |
| `input_store_full` | `put_input` would make the input store larger than `--input-store-bytes`; the message has the numbers | Content already stored needs no room; the node's owner raises the limit or removes files, or a restart removes those unused for 7 days |
| `not_finished` | `get_result` before the job ended | `wait_job` |
| `result_too_large` | `full` on a manifest over 1 MiB, or any read of a manifest over 256 MiB | `tasks`, or `run.json` in the job directory |
| `mcp_timeout` | A runner call, or the confirmation that a submitted job exists, exceeded its deadline; retryable | `get_job` before submitting again |

### Input files and the guide

A client that shares no files with the server stores input files with
`put_input`. It takes exactly one of `content` (text, stored as its UTF-8
bytes; a JSON input as the text its serializer wrote), `content_base64`
(bytes) or `from_artifact` (`{"job_id": ..., "name": ...}`: an
[artifact](#artifacts) of an existing job as a whole `get_artifact` read
returns it, checked against the SHA-256 of the sealed manifest). It writes
the bytes atomically to `NODE/mcp/inputs/SHA256` and returns `file` and
`sha256` (both that lowercase hex digest), `bytes` and `input_dir`, the
store's absolute path. The job lists `{"name": ..., "file": FILE,
"sha256": SHA256}` in `inputs` and is validated and submitted with that
`input_dir`. All stored inputs share it, so one job can combine a new model
with an earlier job's artifact. Storing the same content again returns the
same answer and refreshes the file's modification time.

An input holds at most 64 MiB (invalid base64 or a larger input is
`invalid_arguments`); a message holds at most 64 MiB too, so
`content_base64` carries a little under 48 MiB. The store holds at most
`--input-store-bytes`; storing more fails with `input_store_full`. A server
that starts removes stored files not stored again for 7 days; jobs copy
their inputs when they are created, so this never affects a job. The store
holds data, never code, and a name that is a SHA-256 cannot traverse paths.

`get_guide` returns [`ai-context.md`](../ai-context.md), the entry point
that chooses among the solvers, to clients that cannot read this
repository; the server carries a copy. With `section`, it returns the first
section whose heading contains that text, case-insensitively, through to
the next heading of the same or a higher level; a text that no heading
contains is `invalid_arguments`, with the list of headings. The server's
instructions tell an agent that has not chosen a solver or profile to call
it first.

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
| `describe` | Tool input schemas | The envelope schema in the job tools; `describe_worker` for the profiles, their payload schemas and examples |
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
once the runner has registered the job; each launcher's stderr log,
removed when the launcher succeeds while the server runs; and the input
store `inputs/` of `put_input`. A server that starts removes staging copies
and empty logs older than a day and stored inputs unused for 7 days. A job
file passed as `spec_path` must be a regular file of at most 64 MiB.

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
refutation (`Evidence::refuting`), not as an error. Declare files that agents
should read, such as logs and snapshots, as [artifacts](#artifacts). List a
payload schema and runnable examples of every profile in `describe`
([Discovery for agents](#discovery-for-agents)). The SDK
handles concurrency, journal commits and final manifests. Do not put solver-specific
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
unavailable solver-specific cases. For every real worker, it checks the
[discovery keys](#discovery-for-agents) strictly (`discovery.py`): a profile
without a payload schema or an example fails; every schema must be a valid
draft 2020-12 schema, every example payload and every example input with a
format must validate, and a payload with an unknown field must not. Every
example becomes a job (inputs written and hashed, a fresh `request_key`) that
must validate, run and complete with at least one task, and every payload
the shared scripts give a real worker must validate against its schema. For
each optional top-level field of an example, set to `null`, the schema and
the worker must agree on whether the payload is valid.
`test_review.py` holds the runner
regression tests of the 0.1.1 review, the error codes and the schema checks;
it drives a protocol fixture (`fake_worker.py`, which speaks protocol 0.1 and
lists payload schemas and examples, so the discovery checks run without real
workers) and a real worker when one is built. `test_mcp.py` tests the MCP
server in both protocol eras, with tasks, cancellation, restarts, launch
modes, the input store and the guide, against the same fixture and a real
worker, and runs every example MCP-only: `describe_worker`, `put_input` for
its inputs, `validate_job` with the store as `input_dir`, `submit_job`,
`wait_job` and `get_result`. The schema checks need the Python
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
