# AI entry point: optimization with fcmaes, LP-IP-craft, SQP-craft and optimization-jobs

Last reviewed 2026-10-21 against `main` with the changes of an external
review of agent workflows: workers publish payload schemas and runnable
examples in `describe`, the MCP server has `get_guide` and `put_input`, and
`node doctor` reports the host's usable CPUs and memory. The crates are
`optimization-job-api` and `optimization-runner` 0.3.0, the envelope is
`optimization.job/0.1` and the result contract `optimization.result/0.2`.
In another checkout, check `Cargo.toml`, the `describe_node`/`describe_worker`
output and the linked guides before you rely on a command, option or claim.
Over MCP, `get_guide` returns this file.

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
| [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) | LP and MIP (linear objective, linear rows, continuous and integer variables) | `lp-ip-craft`, `lp-ip-craft-native` (Rust), `lp_ip_craft` (Python) | `lp-ip-job-worker`: `lp-ip.solve/1`, `lp-ip.evaluate/1` | crates.io `lp-ip-craft`, `lp-ip-craft-native`, PyPI `lp-ip-craft` (from 0.29.0) |
| [SQP-craft](https://github.com/dietmarwo/SQP-craft) | Smooth constrained NLP, at most 256 variables, analytic derivatives | `sqp-craft` (core), `sqp-craft-solver`, the backends `sqp-craft-clarabel` and `sqp-craft-activeset` (Rust), `sqp_craft` (Python) | `sqp-job-worker`: `sqp.solve/1`, `sqp.evaluate/1` | crates.io `sqp-craft` and its solver and backend crates, PyPI `sqp-craft` (from 0.17.0) |
| optimization-jobs (this one) | No solver of its own: the job envelope, result contract, worker SDK, runner and MCP server | `optimization-job-api` (worker SDK) | runner `optimization-run`, MCP server `optimization-mcp` | crates.io `optimization-job-api`, `optimization-runner` (from 0.3.0) |

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

Decide in this order, so that structure never overrides the requested output:

1. **What the user needs**: one solution, a Pareto front, or many diverse
   solutions; and which guarantee (a good point, a local optimum with KKT
   evidence, an LP/MIP bound and gap). Keep both through the next steps.
2. **Structure the model has**: linear, smooth with derivatives, or a black
   box; its size, integer variables and evaluation cost.
3. **A method that keeps both**, from the tables below.
4. **An interface that has it** ([step 3](#3-choose-the-interface-library-or-job)):
   check that the model, profile and options exist where you will run it.

### One objective

| Structure | Solver | Limits to check |
| --- | --- | --- |
| Linear objective and constraints, continuous and/or integer variables | LP-IP-craft | A MIP needs finite bounds on every variable (or bounds presolve can infer); no QP/MIQP; no relative-gap stop; numerical statuses, no exact certificates. When peak speed decides, or for a large, hard industrial MIP, compare with a mature solver such as HiGHS under the same independent check |
| Smooth nonlinear objective and constraints, continuous variables, at most 256, gradient and Jacobian available; a local optimum suffices or good starts exist | SQP-craft | Local method with dense BFGS; use multistart for multimodal models. More than 256 variables or exact Hessians: an IPOPT-family solver fits better |
| Expensive deterministic simulation (seconds to a minute per call), continuous box, 1–32 variables, at most 256 calls, few evaluations at a time | `fcmaes.surrogate/1` (fcmaes-rust job worker, experimental), compared with BiteOpt | Job-only: the simulation must be a Rust model in an fcmaes application worker; there is no Python surrogate. No constraints, noise or mixed variables. Prefer retry (BiteOpt first) for separable or many-modal problems with ten or more variables, and when many cores can evaluate in parallel. In Python, use fcmaes with a parallel population (fast-cma-es "Expensive objective") |
| Black box: nonsmooth, noisy or multimodal, box bounds; integers or categories decoded from continuous variables | fcmaes retry: BiteOpt first; DE for robust exploration and integer decoding; CMA-ES with a good start (`guess` in `fcmaes.retry/1`); CR-FM-NES for higher dimensions; PGPE for noise and very high dimensions | Benchmark at least two choices on equal budgets and seeds. Constraints become penalties or repairs: check the raw constraints separately ([Results](#results-claims-and-evidence)) |

### Several objectives (a Pareto front)

| Structure | Method | Notes |
| --- | --- | --- |
| Linear | A series of LPs/MIPs in LP-IP-craft: weighted sums with strictly positive weights, or ε-constraints (minimize one objective, bound the others as extra rows), one model per candidate point | Candidates, not certified Pareto points (below). Weighted sums reach only supported points: for an LP the front is convex and every efficient point is supported, but a MIP's front can have unsupported points that no weights reach. MODE would discard the structure |
| Smooth, at most 256 variables | ε-constraint or weighted-sum SQP solves with multistart (one model per bound or weight, or both as model parameters), or fcmaes MODE | A converged solve is a first-order point of the scalarized problem, not proof of local Pareto optimality. MODE needs no derivatives but more evaluations |
| Black box | fcmaes MODE (or weighted `moretry` in the libraries); with exactly two objectives keep every evaluation in the exact archive (`fcmaes.pareto`, `ParetoArchive2D`) | Constraints come after the objectives and are feasible at `g(x) <= 0`; MODE's final population is not the front of everything it evaluated |

Scalarization gives candidate points; check them before calling them a
front:

- **Ties.** An ε-constraint optimum can be dominated when the bound is not
  tight or the optimum is not unique. Minimizing `f1 = x` subject to
  `f2 = -y <= 0` on `[0,1]^2` may return `(0,0)` with objectives `(0,0)`,
  which `(0,1)` with `(0,-1)` dominates; the solver is right, the label would
  be wrong. Resolve ties with a second stage (fix the first objective at its
  optimum and minimize the others) or a small augmentation term, as in
  AUGMECON.
- **Unsupported points.** A weighted sum with a degenerate direction has a
  whole optimal face, and the solver returns one point of it. Of the
  efficient points `(0,3)`, `(2,2)` and `(3,0)` of a discrete problem, no
  positive weights make `(2,2)` optimal.
- **Filtering.** Evaluate every candidate's original objectives and
  constraints independently, and keep the non-dominated ones.
- **Reporting.** Report each point's own scalar evidence (termination, gap,
  KKT residuals), and call the result a set of non-dominated candidates, not
  a certified Pareto front.

### Many diverse solutions

fcmaes MAP-Elites (grid or CVT archives, CMA-ME/CMA-MAE emitters in the job
worker; Diversifier in the libraries). The behavior descriptors must express
the diversity the user wants; occupancy alone is not usefulness.

### Requests outside the toolbox

Say so, and name what would fit, instead of forcing the problem into one of the
solvers:

| Request | What to do |
| --- | --- |
| QP or MIQP, conic (SOCP, SDP) | No dedicated solver here. A small, smooth, continuous QP can be an SQP model; otherwise a QP/conic solver (OSQP, Clarabel directly, a MIQP-capable MIP solver) |
| Large sparse NLP (more than 256 variables), exact Hessians | IPOPT-family solvers; SQP-craft is dense and limited to 256 variables |
| MINLP with a proof of optimality, any global-optimality certificate | Outside the guarantees: fcmaes on a decoded model is a heuristic, LP-IP-craft's statuses are numerical. Use a global MINLP solver (SCIP, BARON, Couenne) |
| Scheduling, routing, graphs and other combinatorial structure | Prefer an exact formulation (a MIP in LP-IP-craft, or a dedicated CP/routing solver) when the structure allows; decode-and-repair with fcmaes when it does not. Do not drop exploitable structure just because a black-box encoding is possible |
| Remote, asynchronous or human-in-the-loop evaluation | The library ask/tell interfaces (fast-cma-es, `fcmaes-core`); the job protocol has no ask/tell session |
| Stochastic simulation | Fixed seed sets for training and disjoint seeds for validation (see the fcmaes `ai-context.md` files); the job profiles recheck deterministic values only |
| Several machines, pause and resume of an optimizer's state | Not provided: one node per runner; a surrogate warm start from a snapshot is a new job, not a resumed one |

### Rules across the tables

- Do not pick a gradient-free optimizer just because the model is a
  simulation. If the whole map from decisions to objective is differentiable
  and the gradients are reliable, a gradient method uses far fewer
  evaluations.
- Global then local: points from an fcmaes run can be the starts of an SQP
  solve. In process this is ordinary code. As jobs, the agent passes the
  points between two jobs. Before using them, check that both sides have the
  same model ID and version, the same variable order, units and bounds, and
  the same data (SHA-256); recheck the points with the target worker's
  `evaluate` profile.
- No solver here certifies a global optimum, proves MINLP optimality or emits
  exact certificates. fcmaes on a decoded integer model is a heuristic.
- Recheck any point, including another tool's, independently. The
  `evaluate` profiles recompute objective and feasibility (`sqp.evaluate/1`
  only function values). The libraries also check optimality conditions:
  `lp_ip_craft.lp_residuals` and `safe_dual_bound` for LPs,
  `sqp_craft.kkt_residuals` for KKT points.

## 3. Choose the interface: library or job

| Situation | Use |
| --- | --- |
| The objective is a Python function | A library in process: `fcmaes` (black box, MODE, MAP-Elites), `sqp_craft.solve(spec, model, x0, method="sqp")`, `lp_ip_craft.solve(model, backend="native")`, or `fcmaes_rust` for the Rust implementations |
| The objective is Rust code | The crates ([below](#rust-crates)), or a model registered in a job worker |
| An LP or MIP given as data | A job with an `lp-ip.model/1` artifact (no code needed), or `lp_ip_craft` in Python |
| Durable, CPU-budgeted, cancellable runs with independently checked results; several solvers on one CPU budget; an agent that must not block on a long run | The job API, through the shell or MCP |

A job names a model that its worker has registered. It can carry hashed data
files, but never Python callables, source code, executable paths or shell
commands. Without writing Rust, a job can run:

- any LP or MIP, as a hashed JSON model artifact (`lp-ip.solve/1`). Its
  schema is in the LP worker's `describe`; LP-IP-craft's
  `scripts/mps_to_model.py` converts an MPS file. Over MCP, store the model
  with `put_input`;
- the registered benchmark models of the fcmaes and SQP workers, which are
  useful for testing a node but are not user problems;
- checks of given points with the `evaluate` profiles.

A user's own nonlinear model becomes a job model as Rust code in a worker:

- **fcmaes:** an application worker, i.e. a closure with parameters and
  SHA-256-checked data inputs (see fcmaes-rust's
  [application models](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/job-api/models.md)).
  `Scalar::simulation` models are fallible, cancellable simulations;
  `fcmaes.surrogate/1`, `fcmaes.retry/1` and `fcmaes.evaluate/1` accept
  them, so one model can be compared under the surrogate and BiteOpt. In a
  retry a failed evaluation counts as `+inf` and is counted in
  `failed_evaluations`.
- **SQP:** a model in SQP-craft's public `Registry`, with a `config`
  schema, SHA-256-checked data inputs and a derivative check, built as an
  application worker (see SQP-craft's
  [application models](https://github.com/dietmarwo/SQP-craft/blob/main/docs/job-api/models.md)
  and its `examples/custom_worker.rs`).

Otherwise use the library.

With the Python libraries, a cheap Python objective called from native
threads still needs the GIL, so it rarely scales across threads. Instead:

- fast-cma-es's `retry`, `advretry` and `moretry` evaluate in processes;
- vectorized or ask/tell evaluation suits evaluators the user owns;
- a Rust objective avoids the boundary altogether.

## 4. Install

The packages on PyPI and crates.io install with the usual commands; the rest
build from source. Each README describes installation from source, with the
requirements and, where there are any, our own dependencies.

### Python

```sh
python -m pip install fcmaes        # fast-cma-es; CPython 3.10+
python -m pip install fcmaes-rust   # import fcmaes_rust; CPython 3.11-3.13
python -m pip install lp-ip-craft   # import lp_ip_craft; CPython 3.10+
python -m pip install sqp-craft     # import sqp_craft; CPython 3.10+
```

The two craft packages have abi3 wheels for Linux x86_64, Windows x64 and
macOS x86_64/arm64; elsewhere pip builds them from the sdist with Rust 1.85
or newer.

fcmaes has wheels for CPython 3.10–3.13 on x86-64 Linux and Windows and on
macOS (Intel and Apple Silicon). Elsewhere, for example Python 3.14 or Linux
aarch64, pip builds the sdist. That build needs a C++17 compiler and either
a system Eigen 3.4 or
`--config-settings=cmake.define.FCMAES_FETCH_EIGEN=ON`.

From source, each in its own checkout. The Rust toolchain comes from
https://rustup.rs, and pip fetches the build backends itself.

```sh
# fast-cma-es: C++17 compiler; Eigen 3.4 from the system or fetched as here
git clone https://github.com/dietmarwo/fast-cma-es
(cd fast-cma-es && python -m pip install . --config-settings=cmake.define.FCMAES_FETCH_EIGEN=ON)
# CPython 3.10+; LP-IP-craft (Rust 1.85+), SQP-craft (Rust 1.85+ and a C linker),
# fcmaes-rust (Rust 1.88+, CPython 3.11-3.13)
git clone https://github.com/dietmarwo/LP-IP-craft
(cd LP-IP-craft && python -m pip install .)
git clone https://github.com/dietmarwo/SQP-craft
(cd SQP-craft && python -m pip install .)
git clone https://github.com/dietmarwo/fcmaes-rust
(cd fcmaes-rust && python -m pip install .)
```

None of these Python packages depends on another repository of ours.

For MODE work use fcmaes 2.1.0 or later and fcmaes-rust/`fcmaes-core` 0.2.0
or later (`pip install "fcmaes>=2.1"`, `"fcmaes-rust>=0.2"`). Earlier
releases (fcmaes 2.0.3, fcmaes-rust and `fcmaes-core` 0.1.5) predate the
October 2026 MODE fixes (correct SBX and polynomial mutation, non-dominated
sorting, feasibility first; fast-cma-es #31, fcmaes-rust #1) and the exact
two-objective archives (`fcmaes.pareto`, `ParetoArchive2D`). Check the
registry for the installed version; for changes after the latest release,
build from source, for example
`python -m pip install "git+https://github.com/dietmarwo/fast-cma-es" --config-settings=cmake.define.FCMAES_FETCH_EIGEN=ON`,
and in Rust use git dependencies ([below](#rust-crates)).

### Rust crates

```toml
[dependencies]
fcmaes-core = "0.2"          # 0.2.0 or later has the MODE fixes and ParetoArchive2D
# LP/MIP: the model, options and checks, and the solver
lp-ip-craft = "0.29"
lp-ip-craft-native = "0.29"
# Smooth NLP: the core (ProblemSpec, NlpProblem), the solver and a QP backend
sqp-craft = "0.17"
sqp-craft-solver = "0.17"
sqp-craft-clarabel = "0.17"  # or sqp-craft-activeset
```

These are the first crates.io releases of LP-IP-craft and SQP-craft (October
2026). If a version is not on crates.io yet, or for changes after the latest
release, use git dependencies, ideally with a pinned `rev`, for example
`lp-ip-craft = { git = "https://github.com/dietmarwo/LP-IP-craft", rev = "..." }`.

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

The runner and MCP server can also be installed alone:
`cargo install optimization-runner --locked` (crates.io, from 0.3.0) puts
both on `PATH`; in a checkout of this repository, `cargo build --release
--locked` or `cargo install --path crates/optimization-runner --locked`. A
runner from any of these sources accepts the three workers (worker protocol
`optimization.worker/0.2`).

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

The guide [docs/job-api.md](docs/job-api.md) is the reference, and the JSON
Schemas describe
[the job](docs/job-api/schemas/optimization.job-0.1.schema.json) and
[the result](docs/job-api/schemas/optimization.result-0.2.schema.json).

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
| `request_key` | 1–200 bytes, chosen by the caller. The same key with the same content and the same worker binary returns the existing job and never starts a second one. A different content, or a rebuilt and re-registered worker, gives `request_key_conflict`. Use a new key per experiment |
| `worker`, `payload_schema` | A registered worker ID and one of its profiles |
| `payload` | Strict and profile-specific: unknown fields are errors. Copy field names from `describe_worker` / `problems describe` and the tutorial jobs |
| `resources` | `outer_workers * inner_threads <= cpu_slots <= node capacity`. Outer workers run independent tasks; inner threads parallelize inside one task where the profile allows (`8/8/1` for eight runs, `8/1/8` for one large LP or SQP solve) |
| `limits` | Wall time starts after CPU admission. At the deadline the job ends `timed_out`, and its committed tasks stay in the result |
| `inputs` | Files relative to the job file, each with its SHA-256; at most 16 files of 64 MiB each. Never edit a file and keep its old hash |

The worker repositories' tutorials have complete jobs for every profile
([fcmaes](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/job-api),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/tree/main/tutorials/job-api),
[SQP](https://github.com/dietmarwo/SQP-craft/tree/main/tutorials/job-api);
the surrogate jobs are in fcmaes-rust's
[tutorials/surrogate](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/surrogate)).
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
job jobs execution JOB_ID                # how the worker process ended (after 0.3.0)
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

A runner built from `main` after 0.3.0 also keeps an execution record of
each finished job (`jobs execution JOB_ID`, `execution.record/0.1`): the
worker's exit code or signal, the stop reason, whether its process group is
verifiably stopped, and the size and SHA-256 of `run.json`. It holds no
claim, objective or work; report those from the result manifest. A job that
has not finished returns `attempt_active` (wait, then ask again); one finished
by an older runner returns `execution_unavailable`.
`node capabilities` (and `capabilities` in `node doctor` and MCP
`describe_node`) returns `execution.capabilities/0.3`: optimization jobs and
opt-in trusted local commands, enabled kinds, binary file transfer limits and
CLI-only command/file interfaces. Commands use `execution.command/0.1` with
literal argv, explicit environment, hashed inputs, declared bounded outputs and
no automatic replay; enable with `node commands --enable`. Use `files put/get`
and `jobs collect` for binary transfer. Their separate `command-result.json`
records process/output facts, never mathematical claims. MCP submission and
result summaries remain optimization-only. Commands share admission/cancellation
but are not a sandbox or kernel resource limits. Explicit `fleet submit --node NAME --spec FILE` and `fleet reconcile/collect`
use a fixed SSH helper and persistent node/dispatch identities. Registration pins
the SSH endpoint and node ID; remote launch requires a systemd user manager and
lingering. Staging can resume, but uncertain starts never move or automatically
relaunch. Binary collection is independent. Automatic placement remains future
work; actual host service/logout/reboot behaviour must be commissioned
([guide](docs/job-api.md#execution-discovery-and-terminal-observations)).

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

`feasible` means feasible for the constraints the model declares. A scalar
fcmaes model declares only its bounds, so constraints written as penalties
inside its objective are not checked: a low-penalty point can be reported
`feasible` and still violate them. Keep the raw constraint values, and check
them yourself, or evaluate the point with a model that declares them (a
multi-objective fcmaes model with constraints, an LP, an SQP model).

`objective_bounds` holds the primal objective and, where one exists, a dual
bound. `work` counts evaluations, nodes, iterations or callbacks per profile.
Never add work counters across profiles as if they measured the same thing.

Besides the `results` journal, a worker can declare artifacts such as an
evaluation log or a warm-start snapshot. They are listed in `artifact_index`
(`jobs get`, `jobs list`, the result) and can be read while the job runs.
`records` artifacts are read in pages; continue at `next_offset` while it is
below `available`. A later job takes an artifact as an input: its `file`,
with the SHA-256 from `runner.artifact_index` of the sealed result (`jobs
get` lists no hashes). Over MCP, pass the earlier job's `directory` as
`input_dir`; with the CLI, copy the file next to the new job file. Jobs are
never resumed in place.

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
| Orient | `get_guide`: this file, whole or one section (`section`, matched against the headings) |
| Discover | `describe_node`: capacity, the host's usable CPUs and memory, the workers and their profiles. `describe_worker`: models, options with defaults, claims, and the discovery keys below |
| Prepare | `put_input` stores an input file (text, base64, or an earlier job's artifact) and returns `file`, `sha256` and `input_dir`; `validate_job` with that `input_dir` until it returns the resolved job with its `task_count` |
| Run | `submit_job` returns the job's handle. With the MCP Tasks extension it returns a task that completes with the job's result |
| Follow | `wait_job` (at most 600 s per call), `get_job`, `list_jobs`, `get_events` |
| Read | `get_result` gives a summary by default; `tasks` returns the records and `full` the manifest. `get_artifact` reads whole artifacts or pages (`offset`, `limit`) |
| Stop and recover | `cancel_job` keeps completed tasks; `kill_job` stops at once; `repair_job` finalizes a job whose launcher was lost |

A job tool takes the envelope inline (`job`, with relative inputs read from
`input_dir`) or as `spec_path`, a job file with its inputs next to it.

`describe_worker` is enough to build a first job without a checkout. Each
worker lists:

- `payload_schemas`: a strict JSON Schema per profile;
- `input_schemas`: the schemas of fixed input formats, such as `lp-ip.model/1`;
- `examples`: runnable jobs per profile, with their input files as `content`
  (JSON) or `content_text`.

An MCP-only client turns an example into a job like this:

1. Store each input with `put_input`.
2. Write the envelope: `schema_version` `optimization.job/0.1`, a new
   `request_key`, the worker ID, `payload_schema` (the example's `profile`),
   its `resources`, `limits` and `payload`, and `inputs` with the returned
   `file` and `sha256`.
3. Call `validate_job` with the returned `input_dir`.
4. Change the payload toward the user's problem, keeping it valid against
   `payload_schemas`.

When no registered worker or model fits:

- **MCP only:** tell the user what is missing: the worker, the model or the
  option. The server cannot install code or register workers.
- **With a shell:** use the library route instead, or build an application
  worker. fcmaes-rust's
  [application models](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/job-api/models.md)
  and SQP-craft's model registry turn Rust models into job models. The node
  owner then registers the worker with `workers add`.

The server's limits:

- `get_result` with `full` and a whole `get_artifact` read return at most
  1 MiB (`result_too_large`, `artifact_too_large`). For more, use
  `get_result` with `tasks`, page `records` artifacts, or read the files in
  the job directory. A page holds at most 1 MiB of records.
- A message is at most 64 MiB.
- At most 64 requests run at a time, of which at most 32 may wait.

Protocol: the server supports MCP 2026-07-28 statelessly (`server/discover`)
and 2025-11-25 back to 2024-11-05 after `initialize`. It offers tools only.

Trust: the server cannot register workers, change the node or run code.
`put_input` stores data, never code. Every connected client acts for the
node's owner, so connect only trusted clients.

The guide's [Agents and MCP](docs/job-api.md#agents-and-mcp) covers tasks,
durability and error codes.

## 7. Resources on a large machine

CPU slots are accounting, not a speedup promise and not enforcement: the
runner admits jobs while `outer_workers * inner_threads <= cpu_slots <=
capacity`, but it does not pin threads, enforce a quota or reserve memory.
Plan the layout yourself:

1. **Measure the host.** `node doctor` (MCP `describe_node`) reports `host`:
   `usable_cpus` (affinity mask and cgroup quota), `physical_cores`,
   `numa_nodes`, `usable_memory_bytes`, and a warning when the node's
   capacity exceeds the usable CPUs. Size the capacity from `usable_cpus`, not
   from the machine's CPU count.
2. **Estimate memory per task.** Model data, the population or archive, and a
   simulator's working set, times the outer workers of all concurrent jobs
   (and of any direct library callers on the same host). Lower the outer
   width until it fits `usable_memory_bytes` with headroom. The runner has no
   memory admission.
3. **Give each level of parallelism one owner.** Outer tasks, inner threads,
   and pools inside the model (BLAS/OpenMP, Rayon, a simulator's threads,
   Python processes) multiply. Set the model's own pools (for example
   `OMP_NUM_THREADS=1`) when the job's threads already use the slots.
4. **Create useful parallel work, not duplicates.** Identical tasks (LP null
   starts, one SQP start repeated) repeat the same deterministic solve.

What each surface can use:

| Surface | Width | Consequence |
| --- | --- | --- |
| Common job envelope | `outer_workers * inner_threads <= cpu_slots <= 1024` | The node can hold many jobs; a job's outer workers help only when it has that many tasks |
| LP job (`lp-ip.solve/1`) | One model per job; `inner_threads` 1–8 (numerical kernels); component, packing and tree workers forced to 1 | Many models: many jobs (for example 64 one-slot jobs or 8 eight-slot jobs). One LP is not a 64-thread solve |
| LP library | `solve_batch` with 1–16 workers; `component_threads` defaults to 16 when `threads=1` | Set `component_threads=1` when the caller owns concurrency |
| SQP job (`sqp.solve/1`) | One task per start; `inner_threads` 1–8 | Many distinct starts with `inner_threads=1` is the first many-core layout; Clarabel is serial, active-set kernels parallelize only above size thresholds |
| SQP library | `batch::solve_many`: outer × inner at most 8 | Beyond 8, use jobs or separate processes |
| fcmaes population profiles | `inner_threads` parallelize the population (results do not depend on the width) | Useful when the objective is expensive and the population large enough |
| fcmaes serial BiteOpt/DE | `inner_threads=1` unless `batch` is set | Use outer retries; `batch` changes the feedback timing |
| `fcmaes.surrogate/1` | `concurrent * evaluation_threads <= inner_threads <= 8` per run | More slots mean more independent runs, not one larger surrogate |
| fast-cma-es | Retry processes, population evaluators, the simulator's pools | Count usable CPUs (`usable_cpus()` in its `examples/external_simulator.py`) and choose one owner |

Candidate layouts for 64 usable slots, to compare, not benchmarked
recommendations:

| Workload | Layout |
| --- | --- |
| Many independent scalar searches on a registered model | One job, `cpu_slots=64, outer_workers=64, inner_threads=1`, at least 64 retries |
| Expensive population objective | One run with `inner_threads=64`, or eight runs with eight each |
| Many LP/MIP models | 64 one-slot jobs, or eight eight-slot jobs |
| One NLP, many starts | One job with 64 distinct starts, `outer_workers=64, inner_threads=1` |
| Expensive surrogate searches | Eight runs × eight inner threads, each with its own history and budget |

For a performance comparison, fix the model, data, budgets, seeds and
acceptance rule. Report wall time, completed work, solution quality, peak
memory and how many tasks completed. CPU utilization alone is no result.

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
