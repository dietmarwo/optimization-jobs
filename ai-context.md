# AI entry point: optimization with fcmaes, LP-IP-craft, SQP-craft and optimization-jobs

Last reviewed 2026-10-20 against `main` at `423cd87` plus the release
preparation (#7). That state has the crates `optimization-job-api` and
`optimization-runner` 0.2.0, the envelope `optimization.job/0.1` and the
result contract `optimization.result/0.2`, and the three workers pin
`423cd87`. In another checkout, check `Cargo.toml`, the
`describe_node`/`describe_worker` output and the linked guides before you rely
on a command, option or claim.

Start here when a user wants something optimized and no solver has been
chosen yet, whether you will work through MCP, a shell or the user's own code.
This file covers:

1. which solver fits the problem;
2. whether to call it as a library or run it as a job, either through the
   shell (`optimization-run`) or through MCP (`optimization-mcp`);
3. how to install it;
4. the job API and the MCP server, enough to run and read jobs.

Each solver repository's `ai-context.md` has the detailed modelling rules,
options and checks. Read the one for the chosen solver before you write the
model ([where to read next](#where-to-read-next)).

## The toolbox

| Repository | Solves | Libraries | Job worker: profiles | Registries |
| --- | --- | --- | --- | --- |
| [fast-cma-es](https://github.com/dietmarwo/fast-cma-es) | Black-box, nonsmooth, multimodal, multi-objective and quality-diversity problems, with the objective in Python | `fcmaes` (Python, C++ backend) | none | PyPI `fcmaes` |
| [fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust) | The same algorithms in pure Rust, plus experimental exact-GP Bayesian optimization of expensive simulations | `fcmaes-core` (Rust), `fcmaes_rust` (Python binding) | `fcmaes-job-worker`: `fcmaes.retry/1`, `fcmaes.mode/1`, `fcmaes.map-elites/1`, `fcmaes.surrogate/1` (experimental), `fcmaes.evaluate/1` | crates.io `fcmaes-core`, PyPI `fcmaes-rust`; worker and surrogate from source |
| [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) | LP and MIP (linear objective, linear rows, continuous and integer variables) | `lp-ip-craft`, `lp-ip-craft-native` (Rust), `lp_ip_craft` (Python) | `lp-ip-job-worker`: `lp-ip.solve/1`, `lp-ip.evaluate/1` | none yet: from source |
| [SQP-craft](https://github.com/dietmarwo/SQP-craft) | Smooth constrained NLP, at most 256 variables, analytic derivatives | `sqp-craft-solver` with the Clarabel and active-set backends (Rust), `sqp_craft` (Python) | `sqp-job-worker`: `sqp.solve/1`, `sqp.evaluate/1` | none yet: from source |
| optimization-jobs (this one) | No solver of its own: the job envelope, result contract, worker SDK, runner and MCP server | `optimization-job-api` (worker SDK) | runner `optimization-run`, MCP server `optimization-mcp` | none yet: from source |

The two fcmaes projects are independent implementations of the same algorithm
family. fast-cma-es is the one for objectives written in Python. fcmaes-rust
is the one for objectives in Rust and for job workers.

## 1. Write a short problem card

Establish these facts from the user's code and data before choosing. Ask only
for what you cannot infer and what would change the choice.

- **Variables:** how many; continuous, integer or binary, categorical, or
  structured (permutations, routes, graphs); finite bounds?
- **Model structure:** are the objective and constraints linear, smooth with
  available derivatives, or a black box (nonsmooth, noisy, multimodal, a
  simulation that can fail)?
- **Wanted output:** how many objectives, and does the user want one
  solution, a Pareto front or many diverse good solutions over behavior
  descriptors?
- **Cost:** how long one evaluation takes, the evaluation, wall-time and core
  budget, and whether evaluations can run in parallel.
- **Where the model lives:** Python code, Rust code, a data file (an LP/MIP),
  or an external program.
- **How it must run:** a call inside the user's program, or a durable,
  budgeted job that an agent submits, watches, cancels and reads later.
- **Evidence:** a good feasible point, a local optimum with an independent
  KKT check, or a bound and gap.

## 2. Choose the solver

Take the first row that matches.

| Problem | Solver | Limits to check |
| --- | --- | --- |
| Linear objective and constraints, continuous and/or integer variables | LP-IP-craft | A MIP needs finite bounds on every variable (or bounds presolve can infer); no QP/MIQP; no relative-gap stop; numerical statuses, no exact certificates |
| Smooth nonlinear objective and constraints, continuous variables, at most 256, gradient and Jacobian available; a local optimum suffices or good starts exist | SQP-craft | Local method with dense BFGS; use multistart for multimodal models. More than 256 variables or exact Hessians: an IPOPT-family solver fits better |
| Several objectives, a Pareto front wanted | fcmaes MODE | Constraints come after the objectives and are feasible at `g(x) <= 0` |
| Many diverse good solutions over behavior descriptors | fcmaes MAP-Elites (grid or CVT archives) | Descriptors must be computed with the objective |
| Expensive deterministic scalar simulation (seconds to a minute per call), continuous box, 1–32 variables, at most 256 calls | `fcmaes.surrogate/1` (fcmaes-rust job worker, experimental), compared with BiteOpt | No constraints, noise or mixed variables; prefer BiteOpt for separable, many-modal problems with ten or more variables |
| Black-box, nonsmooth, noisy or multimodal scalar objective with box bounds; integers or categories decoded from continuous variables | fcmaes retry: BiteOpt first; DE for robust exploration and integer decoding; CMA-ES with a good start; CR-FM-NES for higher dimensions; PGPE for noise and very high dimensions | Benchmark at least two choices on equal budgets and seeds |

Rules that hold across the table:

- Do not pick a gradient-free optimizer just because the model is a
  simulation. If the whole map from decisions to objective is differentiable
  and the gradients are reliable, a gradient method uses far fewer
  evaluations.
- Global then local: points from an fcmaes run can be the starts of an SQP
  solve. In process this is ordinary code. As jobs, the agent passes the
  points between two jobs, and both workers must register the same model.
- No solver here certifies a global optimum, proves MINLP optimality or emits
  exact certificates. fcmaes on a decoded integer model is a heuristic.
- Recheck any claim, including another tool's, with the matching `evaluate`
  profile or the library's independent checks (`lp_ip_craft.evaluate`,
  `sqp_craft.kkt_residuals`).

## 3. Choose the interface: library or job

| Situation | Use |
| --- | --- |
| The objective is a Python function | A library in process: `fcmaes` (black box, MODE, MAP-Elites), `sqp_craft.solve(spec, model, x0, method="sqp")`, `lp_ip_craft.solve(model, backend="native")`, or `fcmaes_rust` for the Rust implementations |
| The objective is Rust code | The crates (`fcmaes-core`, `sqp-craft-solver`, `lp-ip-craft-native`), or a model registered in a job worker |
| An LP or MIP given as data | A job with an `lp-ip.model/1` artifact (no code needed), or `lp_ip_craft` in Python |
| Durable, CPU-budgeted, cancellable runs with independently checked results; several solvers on one CPU budget; an agent that must not block on a long run | The job API, through the shell or MCP |

A job names a model that its worker has registered. It can carry hashed data
files, but never Python callables, source code, executable paths or shell
commands. Without writing Rust, a job can run:

- any LP or MIP, as a hashed JSON model artifact (`lp-ip.solve/1`);
- the registered benchmark models of the fcmaes and SQP workers, which are
  useful for testing a node but are not user problems;
- checks of given points with the `evaluate` profiles.

A user's own nonlinear model becomes a job model as Rust code in a worker:

- **fcmaes:** an application worker, i.e. a closure with parameters and
  SHA-256-checked data inputs (see fcmaes-rust's
  [application models](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/job-api/models.md)).
  `Scalar::simulation` covers cancellable simulations.
- **SQP:** the worker's extension seam (see SQP-craft's
  [ai-context](https://github.com/dietmarwo/SQP-craft/blob/main/ai-context.md#registered-models-only)).

Otherwise use the library.

With the Python libraries, a cheap Python objective called from native
threads still needs the GIL, so it rarely scales across threads. Instead:

- fast-cma-es's `retry`, `advretry` and `moretry` evaluate in processes;
- vectorized or ask/tell evaluation suits evaluators the user owns;
- a Rust objective avoids the boundary altogether.

## 4. Install

The packages on PyPI and crates.io install with the usual commands; the rest
build from source. Each README has a section "Install from source", which
lists the requirements and our own dependencies.

### Python

```sh
python -m pip install fcmaes        # fast-cma-es; CPython 3.10+; wheels for Linux, macOS, Windows
python -m pip install fcmaes-rust   # import fcmaes_rust; CPython 3.11-3.13
```

From source, each in its own checkout. The Rust toolchain comes from
https://rustup.rs, and pip fetches the build backends itself.

```sh
# fast-cma-es: C++17 compiler; Eigen 3.4 from the system or fetched as here
git clone https://github.com/dietmarwo/fast-cma-es
(cd fast-cma-es && python -m pip install . --config-settings=cmake.define.FCMAES_FETCH_EIGEN=ON)
# LP-IP-craft (Rust 1.85+), SQP-craft (Rust 1.85+ and a C linker), fcmaes-rust (Rust 1.88+)
git clone https://github.com/dietmarwo/LP-IP-craft
(cd LP-IP-craft && python -m pip install .)
git clone https://github.com/dietmarwo/SQP-craft
(cd SQP-craft && python -m pip install .)
git clone https://github.com/dietmarwo/fcmaes-rust
(cd fcmaes-rust && python -m pip install .)
```

None of these Python packages depends on another repository of ours.

The registry releases (fcmaes 2.0.3, fcmaes-rust and `fcmaes-core` 0.1.5)
predate the October 2026 MODE fixes (correct SBX and polynomial mutation,
non-dominated sorting, feasibility first; fast-cma-es #31, fcmaes-rust #1)
and the exact two-objective archives (`fcmaes.pareto`, `ParetoArchive2D`).
Until the next release, build from source for MODE work, for example
`python -m pip install "git+https://github.com/dietmarwo/fast-cma-es" --config-settings=cmake.define.FCMAES_FETCH_EIGEN=ON`.

### Rust crates

```toml
[dependencies]
fcmaes-core = "0.1"                                                    # crates.io
lp-ip-craft-native = { git = "https://github.com/dietmarwo/LP-IP-craft" }
sqp-craft-solver = { git = "https://github.com/dietmarwo/SQP-craft" }
```

LP-IP-craft and SQP-craft have release workflows for crates.io and PyPI. Until
their first release, use git dependencies, ideally with a pinned `rev`.

### Job workers, the runner and the MCP server

These need Linux, git and Rust 1.88 or newer. Each worker builds in its own
repository, together with `optimization-run` and `optimization-mcp`. Cargo
fetches this repository at the revision the worker pins (network access to
GitHub is needed; `cargo fetch --locked` prepares an offline build).

```sh
git clone https://github.com/dietmarwo/fcmaes-rust
(cd fcmaes-rust && cargo build --release --locked -p optimization-runner -p fcmaes-job-worker)
git clone https://github.com/dietmarwo/LP-IP-craft
(cd LP-IP-craft && cargo build --release --locked -p optimization-runner -p lp-ip-job-worker)
git clone https://github.com/dietmarwo/SQP-craft
(cd SQP-craft && cargo build --release --locked -p optimization-runner -p sqp-job-worker)
```

The runner and MCP server can also be built alone in this repository:
`cargo build --release --locked`, or
`cargo install --path crates/optimization-runner --locked` to put both on
`PATH`.

One node, with one absolute root and one CPU budget, serves all three
workers. Use one runner build for the node, and register the workers by
absolute path:

```sh
NODE="$HOME/.optimization-node"
RUN="$PWD/fcmaes-rust/target/release/optimization-run"
"$RUN" --root "$NODE" node init --capacity 8      # CPU slots jobs may reserve
"$RUN" --root "$NODE" workers add --id fcmaes --executable "$PWD/fcmaes-rust/target/release/fcmaes-job-worker"
"$RUN" --root "$NODE" workers add --id lp-ip  --executable "$PWD/LP-IP-craft/target/release/lp-ip-job-worker"
"$RUN" --root "$NODE" workers add --id sqp    --executable "$PWD/SQP-craft/target/release/sqp-job-worker"
"$RUN" --root "$NODE" workers list
```

Initializing the node and registering workers is the node owner's step; the
MCP server cannot do either. Executables are trusted local programs: this is
a single-user local runner, not a sandbox. After rebuilding a worker,
register it again (`worker_changed` otherwise).

## 5. The job API

A job is a JSON envelope. Its life runs like this:

1. The selected worker validates it and resolves its defaults.
2. The runner admits it against the node's CPU slots.
3. It runs as independent tasks, each committing a checked record to a
   journal.
4. It is sealed as a result manifest whose outcomes separate why a task
   stopped, what the worker claims and what was rechecked.
5. The job directory stays the durable record.

The guide [docs/job-api.md](docs/job-api.md) is the reference, and
[the JSON Schemas](docs/job-api/schemas/optimization.job-0.1.schema.json)
describe the job and the result.

### Envelope

The LP tutorial job: two tasks solve the model in `continuous-lp-model.json`,
which lies next to the job file.

```json
{
  "schema_version": "optimization.job/0.1",
  "request_key": "my-project.lp.v1",
  "worker": "lp-ip",
  "payload_schema": "lp-ip.solve/1",
  "resources": {"cpu_slots": 2, "outer_workers": 2, "inner_threads": 1},
  "limits": {"wall_time_seconds": 30.0, "grace_seconds": 1.0},
  "inputs": [{"name": "model", "file": "continuous-lp-model.json",
              "sha256": "5679c7093f7672b3e4f5185d0558d40c444bbd3e589e738150120f1a7dd2a5b5"}],
  "payload": {"model_input": "model", "starts": [null, null],
              "node_limit": 10000, "iteration_limit": 100000,
              "feasibility_tolerance": 1e-07, "integrality_tolerance": 1e-07,
              "presolve": true}
}
```

| Field | Rule |
| --- | --- |
| `request_key` | 1–200 bytes, chosen by the caller. The same key with the same content returns the existing job and never starts a second one. The same key with different content is `request_key_conflict`. Use a new key per experiment |
| `worker`, `payload_schema` | A registered worker ID and one of its profiles |
| `payload` | Strict and profile-specific: unknown fields are errors. Copy field names from `describe_worker` / `problems describe` and the tutorial jobs |
| `resources` | `outer_workers * inner_threads <= cpu_slots <= node capacity`. Outer workers run independent tasks; inner threads parallelize inside one task where the profile allows (`8/8/1` for eight runs, `8/1/8` for one large LP or SQP solve) |
| `limits` | Wall time starts after CPU admission. At the deadline the job ends `timed_out`, and its committed tasks stay in the result |
| `inputs` | Files relative to the job file, each with its SHA-256; at most 16 files of 64 MiB each. Never edit a file and keep its old hash |

The worker repositories' tutorials have complete jobs for every profile
([fcmaes](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/job-api),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/tree/main/tutorials/job-api),
[SQP](https://github.com/dietmarwo/SQP-craft/tree/main/tutorials/job-api)).
The LP model format (`lp-ip.model/1`: sparse CSR, `null` for infinite bounds)
is described in LP-IP-craft's
[ai-context](https://github.com/dietmarwo/LP-IP-craft/blob/main/ai-context.md#job-specification).

### From the shell

Every command prints JSON. A runner error exits with status 2 and prints one
line on stderr: `{"error":{"code":...,"message":...,"retryable":...}}`.

```sh
job() { "$RUN" --root "$NODE" "$@"; }    # RUN and NODE as above
job problems describe lp-ip              # profiles, models, options, claims, resource limits
job validate --spec job.json             # the resolved job with task_count; runs nothing
job run --spec job.json                  # blocks until the end, prints the final job
job jobs list                            # newest first, with id, state, directory, artifact_index
job jobs get JOB_ID                      # state and progress
job jobs wait JOB_ID --timeout 60        # returns at the end or after the timeout
job result JOB_DIRECTORY                 # the result manifest
job jobs artifact JOB_ID results --offset 0 --limit 100   # a page of checked records
job jobs cancel JOB_ID                   # graceful; add --now to stop at once
job jobs repair JOB_ID                   # finalize a job whose launcher was lost
```

To keep a long job from blocking, start `run` in a session of its own, as
the MCP server does, and follow it with `jobs get` or `jobs wait`:

```sh
setsid "$RUN" --root "$NODE" run --spec job.json > job.out 2>&1 &
```

Repeating `run` with the same key prints that job's current state and starts
nothing. `submit` instead launches a systemd user unit (`node doctor` tells
whether one is available). Lifecycle states:

- `submitted`, `starting`, `waiting` (for CPU slots), `running`;
- then `completed`, `cancelled`, `timed_out`, `failed` or `interrupted`.

`completed` means the tasks returned normally, not that the solution is
optimal; read the outcomes.

### Results, claims and evidence

Each task outcome in the manifest's `results` reports three things. Report
them to the user separately
([guide](docs/job-api.md#termination-claim-and-evidence)):

- **`termination`:** why the task stopped, such as `evaluation_limit`,
  `time_limit`, `optimizer_stop`, `cancelled`, or a solver status like
  `optimal` or `converged`. It is never a claim.
- **`claim`:** what the worker asserts: `none`, `feasible`, `best_found`,
  `numerical_optimum`, `first_order`, `non_dominated_set`, `elite_archive`,
  `infeasible`, `unbounded`, `infeasible_or_unbounded` or
  `locally_infeasible`. No current worker emits `certified_optimum`.
- **`evidence.level`:** either `claimed` (the solver's report only) or
  `rechecked` (recomputed outside the solver, with the checks listed in
  `evidence.checks`). `evidence.refuted` means an independent check rejected
  the solver's claim; `claim` then holds only what survived. Tell the user.

`objective_bounds` holds the primal objective and, where one exists, a dual
bound. `work` counts evaluations, nodes, iterations or callbacks per profile.
Never add work counters across profiles as if they measured the same thing.

Besides the `results` journal, a worker can declare artifacts such as an
evaluation log or a warm-start snapshot. They are listed in `artifact_index`
(`jobs get`, `jobs list`, the result) and can be read while the job runs.
`records` artifacts are read in pages; continue at `next_offset` while it is
below `available`. A later job takes an artifact as an input (its `file` and
the SHA-256 from `artifact_index`, with the earlier job's directory as input
directory). Jobs are never resumed in place.

## 6. The MCP server

`optimization-mcp` is an MCP server over stdio for one node. Each of its
tools drives the `optimization-run` command line, so validation,
idempotency, CPU admission and recovery are the runner's. Connect a client
with absolute paths, after the node owner has initialized the node and
registered the workers:

```sh
claude mcp add optimization-jobs -- /abs/target/release/optimization-mcp --root /abs/node
```

```json
{"mcpServers": {"optimization-jobs": {
  "command": "/abs/target/release/optimization-mcp",
  "args": ["--root", "/abs/node"]}}}
```

The server's options:

- `--runner`: the `optimization-run` executable; by default the one next to
  the server.
- `--launch process|systemd`: how `submit_job` starts jobs. `process` starts
  them in their own session, so they outlive the server but not a reboot.
- `--input-dir`: where relative input files of inline jobs are read from.

| Step | Tools |
| --- | --- |
| Discover | `describe_node` (capacity, workers, profiles), `describe_worker` (models, options with defaults, claims). If the needed worker is missing, tell the user instead of improvising with another profile |
| Prepare | `validate_job` until it returns the resolved job with its `task_count` |
| Run | `submit_job` returns the job's handle. With the MCP Tasks extension it returns a task that completes with the job's result |
| Follow | `wait_job` (at most 600 s per call), `get_job`, `list_jobs`, `get_events` |
| Read | `get_result` gives a summary by default; `tasks` returns the records and `full` the manifest. `get_artifact` reads whole artifacts or pages (`offset`, `limit`) |
| Stop and recover | `cancel_job` keeps completed tasks; `kill_job` stops at once; `repair_job` finalizes a job whose launcher was lost |

A job tool takes the envelope inline (`job`, with relative inputs read from
`input_dir`) or as `spec_path`, a job file with its inputs next to it.

The server's limits:

- An answer is at most 1 MiB: page large `records` artifacts, and read other
  large files in the job directory. `result_too_large` and
  `artifact_too_large` say when.
- A message is at most 64 MiB.
- At most 64 requests run at a time, of which at most 32 may wait.

Protocol: the server supports MCP 2026-07-28 statelessly (`server/discover`)
and 2025-11-25 back to 2024-11-05 after `initialize`. It offers tools only.

Trust: the server cannot register workers or change the node. Every connected
client acts for the node's owner, so connect only trusted clients.

The guide's [Agents and MCP](docs/job-api.md#agents-and-mcp) covers tasks,
durability and error codes.

## Pitfalls

- Do not promise options a worker did not list; profiles reject unknown
  payload fields instead of ignoring them.
- Do not present `best_found` as a global optimum, `first_order` as a global
  or second-order optimum, or `numerical_optimum` as an exact certificate.
- Python's `lp_ip_craft.solve` defaults to `backend="dummy"` and
  `sqp_craft.solve` to `method="dummy"`. Both only evaluate one point, so
  pass `backend="native"` and `method="sqp"`.
- A job that failed validation consumed nothing. A job that ran out of time
  can still carry useful completed tasks.
- Separate roots have separate CPU budgets. Use the same absolute root for
  every job that shares a machine.
- `interrupted` (a lost launcher or host) can be run again with a new
  request key. For a `failed` job, read `runner.journal_error`, the worker's
  `stderr.log` or the runner's message before retrying.

## Where to read next

| Topic | Document |
| --- | --- |
| Black-box algorithm choice, parameters, constraints, MODE, MAP-Elites in Python | fast-cma-es [ai-context.md](https://github.com/dietmarwo/fast-cma-es/blob/master/ai-context.md) |
| The same in Rust, the fcmaes job profiles, the surrogate chooser rule, application workers | fcmaes-rust [ai-context.md](https://github.com/dietmarwo/fcmaes-rust/blob/main/ai-context.md), [application models](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/job-api/models.md), [choosing an optimizer](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/choosing-an-optimizer.md) |
| LP/MIP modelling, options, statuses, bounds, `lp-ip.solve/1` | LP-IP-craft [ai-context.md](https://github.com/dietmarwo/LP-IP-craft/blob/main/ai-context.md) |
| Smooth NLP formulation, derivatives, KKT checks, `sqp.solve/1` | SQP-craft [ai-context.md](https://github.com/dietmarwo/SQP-craft/blob/main/ai-context.md) |
| Envelope, resources, lifecycle, errors, results, artifacts, MCP | [docs/job-api.md](docs/job-api.md) |
| JSON Schemas of the job and the result | [docs/job-api/schemas](docs/job-api/schemas/optimization.job-0.1.schema.json) |
| A worker of your own | [crates/optimization-job-api](crates/optimization-job-api) and the guide's [Extending and testing](docs/job-api.md#extending-and-testing) |
| Building, depending on these crates, tests | [README.md](README.md) |

When this file and the code disagree, the code, the discovery output and the
schemas win. Update this file with the change.
