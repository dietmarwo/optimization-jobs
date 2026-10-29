# Optimization systems for AI agents: how fcmaes & craft compares

Research date 21 October 2026; updated 23 October 2026 for the October registry
releases, 25 October 2026 for explicit SSH placement and experiment-craft, and
26 October 2026 for experiment-craft's comparisons, operations and dashboard.

> **Who wrote this.** This comparison was prepared with AI-assisted research for
> the maintainer of the six repositories, and the maintainer publishes it. It
> is therefore **not an independent evaluation**. Alternatives are described
> from their public documentation and, for ten smaller projects, from their
> source at the revisions in [Section 8](#8-sources-revisions-and-scope). No
> system, ours included, was benchmarked for it. "Supports parallel execution"
> describes an interface or implementation; it is not a measured speedup.
> Corrections are welcome through the
> [evaluation issue form](https://github.com/dietmarwo/optimization-jobs/issues/new?template=independent-evaluation.yml).

**fcmaes & craft** is the name for six MIT-licensed repositories used as one
toolbox:

- [optimization-jobs](https://github.com/dietmarwo/optimization-jobs): the shared shell/MCP job layer.
- [fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust): native global, multiobjective and quality-diversity search in Rust.
- [fast-cma-es](https://github.com/dietmarwo/fast-cma-es): the Python `fcmaes` package.
- [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft): LP and MILP in Rust.
- [SQP-craft](https://github.com/dietmarwo/SQP-craft): smooth constrained NLP in Rust.
- [experiment-craft](https://github.com/dietmarwo/experiment-craft): reproducible campaigns over the job layer (parameter sweeps, dependent steps, budgets, reports), predeclared solver comparisons, pause/backup/restore and a local dashboard; in early development.

It is compared here with the open-source systems an AI agent could use instead.

## Contents

1. [Summary](#1-summary)
2. [The comparison at a glance](#2-the-comparison-at-a-glance)
3. [The alternatives, compared with fcmaes & craft](#3-the-alternatives-compared-with-fcmaes--craft)
4. [fcmaes & craft in detail](#4-fcmaes--craft-in-detail)
5. [Choosing tools for SpOC4 Challenge 2](#5-choosing-tools-for-spoc4-challenge-2)
6. [Application areas where fcmaes & craft ranks high](#6-application-areas-where-fcmaes--craft-ranks-high)
7. [How to establish measured rankings](#7-how-to-establish-measured-rankings)
8. [Sources, revisions and scope](#8-sources-revisions-and-scope)

## 1. Summary

**No other system in this survey combines what fcmaes & craft combines.** The
toolbox offers:

- LP/MILP, smooth constrained NLP, black-box global search, constrained
  multiobjective search, quality diversity and a small surrogate optimizer;
- an agent-facing job service with durable records, a CPU budget shared by
  concurrent jobs, and results that separate the solver's claim from its
  verification;
- one MIT-licensed, locally run stack: the Rust solvers (fcmaes-core,
  LP-IP-craft, SQP-craft) are pure Rust, the libraries install from PyPI or
  crates.io, and the job workers and the surrogate crate are built from
  source.

That is a bounded finding of this research, not proof of uniqueness.
The closest systems match parts of it:

- **GEMSEO** has comparable mathematical breadth, but no first-party agent job
  service.
- **Optees** has the most similar agent contract (schemas, validation,
  structured results), but one dispatch worker and in-memory job records.
- **Optuna with optuna-mcp** offers an established black-box ecosystem and
  **BO-MCP** persistent Bayesian campaigns; both evaluate objectives outside
  their MCP interface and have no LP or NLP solvers.
- **libEnsemble**, **Dakota** and **Ray Tune** schedule work across nodes;
  fcmaes & craft places a job only on a node named explicitly over SSH.

These strengths are established from source and documentation:

- **Fit for agents.** One routing guide chooses the solver by mathematical
  structure. The MCP server's 15 tools serve that guide, JSON Schemas and
  runnable examples, check a job before it runs, and turn a submitted job into
  an MCP task. Objectives run inside native workers, so no agent or Python
  round trip happens per evaluation.
- **Results an agent can trust or question.** The worker's `claim` is reported
  apart from how much of it was rechecked (`evidence`). An independent check
  that fails produces a recorded refutation instead of a silent pass. LP-IP-craft
  adds an outward-rounded safe dual bound; SQP-craft adds KKT and derivative
  checks.
- **One machine, used deliberately.** CPU-slot admission applies
  `outer_workers * inner_threads <= cpu_slots` across all jobs on a node, and
  each optimizer declares whether its evaluation limit is hard or soft.
- **Low installation friction.** Wheels for Linux x86_64, Windows x64 and
  macOS need no compiler. The Rust solver crates link no C/C++ solver library
  and forbid `unsafe` code. `cargo install optimization-runner --locked`
  installs the CLI and the MCP server.
- **Campaigns and comparisons that keep their evidence (early).**
  experiment-craft compiles a JSON campaign (parameter sweeps, dependent
  steps, budgets and deadlines) into ordinary jobs. It records each decision
  in SQLite before acting on it, observes uncertain work instead of
  resubmitting it, and reports every step, failed and blocked ones included,
  with the job's native claim and evidence. A solver comparison is sealed
  before the first job runs and reported descriptively over every planned
  run. Campaigns can be paused, backed up, restored and watched in a local
  browser dashboard. It runs locally and sequentially and is not on PyPI.
- **Track record of the black-box methods.** The fast-cma-es Python package,
  whose algorithms fcmaes-rust reimplements in Rust, has been on PyPI as
  `fcmaes` since February 2020 (133 releases). An independently authored
  OptunaHub sampler wraps its CMA-ES. fcmaes-rust has 22 application
  tutorials and fast-cma-es 44 tutorials, which show the methods on concrete
  problems.

The alternatives are stronger in several places:

- multi-node and GPU execution (libEnsemble, Ray, Dakota, Optuna, cuOpt);
- large sparse NLP and multidisciplinary models (GEMSEO, OpenMDAO with Ipopt);
- hard industrial MIP (HiGHS, cuOpt);
- Bayesian optimization beyond small deterministic boxes (BO-MCP/BoTorch,
  Vizier, Optuna);
- symbolic and constraint programming (MCP Solver);
- community size and track record (Optuna, Dakota).

Five of the six fcmaes & craft repositories were created between July and
October 2026, and one maintainer develops all six.

No speed claim is made in either direction. The recommended next step is a
measured comparison on fixed workloads ([Section 7](#7-how-to-establish-measured-rankings)).

## 2. The comparison at a glance

### 2.1 Systems

| System | Agent access | Mathematical scope | Execution and persistence | Compared with fcmaes & craft |
|---|---|---|---|---|
| **fcmaes & craft** | MCP server (15 tools, MCP Tasks), CLI, Python and Rust libraries, one routing guide | LP/MILP; smooth constrained NLP up to 256 variables; black-box global; constrained multiobjective; quality diversity; exact-GP surrogate (1-32 variables) | Local Linux node; CPU slots shared by concurrent jobs; hashed inputs, journals and records that outlive the MCP server; repair of interrupted records; explicit placement on registered SSH nodes; campaigns over these jobs (experiment-craft, early) | — |
| [GEMSEO](https://gemseo.org/) | Python through a shell; no first-party MCP route found | Broad: LP/MILP (HiGHS, SciPy), SLSQP/NLopt, Ipopt plugin, pymoo, surrogates | Parallel multistart and configurable parallel workflows | Broader engineering modeling and solver plugins; no agent job service, no QD |
| [libEnsemble](https://github.com/Libensemble/libensemble) + [Ensemble Agent](https://github.com/Libensemble/ensemble_agent) | Agent application with an MCP script-generation server; Python | Generators and simulations the user connects | CPU/GPU/node assignment across nodes, monitoring, cancellation | Much stronger distributed execution; fewer built-in solvers, less packaged agent layer |
| [Optees](https://github.com/Pablo-gitub/optees) | CLI, REST, MCP, desktop UI | LP/MILP, convex QP, robust linear, packing, knapsack, restricted nonlinear expressions | Asynchronous queue, one dispatch worker, in-memory job records | Closest contract design and adds QP; no shared CPU budget, records do not survive the process |
| [Optuna + optuna-mcp](https://github.com/optuna/optuna-mcp) | MCP ask/tell, study management, visualization | Black-box, multiobjective, HPO samplers | Persistent studies with storage; multiprocess/multinode in Optuna core | More mature, larger community; objectives evaluated outside MCP; no LP/NLP |
| [BO-MCP](https://github.com/AccelerationConsortium/bo-mcp) | MCP, REST, Python | Bayesian optimization (BoTorch/BayBE), batches with pending experiments | SQLite/PostgreSQL campaigns, provenance | Richer BO for external experiments; no simulation-worker scheduler |
| [NVIDIA cuOpt MCP](https://github.com/NVIDIA/cuopt/tree/main/python/cuopt_mcp) | MCP over a gRPC backend | LP/MILP (as exposed by the MCP interface) | GPU workers, job status, cancellation | GPU-scale LP/MILP; needs a GPU backend; no black-box/NLP tools in the MCP interface |
| [Frontier](https://github.com/cafzal/frontier) | MCP with stage-specific guidance | Selection/allocation with multiple objectives (pymoo; HiGHS/cuOpt for supported shapes) | Four background threads; persisted problems and results; active jobs in memory | Better decision guidance for its domain; narrower scope, process-local job registry |
| [Dakota](https://dakota.sandia.gov/) | Input files and shell | Gradient and nongradient optimization, surrogates, UQ, calibration | Multilevel parallelism with MPI; evaluation restart files | Broader UQ and HPC scale; no agent service, more integration work |

### 2.2 Capabilities

● built in and documented · ◐ partial, limited or through an add-on (see the
notes) · – not found in the sources reviewed · ? not checked

| Capability | fcmaes & craft | GEMSEO | libEnsemble | Optees | Optuna | BO-MCP | cuOpt MCP | Frontier | Dakota |
|---|---|---|---|---|---|---|---|---|---|
| LP / MILP | ● | ● | – | ● | – | – | ● | ◐ ⁷ | ? |
| Smooth constrained NLP | ◐ ¹ | ● | ◐ ² | ◐ ³ | – | – | – | – | ● |
| Black-box global search | ● | ● | ◐ ² | ? | ● | ◐ ⁴ | – | ◐ ⁸ | ● |
| Multiobjective | ● | ● | ◐ ² | ? | ● | ? | – | ● | ● |
| Quality diversity | ● | – | ◐ ² | – | – | – | – | – | – |
| Surrogate / Bayesian | ◐ ⁵ | ● | ◐ ² | – | ● | ● | – | – | ● |
| First-party MCP server | ● | – | ◐ ⁶ | ● | ● | ● | ● | ● | – |
| Job records survive a restart | ● | ? | ? | – | ◐ ⁹ | ● | ? | ◐ ¹⁰ | ◐ ¹¹ |
| Resource management for parallel work | ● ¹² | ◐ ¹³ | ● | – | ◐ ¹⁴ | – | ◐ ¹⁵ | ◐ ¹⁶ | ● |
| Claim separated from verification | ● | ? | ? | ● | ? | ? | ? | ◐ ¹⁷ | ? |
| Multi-node execution | ◐ ¹⁸ | ? | ● | – | ● | ? | ? | – | ● |
| Campaigns of dependent jobs | ◐ ¹⁹ | ? | ◐ ²¹ | ? | ◐ ⁹ | ◐ ²⁰ | ? | ? | ? |
| License | MIT | LGPL-3.0 (core) | BSD-3 / MIT | Apache-2.0 | MIT | MIT | Apache-2.0 | Apache-2.0 | LGPL |

1. Dense BFGS, at most 256 variables; a local method.
2. Any method the user connects as a generator; libEnsemble supplies the execution.
3. Scalar expressions with optional box bounds.
4. Bayesian optimization only.
5. Exact GP, 1-32 continuous box variables, at most 256 observations, synchronous batches up to eight, source-only.
6. An agent application that uses MCP and Python tools.
7. HiGHS or cuOpt for supported problem shapes.
8. pymoo NSGA-II/III.
9. Persistent studies when storage is configured.
10. Problems and completed runs persist; active job handles live in a Python dictionary.
11. Restart files preserve evaluations, not necessarily optimizer state.
12. CPU slots shared by all concurrent jobs on a node; cooperative accounting, not CPU affinity, kernel quotas or memory reservations.
13. Process count for parallel multistart.
14. Threads, processes or nodes sharing one study storage.
15. A pool of GPU workers.
16. Four background solve threads with bounded accepted work.
17. Exact-solver checks for supported formulations.
18. Explicit placement of a job on a registered SSH node through the CLI, with a pinned host key and node identity; no automatic scheduling or budget across nodes. The tests simulate the node's systemd user manager; behavior on real hosts is not yet commissioned.
19. experiment-craft 0.4 (unreleased): JSON campaigns with sweeps, dependencies, budgets and deadlines, run locally and sequentially; predeclared descriptive comparisons; reports keep native claims; no statistical inference.
20. Persistent Bayesian-optimization campaigns (Section 3.5).
21. Ensembles of generator and simulation calls (Section 3.2).

### 2.3 Where fcmaes & craft is strongest

1. **Breadth in one locally run, MIT-licensed stack.** LP/MILP, constrained
   NLP, black-box, multiobjective, quality-diversity and surrogate search share
   one routing guide and one job contract. GEMSEO comes closest in
   mathematical breadth among the systems in Section 2.1, and quality
   diversity was not found in any of them (pyribs and QDax are QD libraries
   without a job service; see Section 6.3).
2. **A job service designed for agents.** Discovery describes the node (CPUs
   and memory the host provides) and each worker (payload schemas, runnable
   examples, resource limits). `validate_job` checks a job before it runs.
   `put_input` stages data such as an LP model. Jobs outlive the MCP server;
   with the MCP Tasks extension, a submitted job completes as a task. Optees
   keeps job records in memory, Frontier's active jobs are process-local, and
   cuOpt's restart behavior is not established.
3. **Result semantics with precedents.** `optimization.result/0.2` keeps
   three answers apart: why the task stopped (`termination`), what the worker
   asserts (`claim`) and how much of it was verified (`evidence`).
   - **Claims** such as `numerical_optimum`, `first_order`, `best_found`,
     `non_dominated_set` and `elite_archive` reuse precedents from
     MathOptInterface, MathOpt, OSrL and COCO where one exists.
   - **Evidence levels** are `claimed`, `rechecked` and `certified`.
     `rechecked` means the returned points were recomputed from the
     registered model outside the solver.
   - **Refutations** (`evidence.refuted`) reuse the solver competitions'
     categories of wrong answers, such as `infeasible_point` and
     `false_optimality`.

   Among the systems checked, only Optees documents a comparable
   separation.
4. **One CPU budget for all jobs on a machine.** The runner admits jobs
   against declared CPU slots with `outer_workers * inner_threads <=
   cpu_slots`, so eight slots can mean eight independent searches or one
   internally parallel task. libEnsemble, Dakota and Ray manage resources
   too, aimed at clusters.
5. **Evaluation stays native.** Objectives run inside the worker next to the
   optimizer. Through optuna-mcp, evaluation happens in another tool, so an
   agent pays a round trip per batch of observations unless it runs a scripted
   Optuna campaign instead. BO-MCP leaves evaluation to external experiments
   by design.
6. **Honest budget accounting.** The fcmaes worker declares per optimizer
   whether its evaluation limit is hard (BiteOpt) or soft, with the maximum
   overshoot per retry:
   - `2*population-1` for serial DE, none for DE with `batch`;
   - `population-1` for CMA-ES, CR-FM-NES and PGPE;
   - `max_population-1` for CMA-ES with restarts.

   Results always report the evaluations actually made.
7. **Low installation friction.**
   - **Python:** wheels for Linux x86_64, Windows x64 and macOS (Intel and
     Apple Silicon) need no compiler: `pip install fcmaes`, `lp-ip-craft` or
     `sqp-craft` (CPython 3.10 or newer) and `fcmaes-rust` (CPython 3.11 to
     3.13).
   - **Rust:** the libraries are on crates.io (`fcmaes-core`, `lp-ip-craft`
     with `lp-ip-craft-native`, `sqp-craft-solver` and its four companions),
     as are the job crates.
   - **Pure Rust solvers:** fcmaes-core, LP-IP-craft and SQP-craft link no
     C/C++ solver library, and the LP engine does not use HiGHS. fast-cma-es
     is the exception: its native backend is C++17.
   - **No `unsafe` in the solver libraries:** fcmaes-core and the LP-IP-craft
     and SQP-craft library crates declare `#![forbid(unsafe_code)]`. The
     Python binding crates of the craft packages and the job runner, which
     supervises processes through libc, do not.
8. **Maturity of the black-box methods.**
   - fast-cma-es has been developed since January 2020 and published on PyPI
     as `fcmaes` since February 2020, with 133 releases
     ([release history](https://pypi.org/project/fcmaes/#history)) and 164
     GitHub stars as of 23 October 2026.
   - [OptunaHub's FastCmaesSampler](https://hub.optuna.org/samplers/fcmaes/),
     by Jacob Pfeil, wraps fast-cma-es's CMA-ES, so Optuna users can already
     call it.
   - fcmaes-rust, which the job worker uses, is a native Rust
     reimplementation started in July 2026, without the C++ backend. Its
     track record is that of the algorithms, not of the new code.
9. **Worked applications.** fcmaes-rust has 22 application tutorials,
   covering astrodynamics, robotics, circuits, phased arrays, production
   lines, biochemical oscillators, optics, CFD and water networks.
   fast-cma-es adds 44 tutorials, from scheduling and routing to space flight
   and power plants. They are concrete starting points, not benchmarks.
10. **Kept consistent across repositories.** Each solver repository pins one
    revision of the shared job crates, guide and test scripts. A weekly check
    fails when optimization-jobs has changed any of them since the pin, so
    pins move instead of drifting. experiment-craft's baseline lock pins the
    runner and the three workers to merged commits and rebuilds and tests
    them together. A
    [landing page](https://dietmarwo.github.io/optimization-jobs/) with
    `llms.txt` and a JSON catalog points agents to the right guide.

### 2.4 Where the alternatives are stronger

- **Several machines, GPUs, HPC.** fcmaes & craft runs a job on one Linux
  node. It can place a job on another node registered over SSH, but it does
  not schedule across machines, and the durability of such jobs on real hosts
  is still being commissioned. libEnsemble, Ray Tune, Dakota (MPI) and Optuna
  (shared storage) schedule across nodes; cuOpt targets GPUs.
- **Mature campaign tooling.** Optuna's studies, BO-MCP's campaigns and
  libEnsemble's ensembles have more users and features. experiment-craft is
  new, local and sequential. Its comparisons are descriptive, with no
  significance tests, and its dashboard serves only the local machine.
- **Large sparse NLP and multidisciplinary models.** SQP-craft is dense and
  limited to 256 variables. GEMSEO and OpenMDAO with Ipopt-family solvers
  handle large sparse and coupled models.
- **Hard industrial MIP.** LP-IP-craft's own guidance records cases where
  HiGHS is faster or proves more MIPs; cuOpt adds GPU scale. LP-IP-craft has
  no QP or MIQP, while Optees covers convex QP.
- **Bayesian optimization beyond a small deterministic box.** The surrogate
  profile is deterministic, continuous, synchronous and limited to 32
  variables. BO-MCP (BoTorch/BayBE, batches that account for pending
  experiments), Open Source Vizier (mixed search spaces) and Optuna's
  samplers reach beyond that scope.
- **Symbolic and combinatorial classes.** SAT, SMT, constraint programming and
  ASP belong to tools such as MCP Solver.
- **Community and track record.** Optuna and Dakota have large user
  communities and long histories. Apart from fast-cma-es, the toolbox is new
  and has one maintainer.
- **Platforms and registration.** The runner needs Linux. The job workers are
  built from source, and arbitrary Python functions cannot be registered as
  jobs: there is no stock fast-cma-es worker.

### 2.5 What the efficiency evidence does and does not establish

Four quantities need separate measurement:

1. Time to select the next candidate, factor a matrix or solve a model.
2. Throughput of objective evaluations, including Python/native boundaries and
   data movement.
3. Scheduling overhead, resource utilization and behavior with uneven task
   durations.
4. Agent interaction cost: tool calls, tokens, setup failures and time to a
   verified answer.

A well-designed MCP interface can sit on a slow numerical backend. A Python
orchestration layer can call efficient compiled solvers. A Rust
implementation can reduce overhead without being algorithmically faster.
Batch Bayesian optimization can save expensive evaluations while spending
more computation per batch. Documentation and source inspection identify
credible systems to test; they do not replace the tests. No "as fast as",
"faster than" or universal scaling claim follows from this comparison.

## 3. The alternatives, compared with fcmaes & craft

### 3.1 GEMSEO: the broadest mathematical alternative

GEMSEO's published catalog includes SciPy/HiGHS LP, SciPy MILP, SLSQP and
NLopt methods, an Ipopt plugin, pymoo methods and surrogate-based
optimization. It is a real alternative to combining separate linear, local and
global solver libraries. The catalog also lists commercial integrations;
choose an open-source configuration for a comparison. The core is
LGPL-3.0; plugin licenses need separate inspection. Its multistart settings
expose the number of processes for independent suboptimizations.

**Compared with fcmaes & craft.** GEMSEO is stronger in multidisciplinary
modeling, solver choice and large NLP. fcmaes & craft adds what an agent needs
around the solvers: an MCP job service, durable records, a node-wide CPU
budget, claim/evidence results and quality-diversity search. GEMSEO's agent
path means connecting the model, selecting plugins, allocating resources and
presenting results.

Sources: [algorithm catalog](https://gemseo.org/more_on/catalogs/optimization/), [parallel multistart settings](https://gemseo.readthedocs.io/en/6.3.3/_modules/gemseo/algos/opt/multi_start/settings/multi_start_settings.html), [licenses](https://gemseo.readthedocs.io/en/stable/software/licenses.html).

### 3.2 libEnsemble: the strongest execution layer for many nodes

The core assigns CPUs, GPUs and nodes to dynamically generated computations
and supports monitoring and cancellation. That goes well beyond a solver's
thread-count argument and suits external programs and expensive simulations.
Ensemble Agent creates and runs libEnsemble workflows, uses a separate MCP
script-generation server, and attempts repairs when generated scripts fail;
its README documents remote execution through Globus Compute. It is an agent
application using tools, not an MCP service for every lifecycle operation.
Setup currently involves a source checkout and manual dependencies. The core
is BSD-3-Clause; the agent is MIT.

**Compared with fcmaes & craft.** libEnsemble wins for multi-node
orchestration and should be studied before building distributed scheduling
into optimization-jobs. fcmaes & craft brings built-in solvers, result
semantics and a packaged MCP service for one node. For very cheap
objectives, keeping evaluation inside a native worker avoids dispatch costs;
how much libEnsemble's dispatch costs in that case still needs
measurement.

Sources: [core introduction](https://libensemble.readthedocs.io/en/main/introduction.html), [agent README at the inspected revision](https://github.com/Libensemble/ensemble_agent/blob/aae6a43cab2bd3868d2ab0dccb2e3a37527e213f/README.md), [organization and licensing](https://github.com/Libensemble).

### 3.3 Optees: the closest agent-facing contract

Optees exposes:
- capability discovery, versioned schemas, validation, execution and
  structured results;
- job status reported apart from mathematical status and verification;
- LP/MILP, convex QP, robust linear models, packing, knapsack and restricted
  nonlinear expressions.

Its license is Apache-2.0. At the inspected revision, `LocalJobService`
constructs a `ThreadPoolExecutor(max_workers=1)` and keeps job records in
memory. Cancellation of running jobs is documented for the packing
capability. One dispatch worker does not limit every numerical backend to
one CPU thread. The nonlinear interface accepts scalar expressions with
optional box bounds.

**Compared with fcmaes & craft.** The two designs agree on schema-first jobs
and on separating job, mathematical and verification status, which supports
the approach. Optees adds convex QP, combinatorial capabilities and a desktop
UI. fcmaes & craft adds:
- concurrent jobs under one CPU budget;
- journaled records that survive the server, and repair;
- evidence levels with recorded refutations;
- global, multiobjective and QD search;
- a general constrained NLP interface backed by model code.

Sources: [overview](https://github.com/Pablo-gitub/optees), [job service implementation](https://github.com/Pablo-gitub/optees/blob/9c613503ee13baa9a76ce7befad5c6452ba3ca3f/src/optees/application/services/local_job_service.py), [job lifecycle and limits](https://github.com/Pablo-gitub/optees/blob/9c613503ee13baa9a76ce7befad5c6452ba3ca3f/docs/guides/local-agent/job-service.md).

### 3.4 Optuna with optuna-mcp: mature black-box campaigns, evaluation outside MCP

The official MIT-licensed MCP server exposes study management, sampler
selection, ask/tell, Pareto results and visualization. A storage argument
makes studies persistent. Optuna core documents threads, multiple processes
with shared storage and multinode configurations. The inspected MCP tools do
not launch or supervise objective workers. In the examples, candidates are
evaluated through another tool and the observations are submitted afterwards.
For many cheap evaluations, an agent should run a scripted campaign instead of
reasoning between evaluations.

**Compared with fcmaes & craft.** Optuna has the larger community, more
samplers and multinode execution. fcmaes & craft evaluates inside native
workers and adds LP/MILP and constrained NLP. The two also connect: OptunaHub's
FastCmaesSampler runs fcmaes CMA-ES inside Optuna.

Sources: [MCP documentation](https://github.com/optuna/optuna-mcp), [distributed optimization](https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html), [inspected tool implementation](https://github.com/optuna/optuna-mcp/blob/0e694df595a48bee646f9b2bf581ce28d80a8fb6/optuna_mcp/server.py).

### 3.5 BO-MCP: Bayesian campaigns for external experiments

This MIT-licensed project combines BoTorch/BayBE backends with MCP, REST,
persistent campaigns and an agent cookbook. Its operations layer manages
observations, pending suggestions, backend state, diagnostics and provenance.
SQLite works locally; the Docker setup uses shared PostgreSQL. It supports
batch recommendations that account for pending experiments; measurements
come from an external evaluator or laboratory. Recommendation work runs in a
thread, and the timeout helper states that timing out the request does not stop
that computation, so pausing a campaign is not killing an optimizer process.

**Compared with fcmaes & craft.** BO-MCP is the stronger choice for
laboratory-style campaigns and richer BO. fcmaes & craft's surrogate profile
targets small deterministic simulations evaluated inside a native worker, with
an evaluation log artifact and warm observations. Ideas worth comparing are
candidate identity, duplicate handling, pending-point tracking and persistent
model state. No performance difference between the two Bayesian backends was
established.

Sources: [overview](https://github.com/AccelerationConsortium/bo-mcp), [agent cookbook](https://github.com/AccelerationConsortium/bo-mcp/blob/main/packages/bo-mcp-server/AGENT_COOKBOOK.md), [recommendation and timeout implementation](https://github.com/AccelerationConsortium/bo-mcp/blob/56d590b91ac120d0f22a3e41e770843d271808cd/packages/bo-mcp-server/src/bo_mcp_server/operations/generate_suggestions.py).

### 3.6 NVIDIA cuOpt MCP: a GPU solver service

NVIDIA's Apache-2.0 repository includes an MCP client for LP/MILP:
- submission, polling and result retrieval;
- incumbent inspection, cancellation and settings discovery.

The MCP process needs no local GPU; it connects to a GPU backend and can
return large solutions as summaries and files. The gRPC backend uses separate
GPU worker processes, with queueing, worker replacement and cancellation by
terminating a worker. Whether a server restart resumes an interrupted solve
is not established.

**Compared with fcmaes & craft.** cuOpt is the comparison for GPU-scale
LP/MILP. LP-IP-craft runs on any CPU without a service and checks returned
points independently. fcmaes & craft also covers non-linear problem classes
that the inspected MCP interface does not expose. Do not attribute the wider
cuOpt product to its MCP interface.

Sources: [MCP README](https://github.com/NVIDIA/cuopt/blob/main/python/cuopt_mcp/README.md), [gRPC architecture](https://docs.nvidia.com/cuopt/user-guide/latest/cuopt-grpc/grpc-server-architecture.html), [license](https://github.com/NVIDIA/cuopt/blob/main/LICENSE).

### 3.7 Frontier: guided multiobjective decisions

Frontier (Apache-2.0) combines pymoo NSGA-II/III with optional HiGHS/cuOpt
solves for supported problem shapes. It focuses on selection and allocation
with competing objectives and scenarios, and its MCP server supplies workflow
guidance. The source defaults to four background solve threads and bounds
accepted work. Problems and completed runs persist, but active job handles
live in a Python dictionary, and the architecture document defers a
solve-cancel action. Its exact-solver checks apply to supported formulations;
they do not prove an evolutionary front complete.

**Compared with fcmaes & craft.** Frontier's stage-by-stage guidance and
decision explanations are worth learning from. fcmaes & craft is general
rather than domain-specific, keeps active jobs durable and cancellable, and
reports a front as `non_dominated_set` without claiming Pareto optimality.

Sources: [overview](https://github.com/cafzal/frontier), [jobs implementation](https://github.com/cafzal/frontier/blob/c4d406b682116cce7800877fb14b3618c82260ca/mcp_server/jobs.py), [architecture](https://github.com/cafzal/frontier/blob/c4d406b682116cce7800877fb14b3618c82260ca/architecture.md).

### 3.8 Dakota: broad, established, used through a shell

Dakota combines:
- gradient and nongradient optimization;
- surrogate strategies, calibration and uncertainty analysis;
- mixed-integer nonlinear workflows.

It parallelizes at several levels, locally and with MPI. Restart files
preserve evaluations for reuse, which is not necessarily a checkpoint of every
optimizer's internal state. A coding agent can generate an input file and a
simulation driver. Dakota uses LGPL licensing, with separate terms for
included components and its GUI.

**Compared with fcmaes & craft.** Dakota is stronger for expensive engineering
simulations, uncertainty quantification and HPC. fcmaes & craft is quicker to
put in an agent's hands for what its workers already support (LP/MILP data,
registered models): an MCP service, schemas, examples and checked results.
A new nonlinear model still needs worker code, much as Dakota needs a
driver.

Sources: [capabilities](https://dakota.sandia.gov/about-dakota/), [parallel execution](https://snl-dakota.github.io/docs/latest_release/users/usingdakota/advanced/parallelcomputing.html), [restart behavior](https://snl-dakota.github.io/docs/6.24.0/users/usingdakota/running/restart.html), [licensing](https://dakota.sandia.gov/license/).

### 3.9 Other alternatives and components

| Project | Relevance | Boundary |
|---|---|---|
| [Ray Tune](https://docs.ray.io/en/latest/tune/tutorials/tune-resources.html) | Cluster-aware trials, CPU/GPU resource requests, searcher integrations, [experiment restoration](https://docs.ray.io/en/latest/tune/tutorials/tune-fault-tolerance.html) | An execution/search framework, not a solver suite; resource requests do not cap objective threads; restoration needs storage and checkpoint setup |
| [Open Source Vizier](https://github.com/google/vizier) | Apache-2.0 distributed black-box service, mixed search spaces, JAX Bayesian optimization, benchmarking APIs | Evaluations are the client's job; no first-party MCP interface found |
| [OpenMDAO](https://openmdao.org/newdocs/versions/latest/) | Coupled engineering models, derivative-based optimization, [MPI/PETSc](https://openmdao.org/newdocs/versions/latest/getting_started/getting_started.html), parallel derivatives | A model-integration framework, not an agent job service |
| [MCP Solver](https://github.com/szeider/mcp-solver) | MIT; SAT, MaxSAT, SMT, constraint programming, ASP and dynamic programming with an interactive kernel | Complements fcmaes & craft with classes it does not cover; a syntax-checked submission is not a proof |
| [optimization-mcp](https://github.com/eesb99/optimization-mcp) | MIT; allocation, scheduling and portfolio tools | Its MCP handler solves synchronously; no durable job subsystem found. Unrelated to this repository's `optimization-mcp` binary |
| [highs-mcp](https://github.com/wspringer/highs-mcp) | MIT; a small agent interface for HiGHS | Uses the npm WebAssembly build; native HiGHS performance does not carry over |
| [USolver](https://github.com/sdiehl/usolver) | Apache-2.0 prototype combining symbolic and numerical solvers | Archived and unmaintained |

Two projects are worth watching but are not counted as confirmed open-source
alternatives:

- [emdgroup/baybe-mcp](https://github.com/emdgroup/baybe-mcp) exposes
  stateless recommendations, prediction and parameter importance, with
  schemas and recipes derived from the installed BayBE version, a good model
  for keeping agent documentation in sync with code. At the inspected
  revision it had no license file or declaration.
- [Veoveo](https://github.com/BiomaAI/veoveo) advertises durable MCP tasks,
  independently checked cuOpt results and a Rust platform, and requires
  GPU-backed execution. No open-source license could be established from the
  repository.

## 4. fcmaes & craft in detail

The six repositories form a toolbox with a common execution layer, not one
universal solver. The numerical choice depends on mathematical structure and
on where the objective is implemented; the job layer makes supported
computations discoverable, budgeted and inspectable, and experiment-craft
composes such jobs into campaigns. All six are MIT; check dependency and data
licenses separately.

| Repository | Responsibility | Agent entry point | Registry release (Oct 2026) |
|---|---|---|---|
| optimization-jobs | Jobs, CPU admission, supervision, results, MCP | [`ai-context.md`](../ai-context.md), then worker discovery | crates.io `optimization-job-api`, `optimization-runner` 0.3.0 |
| fcmaes-rust | Native global, multiobjective and QD search; experimental surrogate | Rust library, Python `fcmaes_rust`, or the fcmaes worker | crates.io `fcmaes-core` 0.2.1, PyPI `fcmaes-rust` 0.2.1 |
| fast-cma-es | Python optimization with native C++ algorithms | Python library, examples, tutorials | PyPI `fcmaes` 2.1.0 |
| LP-IP-craft | LP and MILP | Sparse model data through the library or a job | PyPI `lp-ip-craft`, crates.io `lp-ip-craft` and `lp-ip-craft-native` 0.29.0 |
| SQP-craft | Small smooth constrained NLP | A differentiable model through the library or a worker | PyPI `sqp-craft`, crates.io `sqp-craft-solver` and four companion crates 0.17.0 |
| experiment-craft | Campaigns of jobs: sweeps, dependent steps, budgets, deadlines, reports; predeclared comparisons; pause, backup and restore | The `experiment-craft` CLI over JSON campaign manifests and comparison protocols; a local browser dashboard | Not released; 0.4.0 builds from source |

The job workers (`fcmaes-job-worker`, `lp-ip-job-worker`, `sqp-job-worker`)
are built from source in their repositories.

### 4.1 optimization-jobs: execution and evidence shared by the solvers

**Architecture.** `optimization-job-api` holds:
- the job envelope `optimization.job/0.1`;
- the result contract `optimization.result/0.2`;
- input hashes, checked journals and the worker SDK.

`optimization-runner` builds the `optimization-run` CLI and the
`optimization-mcp` stdio server. Solver repositories pin one shared revision
instead of copying the code, and the runner contains no optimization
algorithm. `cargo install optimization-runner --locked` installs both
binaries.

**Agent workflow.** An MCP client:
1. reads `get_guide`;
2. inspects `describe_node` and `describe_worker` for payload schemas and
   runnable examples;
3. stages data with `put_input` and checks the job with `validate_job`;
4. submits, follows, waits for, cancels or kills jobs;
5. reads results, events and paged artifacts, and repairs interrupted records.

With the MCP Tasks extension, a submitted job is a task that completes with
its result. The MCP server cannot register workers or change the node. A
shell agent uses the same workflow through the CLI and can build and
register further workers.

**Execution model.** A node reserves CPU slots across concurrent jobs with
`outer_workers * inner_threads <= cpu_slots`. Input hashes, staged
executables, provenance, checked task journals and lifecycle records keep
runs inspectable after the conversation or MCP connection ends. Admission is
cooperative accounting, not CPU affinity, a kernel quota or a memory
reservation.

**Result semantics.** Termination, claim and evidence are separate fields,
and a rejected claim is recorded in `evidence.refuted`
([details](job-api.md#termination-claim-and-evidence)). A
completed job can contain a time-limited feasible answer. When a solver's
claim fails an independent check, the job records the refutation instead of
failing. SHA-256 verifies recorded bytes, not mathematical correctness; each
solver supplies the numerical checks.

**Remote placement.** From 0.4.0 the runner places a job on a node registered
over SSH (`fleet submit --node NAME`), with a pinned host key and node
identity. A fixed helper receives every request as JSON, and the persisted
dispatch intent means an uncertain start is observed on that node, never
repeated or moved. There is no automatic placement or budget across nodes,
and the tests simulate the node's systemd user manager
([SSH guide](job-api.md#explicit-ssh-placement-and-recovery)).

**Limits.**
- Runs on Linux, as a local, single-user service.
- No automatic scheduling across machines, no arbitrary code submission, no
  general remote ask/tell session.
- No exact resume of optimizer state: recovery keeps committed work and
  finalizes records, but does not resume a branch-and-bound tree or a CMA-ES
  population.
- Nonlinear models must be registered in a worker.

Use it to supervise substantial campaigns, and keep cheap numerical
iterations inside the worker.

Sources: [overview and install](https://github.com/dietmarwo/optimization-jobs/blob/c2dc7e878865eebe31fb14d1dd2644fd6392c0bd/README.md), [agent routing guide](https://github.com/dietmarwo/optimization-jobs/blob/c2dc7e878865eebe31fb14d1dd2644fd6392c0bd/ai-context.md), [job protocol and lifecycle](https://github.com/dietmarwo/optimization-jobs/blob/c2dc7e878865eebe31fb14d1dd2644fd6392c0bd/docs/job-api.md).

### 4.2 fcmaes-rust: native search and application workers

**Algorithms.** `fcmaes-core` implements in Rust:
- DE, active CMA-ES, CR-FM-NES, PGPE, Dual Annealing and BiteOpt;
- basic and coordinated retry, and weighted multiobjective retry;
- constrained MODE, MAP-Elites and Diversifier.

A two-objective archive keeps the nondominated observed points within its
reference box; that is the exact observed set, not the unknown global
Pareto front. The implementation does not use the historical C++ backend.

**Integration.**
- Rust applications call the core directly; Python uses `fcmaes-rust`
  (`import fcmaes_rust`).
- For durable jobs, the `fcmaes-job-worker` exposes the retry, MODE,
  MAP-Elites, surrogate and evaluate profiles.
- An application worker registers its own scalar, multiobjective or
  descriptor model, with versioned parameters and hashed data inputs.

**Parallel execution.** Independent restarts spend cores on different
basins; ask/tell or batch evaluation spends them on candidates within one
search. Compare both at the same wall time and CPU budget. Native objectives
avoid Python callback overhead; Python callbacks can be GIL-bound. Retry can
also wrap an external optimizer.

**Surrogate.** The source-only `fcmaes-surrogate` crate provides exact-GP
Bayesian optimization through `fcmaes.surrogate/1`:
- Matérn-5/2 or RBF kernels, LogEI or LCB, an optional trust region;
- synchronous batches of at most eight;
- deterministic scalar box problems with 1-32 variables and at most 256 new
  plus retained observations.

It has no constrained, mixed-variable, asynchronous or noisy BO. Warm
observations start a new job; they are not a checkpoint resume.

**Release notes.** 0.2.0 (22 October 2026) contains the MODE fixes and
`ParetoArchive2D`. 0.2.1 (23 October 2026) fixes errata found by testing the
published 0.2.0 wheel:
- 0.2.0 accepted only NumPy arrays of the exact dtype (`float64`, `bool` for
  `ints`), although its type stub admits sequences. 0.2.1 also accepts lists
  and tuples, with the same results.
- In 0.2.0 several invalid inputs raised pyo3's `PanicException`; 0.2.1
  raises `ValueError`.
- `optimize_da` panicked on a bounded problem when every start value was at
  or above `1e16` (a large penalty, `inf` or NaN). 0.2.1 returns
  `stop == -1` with the best point evaluated.
- A raising objective counts as a failed evaluation in both versions. 0.2.1
  logs the first failure of a run once as a warning on the `fcmaes_rust`
  logger, where 0.2.0 was silent.

`optimize_de` checks `max_evaluations` once per generation and can spend up
to `2 * popsize - 1` more evaluations; the reported `evaluations` is always
the actual count, as the 0.2.1 documentation states. The revision cited below
predates 0.2.1; the
[changelog](https://github.com/dietmarwo/fcmaes-rust/blob/main/CHANGELOG.md)
lists the changes.

Ten of the 22 tutorials pin `fcmaes-core` 0.1.3 from crates.io, so rerun
their MODE results with 0.2.0 or later before using them in a comparison. A library
algorithm does not imply a matching job option.

Sources: [architecture and concurrency](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/docs/architecture.md), [agent and release guidance](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/ai-context.md), [application models](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/docs/job-api/models.md), [surrogate contract](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/docs/job-api/surrogate.md).

### 4.3 fast-cma-es: Python-first modeling and optimization

**Implementation.** The `fcmaes` package combines Python orchestration with a
C++17 backend exposed through nanobind. Modules ending in `cpp` select native
implementations; Python implementations also exist. Its API, packaging and
performance are separate from fcmaes-rust.

**Coverage.** The package covers:
- scalar gradient-free search, and parallel and coordinated retry;
- constrained multiobjective MODE and weighted multiobjective retry;
- MAP-Elites and Diversifier.

Integer flags help with discrete decisions, but a permutation or scheduling
problem still needs a correct encoding, repair and objective. The tutorials
are good starting points for an agent integrating an existing Python
simulator.

**Many-core use.** `retry`, `advretry` and `moretry` use processes, which
helps Python objectives that would serialize on the GIL. Population ask/tell
lets the application own evaluation and vectorization. BiteOpt's batch
interface gives delayed feedback: more throughput, but possibly less progress
per evaluation. Set worker counts explicitly when the CPU quota is below the
visible CPU count.

**Results and limits.** Scalar wrappers return SciPy-style results;
multiobjective and QD APIs return arrays or archives. Recompute the real
objective and constraints before accepting a result, especially behind
penalties or repairs. PyPI 2.1.0 contains the MODE corrections and
`ParetoArchive2D`. There is no stock fast-cma-es worker in the shared job
service: installing the package does not register Python functions with
optimization-jobs. Prefer derivatives or explicit structure when they are
more informative than black-box search.

Sources: [project overview](https://github.com/dietmarwo/fast-cma-es/blob/f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3/README.md), [agent guide](https://github.com/dietmarwo/fast-cma-es/blob/f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3/ai-context.md), [process retry](https://github.com/dietmarwo/fast-cma-es/blob/f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3/fcmaes/retry.py), [two-objective archive](https://github.com/dietmarwo/fast-cma-es/blob/f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3/fcmaes/pareto.py).

### 4.4 LP-IP-craft: native LP and mixed-integer linear optimization

**Model.** A linear objective with a constant offset, sparse row intervals
(CSR) and variable bounds; variables are continuous, integer or binary. MIP
variables, continuous ones included, need finite bounds, possibly inferred by
presolve. QP and MIQP are outside the model class.

**Engine.**
- LPs and node relaxations are solved by a bounded-variable dual revised
  simplex on a sparse LU factorization.
- Integer search combines best-bound selection, diving and pseudocost
  branching with presolve, propagation and optional cuts and heuristics.
- It links no HiGHS or C/C++ solver.
- The Python facade defaults to a dummy backend, so real solves pass
  `backend="native"`.

**Verification.**
- Candidate evaluation checks objective, rows, bounds and integrality
  independently of the search; LP residual checks add primal/dual
  information.
- `safe_dual_bound` rounds outward to give a bound that is valid for exactly
  feasible points of the stored binary64 model, when it can produce a finite
  one. This guarantee is narrower than a certificate for the whole MIP
  search, its cuts or the original decimal problem.

**Parallelism and jobs.**
- Numerical width is 1-8. Batches of independent models allow up to 16
  workers with serial kernels; mixed batches have a total width of eight.
  Batches and jobs disable hidden nesting.
- `lp-ip.solve/1` takes a hashed model artifact and optional complete MIP
  starts; `lp-ip.evaluate/1` checks given points.
- An MPS conversion script and discovery schemas give an MCP agent a
  data-only path.

**Limits and best use.** Use it for linear subproblems, dependency-light Rust
and Python integration and transparent checks. Benchmark demanding models
against native HiGHS: the project's own guidance records cases where HiGHS is
faster or proves more MIPs. A limited run still returns a checked incumbent
with a bound and gap where available.

Sources: [native API](https://github.com/dietmarwo/LP-IP-craft/blob/dfb336c8c81be423ace58777c6efb85c84fddc0a/docs/api.md), [operational guide and limits](https://github.com/dietmarwo/LP-IP-craft/blob/dfb336c8c81be423ace58777c6efb85c84fddc0a/ai-context.md), [safe-bound scope](https://github.com/dietmarwo/LP-IP-craft/blob/dfb336c8c81be423ace58777c6efb85c84fddc0a/docs/safe-dual-bounds.md), [job interface](https://github.com/dietmarwo/LP-IP-craft/blob/dfb336c8c81be423ace58777c6efb85c84fddc0a/docs/job-api.md).

### 4.5 SQP-craft: local refinement of smooth constrained problems

**Role.** A Rust SQP solver with Python bindings for at most 256 continuous
variables. A model supplies function values, a gradient and Jacobian values
for a fixed sparsity pattern. A sparse Jacobian does not make the dense BFGS
method a large sparse NLP solver.

**Algorithm.** Damped BFGS and QP subproblems, an ℓ1 merit line search and
bounded feasibility restoration. The default QP backend is Clarabel; a dense
active-set backend is the alternative and supports elastic mode. Second-order
correction and scaling are optional. Reliable derivatives and sensible scales
matter as much as the backend.

**Meaning of success.**
- `converged` means the declared first-order residual tolerances hold. It is
  not a global or second-order certificate.
- Non-convergence is no proof of infeasibility.
- The library checks derivatives and KKT residuals. In jobs, solve results
  carry independent evidence; `sqp.evaluate/1` re-evaluates functions and
  feasibility and is not a full standalone KKT check.

**Parallelism and integration.** For small NLPs, multistart pays more than
inner threads: Clarabel is serial and full BFGS is scalar. Rust batch solves
allow an outer-times-inner width of up to eight. The worker `Registry`
accepts custom models with configuration schemas and hashed inputs through
application workers, not executable code inside jobs.

**Limits and best use.** A local finishing tool for small, genuinely smooth
blocks with derivatives. Use several starts on nonconvex problems and compare
both QP backends. Larger sparse NLPs call for an Ipopt-family solver.

Sources: [agent guide](https://github.com/dietmarwo/SQP-craft/blob/b2c2c4322ad8df3d4b586888f18467100d674618/ai-context.md), [solver API](https://github.com/dietmarwo/SQP-craft/blob/b2c2c4322ad8df3d4b586888f18467100d674618/docs/api.md), [job interface](https://github.com/dietmarwo/SQP-craft/blob/b2c2c4322ad8df3d4b586888f18467100d674618/docs/job-api.md), [custom models](https://github.com/dietmarwo/SQP-craft/blob/b2c2c4322ad8df3d4b586888f18467100d674618/docs/job-api/models.md).

### 4.6 experiment-craft: campaigns over the jobs

**Role.** experiment-craft is the Python layer above optimization-jobs for
campaigns: parameter sweeps, comparisons and dependent steps. It owns
campaign composition, scientific choices and reports; the Rust runner keeps
execution, admission, staging and recovery. It contains no SSH code,
launcher or capacity ledger of its own.

**Campaigns.** A versioned JSON manifest expands deterministically into
ordinary optimization and command jobs; duplicate keys, cycles, ambiguous
bindings and oversized expansions fail before anything runs, and
initialization validates the jobs through the runner. Each step's request
key binds the plan, the input contents, the worker and runner identities,
the node and the workspace, so two runs of one manifest never share jobs.
SQLite records every decision before the client acts on it, so an
interrupted client continues the same jobs instead of submitting new ones,
and uncertain work is observed, never resubmitted. Campaign budgets (jobs,
declared slot-seconds, a deadline) are a client policy on top of the
runner's own admission.

**Results.** A dependent step can consume a verified command output or a
native result. Acceptance rules can require feasibility or particular
claims. Reports in JSON, CSV and Markdown list every step, including failed,
cancelled, blocked and unknown ones, with the native claim and evidence;
reporting submits no work and detects tampered cached results.

**Comparisons.** A comparison protocol is sealed in the campaign database
before the first job runs and cannot be changed afterwards. It names the
arms, the one solver setting that varies, the seeds or start points, a common
work or time cap and the metrics. Arms that differ in the model, the inputs,
the tolerances or the resources are refused, not pooled. Reports count every
planned run: failed, partial and missing results stay visible and never count
as zero. Means, medians and paired differences are computed exactly. There is
no ranking, significance test or confidence interval, and the first adapters
cover one task per job for fcmaes retry, LP/IP and SQP.

**Operations.** Dispatch can be paused and resumed; resuming first checks
every native handle with the runner. A paused campaign can be backed up to an
archive and restored into a new workspace, which starts paused and refuses
work that another copy of the campaign launched. A node inventory prepares
further machines: one local test node is the default, planned SSH workers stay
disabled, and an offline export writes the runner's own registration
commands. Campaigns still run on the local node only.

**Dashboard.** A browser page served on the local machine shows the attached
campaigns, their steps and per-node progress, and offers start, pause, resume
and stop with the same rules as the CLI. It is a single-operator tool behind a
token, not a hosted multi-user service, and it does not measure CPU, memory
or solver progress.

**Limits and best use.** Version 0.4 is local and sequential, needs Python
3.12 or later and is not on PyPI. Remote campaign routing and automatic
placement are not implemented, and real-host service and reboot behavior is
still being commissioned. Use it to make a sweep, a solver comparison or a
multi-solver pipeline reproducible and auditable, not for throughput.

Sources: [project overview](https://github.com/dietmarwo/experiment-craft/blob/main/README.md), [campaign guide](https://github.com/dietmarwo/experiment-craft/blob/main/docs/campaigns.md), [comparison guide](https://github.com/dietmarwo/experiment-craft/blob/main/docs/scientific-comparisons.md), [operating guide](https://github.com/dietmarwo/experiment-craft/blob/main/docs/operations.md), [dashboard guide](https://github.com/dietmarwo/experiment-craft/blob/main/docs/dashboard.md), [integration contract](https://github.com/dietmarwo/experiment-craft/blob/main/docs/integration-contract.md).

### 4.7 How an agent combines the repositories

Start with the shared routing guide, even when the solve uses only a library.
Determine the variable structure, required output, tolerances, available
derivatives and evaluation cost. Then choose the method, and only then the
execution interface.

| Need | Practical route | Acceptance check |
|---|---|---|
| Existing Python simulator | fast-cma-es with process retry or owned batch evaluation | Re-evaluate objective and raw constraints |
| Native Rust simulation | `fcmaes-core` directly or a registered fcmaes application worker | Re-evaluate the candidate with the same model and data identity |
| Expensive, small deterministic box problem | Compare the surrogate profile with retry at equal budgets | Count warm, new and validation evaluations separately |
| Linear model given as data | LP artifact, optional MPS conversion, `lp-ip.solve/1` | Objective, feasibility, integrality, dual/bound checks |
| Smooth small nonlinear model | SQP library or registered worker, usually multistart | Derivative checks before, KKT residuals after |
| Several campaigns sharing one machine | One optimization-jobs node with registered workers | Usable CPUs, declared slots, retained records, outcome evidence |
| A sweep or a multi-solver pipeline to repeat and audit | An experiment-craft campaign over one node | Every step reported with its native claim and evidence; no job submitted twice |
| Two solver settings to compare fairly | An experiment-craft comparison protocol sealed before the campaign runs | Same model, inputs and caps in every arm; every planned run counted, failures included |

A global-to-local pipeline is application integration, not automatic model
translation. Transfer variable order, units, bounds, model version,
parameters and data hashes consistently, and re-evaluate the point with the
receiving model before refining it.

For eight CPUs, compare `8 / 8 / 1`, `8 / 2 / 4` and `8 / 1 / 8` (slots /
outer / inner) where the profile supports them. Eight retries times eight
inner workers is not 64-way execution. Larger nodes admit several jobs, but
solver and profile caps still apply.

## 5. Choosing tools for SpOC4 Challenge 2

### 5.1 The mathematical structure

For ESA's Keplerian Tomato Traveling Salesperson Problem (KTTSP), the first
choice is **optimization-jobs with fcmaes-rust/fast-cma-es**, with LP-IP-craft
and SQP-craft used selectively. This assumes a shell-capable agent, 8-16 CPU
cores and the goal of the best verified feasible mission within a practical
time limit. It is a choice of development path, not a measured ranking.

The challenge couples a visit permutation with departure and flight times.
Transfers depend on the moving bodies and on Lambert solutions, so a fixed
distance matrix misses the problem. It is an open path visiting every target
once, with waiting allowed, a mission-time objective and rules limiting
transfer delta-v and exceptional high-delta-v moves.

| Instance | Targets N | Full representation (`3N - 2`) | Timing variables with route fixed |
|---|---:|---:|---:|
| Easy | 49 | 145 | 96 |
| Medium | 181 | 541 | 360 |
| Hard | 1,051 | 3,151 | 2,100 |

These sizes rule out a single full-vector GP surrogate, an unconstrained
generic CMA-ES encoding of the whole hard route, and passing all hard-instance
timing variables to SQP-craft. Even with the permutation fixed, choosing the
cheapest Lambert branch can make the timing problem nonsmooth.

Sources: [challenge specification](https://github.com/esa/SpOC4/blob/e4276399b51852e6f1c08c2d0c133bd13f8f967a/Challenge%202%20Keplerian%20Tomato%20Traveling%20Salesperson%20Problem/README.md), [instance files](https://github.com/esa/SpOC4/tree/e4276399b51852e6f1c08c2d0c133bd13f8f967a/Challenge%202%20Keplerian%20Tomato%20Traveling%20Salesperson%20Problem/problems).

### 5.2 Order of investment

For this problem, fast transfer evaluation, explicit route structure and custom
hybrid search matter more than breadth or agent interfaces.

| Rank | Tool or stack | Role at this point |
|---|---|---|
| 1 | fcmaes & craft | Native custom search and parallel restarts, Python prototyping, optional MILP and local NLP subproblems, one job and evidence layer |
| 2 | GEMSEO | Broad alternative for connecting models and continuous optimizers; a custom route-search layer is still needed |
| 3 | libEnsemble + Ensemble Agent | Orchestration when many searches or costly simulations run across nodes; rises for a multi-machine setup |
| 4 | Dakota | If expensive simulation, surrogates or uncertainty analysis become central |
| 5 | Optees / HiGHS interfaces | A discrete transfer-network master or local MILP neighborhood; tight loops call native HiGHS directly |
| 6 | Optuna | Tuning algorithm controls and restart budgets, not the full permutation-plus-timing problem |
| 7 | BO-MCP / Open Source Vizier | Low-dimensional expensive strategy tuning or a reduced continuous subproblem |
| 8 | NVIDIA cuOpt | A separate GPU experiment once a supported discrete formulation exists |
| 9 | Frontier | Its selection/allocation workflow fits this single-objective routing task least |

Ray Tune is an alternative orchestrator where cluster trial management already
exists. OpenMDAO rises if the task becomes smooth multidisciplinary trajectory
design. MCP Solver could help a symbolic subproblem but supplies no
astrodynamics. A solution needs a small effective stack, not all nine tools.

### 5.3 Why fcmaes & craft comes first here

There is domain work close to the toolbox:
[pykep-lambert](https://github.com/dietmarwo/pykep-lambert) contains KTTSP
transfer-table experiments, Numba acceleration, Rust integration and parallel
evaluation comparisons. It is an additional astrodynamics dependency, not one
of the five repositories.

Its author reports two measurements, neither reproduced here and neither
proof of better missions:
- a KTTSP table reduction from about 25.00 s to 1.94 s with the same 16
  threads;
- for a native eight-thread full-transfer comparison, about 4.38x for staged
  batches versus 7.40x for outer Rayon evaluation.

The lesson is that the location of the parallel boundary matters.

A practical split:
- Prototype the objective and route operators in Python, using fast-cma-es
  for continuous searches.
- Move measured hot loops into Rust, where fcmaes-rust supplies native search
  and reusable application workers.
- optimization-jobs supervises the campaigns.
- LP-IP-craft competes with HiGHS on formulated linear subproblems.
- SQP-craft refines small smooth blocks with valid derivatives.

No API solves the challenge from its URL: a correct KTTSP model and search
application are still required.

### 5.4 The solving sequence

1. **Freeze the reference evaluator and establish parity.** Pin the instance,
   official implementation, units, tolerances and Lambert behavior. Test the
   accelerated evaluator on ordinary transfers, exceptional moves, branch
   changes and near-threshold cases. Keep the official validation path for
   every reported incumbent.
2. **Build candidate transfers in parallel.** Cache propagation and transfer
   calculations where valid, generate a manageable time-dependent candidate
   network, and refine time resolution where good routes need it. Include
   preprocessing time and memory in the budget; heuristic pruning stays
   heuristic unless proven safe.
3. **Search route structure explicitly.** Construct feasible routes (for
   example by beam search), then apply insertion, exchange and destroy/repair
   neighborhoods. State tracks arrival time, waiting and remaining
   high-delta-v exceptions. Run independent searches and seeds in parallel.
4. **Refine timing and selected discrete neighborhoods.** Use fcmaes methods on
   bounded timing blocks when gradients are unreliable. Try SQP on
   branch-fixed smooth windows within its size limit, with checked
   derivatives. Formulate local transfer selection as MILP where faithful, and
   compare LP-IP-craft with native HiGHS.
5. **Compare complete campaigns on equal resources.** Start with eight
   independent serial workers, then fewer restarts with internally parallel
   evaluation. Record best verified mission time versus wall time, including
   preprocessing, failures and validation; use several seeds and keep a
   confirmation set.

This is a proposed workflow; no solver campaign was run for this document.

### 5.5 When the ranking changes

[The Keplerian Traveling Salesperson Problem](https://arxiv.org/abs/2605.00010)
(Bannach, Acciarini, Izzo) is useful for time-expanded networks, interval-based
discretization, preprocessing and domain heuristics; its guarantees belong to
its exact model. If the goal becomes a global optimality proof, exact
formulations and rigorous discretization move to the front. If objective calls
become very expensive, Dakota, GEMSEO, libEnsemble and surrogate services gain.
If execution spans several machines, libEnsemble or Ray rise ahead of further
work on the local runner. On one many-core CPU with custom fast astrodynamics,
fcmaes & craft stays the first development choice, subject to the same
verification and benchmarks as the alternatives.

## 6. Application areas where fcmaes & craft ranks high

The strongest applications beyond SpOC4 are custom simulation optimization,
mixed discrete/continuous design and searches that should return several
useful solutions.

### 6.1 Assumptions and tiers

The setting:
- an agent with a shell and one CPU with roughly 8-16 cores;
- permission to implement or register an application objective;
- many independent candidates or restarts, a bounded search representation
  and a native or compiled evaluator;
- a preference for verified, reproducible results.

MCP is an optional campaign interface; it should not carry every evaluation.

**A** means first implementation choice under these assumptions; **B** means a
strong shortlist candidate with an important specialist comparison. Tiers rate
engineering fit for an agent, not a measured league table, and apply to the
toolbox as a whole. They do not imply that all five repositories are needed,
or that LP-IP-craft and SQP-craft individually lead their solver
categories.

| Application area | Tier | Main reason |
|---|---|---|
| Mission and constellation design beyond SpOC4 | A | Astrodynamics examples, parallel global search, explicit discrete/continuous decomposition |
| Contact-rich robotics and controller repertoires | A | Isolated native rollouts, discontinuous behavior, quality-diversity search |
| Analog, filter and transient circuit design | A | Fast native simulation, component catalogues, competing waveform objectives |
| Quantized antenna and phased-array design | A | Hardware-code decisions, failure scenarios, beam catalogues |
| Stochastic production and maintenance systems | A | Discrete-event objectives, mixed controls, independent replications |
| Stochastic biochemical oscillator design | A | Native reaction simulation, nested topology/parameter search |
| Multimodal inverse problems | A | Parallel searches for competing explanations |
| Energy-system sizing with inner dispatch | B | Global architecture search with repeated LP subproblems |
| Water-network operations and quantized controls | B | Stateful simulation, switching decisions, scenario validation |
| Small optical-system design | B | Several optical basins, hard ray-loss boundaries |
| Custom flow, ventilation and geometry simulation | B | Independent native simulations with rebuilt geometry |
| Event-driven strategy and backtesting research | B | Threshold decisions, many trials, reproducible native replay |
| Small expensive deterministic simulations | B | Compact surrogate profile with job evidence and warm observations |

The tutorials linked below are concrete starting points in fcmaes-rust; they
show applicability, not superiority. Tutorials pinned to `fcmaes-core` 0.1.3
need their MODE results rerun with 0.2.0 or later before a performance
comparison, and an application tutorial must be integrated into a worker
before the jobs API can run it.

### 6.2 Mission and constellation design beyond SpOC4 (A)

**Examples:** multiple-gravity-assist trajectories, launch and encounter
timing, bounded transfer parameters, constellation layouts for ground-station
coverage.

**Why first:** native astrodynamics and independent retries are a central use
case. Encounter branches, visibility windows and worst-gap objectives create
multiple basins and abrupt changes. An agent can separate route or
architecture decisions from numerical timing and spend the CPU budget on
competing starts.

**Roles:**
- fast-cma-es: rapid Python prototyping.
- fcmaes-rust: native global search.
- optimization-jobs: records campaign inputs and outcomes.
- SQP-craft: small, smooth, branch-fixed refinements.
- LP-IP-craft: faithfully formulated selection subproblems, with application
  code doing the handoffs.

Sources: [GTOC1 tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/gtoc1/README.md), [Brahe constellation tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/brahe-constellation/README.md). Ephemerides, propagation fidelity and mission validation remain separate requirements; large sparse trajectory NLPs warrant a specialist comparison.

### 6.3 Contact-rich robotics and controller repertoires (A)

**Examples:** gait parameters, compact controller policies, release
mechanisms, behavior families spanning speed, energy and turning.

**Why first:** contacts, falls and discrete success conditions undermine
gradients, and independent physics worlds make candidate parallelism simple.
Quality diversity fits when the deliverable is a repertoire of behaviors
rather than one maximum-reward controller; the agent can inspect niches and
request more exploration.

**Roles:**
- fcmaes-rust: search and archives.
- fast-cma-es: Python simulators.
- optimization-jobs: supervises campaigns.
- SQP-craft: only for genuinely smooth subproblems.

Sources: [Rapier quadruped gait](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/rapier-quadruped-gait/README.md), [compact neural-controller search](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/neural-controller-policy-search/README.md). The gait model is a simplified simulation, not a validated hardware controller. Compare with [pyribs](https://docs.pyribs.org/en/latest/index.html) for QD algorithm breadth and [QDax](https://qdax.readthedocs.io/) for JAX and accelerators.

### 6.4 Analog, filter and transient circuit design (A)

**Examples:** filter sizing, E12 catalogue selection, gate resistance and
snubber tuning, trade-offs between overshoot, transition time, losses and
bandwidth.

**Why first:** small native circuit simulations run repeatedly without a
Python callback in the hot path. Catalogue decoding, peak selection and
threshold-crossing metrics add nonsmoothness. Global search and a Pareto front
give the agent alternatives to inspect and validate.

**Roles:**
- fcmaes-rust: leads the search.
- fast-cma-es: connects Python/SPICE workflows.
- optimization-jobs: keeps configurations and artifacts.
- SQP-craft: refines smooth sizing blocks.
- LP-IP-craft: optional, for linear component-selection models.

Sources: [sindr AC circuit design](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/sindr-circuit-design/README.md), [thevenin transient gate-driver design](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/thevenin-gate-driver/README.md), the latter with an independent ngspice validation path. Full transistor models, tolerances and signoff need circuit tools; the ranking concerns the optimization layer.

### 6.5 Quantized antenna and phased-array design (A)

**Examples:** phase-shifter and attenuator codes, robust beams under element
failures, catalogues covering pointing direction and beamwidth.

**Why first:** register settings make the landscape discrete; evaluations and
failure scenarios parallelize naturally; a behavior archive yields a beam
codebook, which matches the deliverable better than repeatedly finding the
same best beam.

**Roles:**
- fcmaes-rust: global, multiobjective and QD search.
- optimization-jobs: makes the campaign inspectable.
- fast-cma-es: interfaces with Python electromagnetic models.
- LP-IP-craft: separate allocation formulations.
- SQP-craft: smooth relaxations before quantization.

Sources: [phased-array codebook tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/phased-array-codebook/README.md), with implemented hardware codes and fault scenarios. Full-wave electromagnetic validation could change the ranking when evaluator cost dominates.

### 6.6 Stochastic production and maintenance systems (A)

**Examples:** buffer sizes, staffing, machine speed, preventive-maintenance
thresholds, throughput/energy/quality trade-offs.

**Why first:** queues, breakdowns, rework and threshold policies create a
stochastic discrete-event objective that resists smooth modeling. Native
simulation, common random numbers for comparisons and held-out scenarios for
confirmation fit the toolbox.

**Roles:**
- fcmaes-rust: simulation search.
- fast-cma-es: existing Python models.
- optimization-jobs: campaign evidence.
- LP-IP-craft: exact scheduling or allocation subproblems with a valid
  linear formulation.

Sources: [NeXosim production-line tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/nexosim-production-line/README.md). For deterministic scheduling or routing, investigate CP/MIP methods or [OR-Tools routing](https://developers.google.com/optimization/routing) first.

### 6.7 Stochastic biochemical oscillator design (A)

**Examples:** kinetic rates in stochastic reaction networks, robust
oscillation, regulatory-topology search with an inner parameter fit.

**Why first:** an agent's structural decisions separate cleanly from
high-volume numerical work. A proposer selects a topology; the native
optimizer tests whether any parameter region produces the behavior.
Independent retries and replications use the CPU, and distinct validation
seeds separate robust dynamics from lucky realizations.

**Roles:**
- fcmaes-rust: numerical search.
- optimization-jobs: supervises campaigns.
- fast-cma-es: Python entry point.
- SQP-craft: only for smooth deterministic models with derivatives.

Sources: [ReBop oscillator design](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/rebop-oscillator/README.md), [oscillator topology search](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/oscillator-topology-search/README.md). Computational models only, not biological validation. For smooth ODE parameter estimation, sensitivities and gradient methods come first; see [Diffsol's adjoint interface](https://martinjrobins.github.io/diffsol/specify/closure/adjoint_sensitivity.html).

### 6.8 Multimodal inverse problems (A)

**Examples:** locating several sources from sparse observations, fits with
censoring or thresholds, keeping several plausible explanations.

**Why first:** one local minimum can hide non-identifiability. Global retries
explore different basins, a Pareto front exposes competing fit criteria, and
QD keeps physically distinct solutions, which helps an agent choose the next
discriminating measurement.

**Roles:**
- fcmaes-rust: search and alternative-solution archives.
- fast-cma-es: connects forward models.
- optimization-jobs: records data identity and validation.
- SQP-craft: polishes smooth candidates.

Sources: [dispersion-source localization](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/dispersion-source-localization/README.md), with a synthetic educational model. A QD archive is not a posterior; use Bayesian inference tools when calibrated uncertainty is required.

### 6.9 Energy-system sizing with inner dispatch (B)

**Examples:** generation and storage capacities, inclusion switches and grid
tiers, with dispatch re-optimized over demand and weather scenarios.

**Why shortlisted:** a global design search and an LP engine complement each
other, and each candidate design solves its own dispatch model in parallel.

**Roles:**
- fcmaes-rust or fast-cma-es: the outer design.
- optimization-jobs: supervises campaigns.
- LP-IP-craft: a candidate inner solver to benchmark, not yet a demonstrated
  integration.

Sources: [bilevel energy-hub tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/energy-hub-bilevel/README.md), which uses **microlp** for dispatch today. Compare against a direct LP/MILP formulation before committing to outer black-box search; the cost model is synthetic.

### 6.10 Water-network operations and quantized controls (B)

**Examples:** pump-speed schedules, tank thresholds, valve settings, switching
penalties, demand robustness.

**Why shortlisted:** hydraulic state, quantized actuators and safety overrides
suit simulation-based global search, with candidates replayed at finer
resolution and under unseen scenarios.

**Roles:**
- fcmaes-rust and fast-cma-es: outer search.
- optimization-jobs: organizes the evidence.
- LP-IP-craft or SQP-craft: simplified subproblems, with checks that the
  simplifications hold.

Sources: [water-network scheduling](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/water-network-scheduling/README.md). It rejects its own QD catalogue gate, so the recommendation is scalar or multiobjective search. Domain-specific hydraulic optimization is an essential comparison.

### 6.11 Small optical-system design (B)

**Examples:** lens curvatures, thicknesses and air gaps with competing image
quality, size and feasibility.

**Why shortlisted:** several optical basins and changes in ray survival favor
global multistart, and native ray tracing keeps evaluations cheap.

**Roles:**
- fcmaes-rust: global search.
- fast-cma-es: connects optical packages.
- optimization-jobs: records prescriptions.
- SQP-craft: local refinement where smoothness and size allow.

Sources: [Cooke-triplet tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/optical-lens-design/README.md), a limited geometric ray tracer. Dedicated optical tools lead when tolerancing, diffraction, coatings or aspheres dominate.

### 6.12 Custom flow, ventilation and geometry simulation (B)

**Examples:** vent placement, baffles, flow-control geometry; trade-offs among
transport, energy proxies and worst-case exposure.

**Why shortlisted:** each design rebuilds its geometry and runs an isolated
simulation, which fits parallel candidates and scalar, multiobjective or
diversity objectives around one native evaluator. The fit is best for modest
CPU simulations under the developer's control.

**Roles:**
- fcmaes-rust: leads native search.
- fast-cma-es: connects Python or executable solvers.
- optimization-jobs: supervises wrapped runs.

Sources: [room-ventilation tutorial](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/tutorials/cfd-room-ventilation/README.md), a two-dimensional educational backend. For expensive multidisciplinary models, adjoint methods, GEMSEO/Dakota workflows and libEnsemble may be the better start.

### 6.13 Event-driven strategy and backtesting research (B)

**Examples:** threshold and window parameters in trading-rule simulations,
turnover constraints, strategies with distinct behavior across regimes.

**Why shortlisted:** discrete trades make the objective nonsmooth, while trials
run independently in a compiled replay loop, without a commercial license.

**Roles:**
- fcmaes-rust or fast-cma-es: the search.
- optimization-jobs: records data hashes and settings.

Sources: [native trading example](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/docs/examples.md#trading-strategy), which demonstrates integration, not profitability. A credible comparison needs transaction costs, leakage checks and untouched periods.

### 6.14 Small expensive deterministic simulations (B)

**Examples:** calibration or design with a small continuous vector, a
deterministic response and tens to a few hundred expensive evaluations.

**Why shortlisted:** the surrogate profile proposes batches inside a native
worker and keeps observation artifacts for warm starts, a short route from
model registration to a bounded campaign with evidence.

**Roles:**
- fcmaes-rust: the surrogate worker.
- optimization-jobs: execution and artifacts.
- fast-cma-es: the direct-search comparison.

Sources: [surrogate job profile](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/docs/job-api/surrogate.md), [comparison harness](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/benchmarks/surrogate-comparison/README.md). Limits as in [Section 4.2](#42-fcmaes-rust-native-search-and-application-workers). Compare with BO-MCP/BoTorch, egobox and Optuna samplers; the small checked-in benchmarks do not establish general leadership.

### 6.15 What each repository contributes

| Repository | Contribution across these domains | Boundary to preserve |
|---|---|---|
| fcmaes-rust | Native global, multiobjective, QD and bounded surrogate search close to the simulator | Application modeling and correctness remain the developer's |
| fast-cma-es | Python-first prototypes, integration with existing models | No stock jobs worker for arbitrary Python objectives |
| optimization-jobs | Discovery, validation, CPU-slot admission, run control, artifacts and evidence | A local runner, not a distributed scheduler or CPU isolation |
| LP-IP-craft | Linear subproblems, restricted discrete neighborhoods, repeated LP/MIP solves | Compare with mature solvers; keep good structured formulations |
| SQP-craft | Small smooth constrained refinements after global or structural search | Needs valid derivatives; dense size limit and local convergence |
| experiment-craft | Reproducible sweeps, predeclared comparisons and multi-solver pipelines with complete reports | A client over the runner, not a scheduler; local and sequential so far; descriptive statistics only |

An agent still builds the validated evaluator, the variable encoding,
objectives and constraints, worker registration or a shell driver, and any
cross-solver handoff. The tutorials reduce that work substantially; a domain
name alone is not an executable problem. Inspect the worker's discovery
output before choosing a profile.

## 7. How to establish measured rankings

Start with eight CPUs in total, then repeat on the target machine.
Distinguish eight independent workers from one solver using eight threads,
measure both patterns, and prevent nested BLAS/OpenMP/solver
oversubscription.

| Workload | Comparators | Main measurements |
|---|---|---|
| Representative LP/MILP instances | LP-IP-craft; native HiGHS; Optees as an interface comparison; cuOpt as a separate GPU track | Time to verified feasibility or target gap, final gap, memory, timeouts |
| Constrained nonlinear simulation | SQP-craft; GEMSEO/OpenMDAO with open-source local solvers | Time to the same feasibility/stationarity target, evaluations, failed starts |
| Expensive black-box objective | fcmaes-rust/fast-cma-es; Optuna; BO-MCP or Vizier; libEnsemble campaigns | Best feasible value against wall time and evaluation count |
| Cheap objective, parallel restarts | Native fcmaes path; equivalent configurations elsewhere | Evaluations per second, dispatch overhead, CPU utilization |
| Multiple objectives | MODE and the Pareto archive; pymoo/Optuna configurations; Frontier on supported models | Feasibility, hypervolume with a fixed reference, diversity, budget |
| Agent and job behavior | optimization-jobs; Optees; BO-MCP; libEnsemble or Ray workflows | Discovery success, schema errors, cancellations, restart behavior, lost or duplicated work |

The first application demonstrations to measure are phased-array codebooks,
stochastic production policies and circuit sizing: discrete controls,
stochastic simulation and multiobjective native search in models small enough
to audit. For each:

1. **Fix the application contract.** Pin the evaluator, units, constraints,
   data and independent acceptance checks; compare systems on the same valid
   problem.
2. **Choose a meaningful competitor.** Include a domain specialist or a
   structured formulation, not only another evolutionary optimizer. Report
   integration effort apart from numerical performance.
3. **Use equal resources.** Eight CPU workers in total; constrain nested
   threads; record hardware, memory, startup, preprocessing and verification
   time. Repeat at sixteen cores if that is the deployment target.
4. **Measure the requested result.** Time to a verified feasible target, or
   best accepted quality against wall time; fixed references for
   multiobjective output; useful coverage and quality on the actual grid for
   QD. Count actual evaluations, not requested budgets; include failures,
   stochastic variation and held-out scenarios.
5. **Use a specialist where appropriate.** Smooth ODE fits, molecular
   objectives with cheap gradients, standard routing, ordinary HPO, large
   sparse NLPs and hard MILPs can favor other tools; the
   [Lennard-Jones study](https://github.com/dietmarwo/fcmaes-rust/blob/68694416f09e6acae0a47638b08f9ba467571be3/foundations/LENNARD_JONES.md)
   shows why gradient methods belong in the comparison.

Use fixed datasets and tolerances, several seeds, separate cold-start from
steady-state timing, and keep unsuccessful runs. experiment-craft campaigns
can run the fcmaes & craft side of such a comparison reproducibly: a fixed
manifest, every step reported, unsuccessful ones included, and each job's
native claim kept. Its comparison protocols are sealed before the runs and
report descriptive summaries over every planned run. Results can be
submitted through the
[evaluation issue form](https://github.com/dietmarwo/optimization-jobs/issues/new?template=independent-evaluation.yml);
the [reference index](discovery/references.md) lists independent evidence.

## 8. Sources, revisions and scope

### fcmaes & craft revisions

Descriptions of the five original repositories refer to these revisions (the
default branch on 22 October 2026). Registry releases are listed in
[Section 4](#4-fcmaes--craft-in-detail); installed versions can lag the
source.

| Repository | Revision | License |
|---|---|---|
| [optimization-jobs](https://github.com/dietmarwo/optimization-jobs/tree/c2dc7e878865eebe31fb14d1dd2644fd6392c0bd) | `c2dc7e878865eebe31fb14d1dd2644fd6392c0bd` | MIT |
| [fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust/tree/68694416f09e6acae0a47638b08f9ba467571be3) | `68694416f09e6acae0a47638b08f9ba467571be3` | MIT |
| [fast-cma-es](https://github.com/dietmarwo/fast-cma-es/tree/f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3) | `f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3` | MIT |
| [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft/tree/dfb336c8c81be423ace58777c6efb85c84fddc0a) | `dfb336c8c81be423ace58777c6efb85c84fddc0a` | MIT |
| [SQP-craft](https://github.com/dietmarwo/SQP-craft/tree/b2c2c4322ad8df3d4b586888f18467100d674618) | `b2c2c4322ad8df3d4b586888f18467100d674618` | MIT |

The 21 October research inspected earlier revisions (LP-IP-craft `b851fe3`,
SQP-craft `7886c1b`, optimization-jobs `8d19278`, fcmaes-rust `5ba1d26`,
fast-cma-es `41ab507`). The 23 October update rechecked the statements about
the five repositories against the revisions above and the registries:
- package versions, wheel platforms, crate lists;
- MCP tool names, the result contract;
- `forbid(unsafe_code)` declarations, tutorial counts, the pin drift
  schedule;
- the fcmaes worker's declared evaluation limits;
- the fcmaes PyPI release history and GitHub stars;
- the published fcmaes-rust 0.2.0 wheel (the errata in Section 4.2).

The 25 October update added experiment-craft (Section 4.6), the explicit SSH
placement of optimization-jobs (Section 4.1) and the corresponding
capability marks; it describes the default branches of 25 October 2026. The
26 October update describes experiment-craft's predeclared comparisons,
operations and dashboard (Section 4.6) at its default branch of 26 October
2026. The alternatives were not re-inspected for either update.

### Alternatives: source revisions

The alternatives were not re-inspected for the updates. Source statements
refer to these shallow-clone revisions from 21 October 2026:

| Repository | Revision |
|---|---|
| optuna/optuna-mcp | `0e694df595a48bee646f9b2bf581ce28d80a8fb6` |
| szeider/mcp-solver | `24b7d6fb1d5e361eeb8558b6119ca8e8cb083a3a` |
| cafzal/frontier | `c4d406b682116cce7800877fb14b3618c82260ca` |
| Pablo-gitub/optees | `9c613503ee13baa9a76ce7befad5c6452ba3ca3f` |
| sdiehl/usolver | `778cc9491fb7f64a32bd5c713ba4a146aeda1650` |
| eesb99/optimization-mcp | `5cdd2e81dd5393633e2b6c5b83c9d44b334ae885` |
| Libensemble/ensemble_agent | `aae6a43cab2bd3868d2ab0dccb2e3a37527e213f` |
| wspringer/highs-mcp | `30dcd767c0746485ba342ec23987b9dcbd814fd8` |
| AccelerationConsortium/bo-mcp | `56d590b91ac120d0f22a3e41e770843d271808cd` |
| emdgroup/baybe-mcp | `63e9fd8cf192448bb28cde91b9dcd2ad94073804` |

NVIDIA's MCP documentation and the framework manuals (GEMSEO, libEnsemble,
Optuna, Dakota, Ray, Vizier, OpenMDAO) were read as retrieved on the research
date, without a pinned source audit. Candidate test suites were not
reproduced. Licenses were checked where declared.

### Scope

- The comparison covers documentation and source, not performance. No
  system was installed and benchmarked for it; reported timings stay
  attributed to their sources.
- Capability marks in [Section 2.2](#22-capabilities) summarize the cited
  sources; a "?" means the research did not check that capability, not that
  the system lacks it.
- Application tiers express engineering judgment under the assumptions of
  [Section 6.1](#61-assumptions-and-tiers).
- The maintainer of fcmaes & craft publishes this document; treat its
  judgments about the ecosystem accordingly and prefer measured, independent
  evidence where it exists.
