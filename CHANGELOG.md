# Changelog

All notable changes to `optimization-job-api` and `optimization-runner`
(`optimization-run`, `optimization-mcp`) are documented here. Both crates
share one version. Until 0.2.0 the crates lived in fcmaes-rust, LP-IP-craft
and SQP-craft; worker repositories depend on them through git at a pinned
revision. 0.3.0 is the first version on crates.io.

## [Unreleased]

### Added

- P1: versioned `execution.capabilities/0.1` discovery through `node
  capabilities`, `node doctor` and MCP `describe_node`; only optimization is
  advertised. `jobs execution ID` reads an additive `execution.record/0.1`
  terminal sidecar with process observations, containment, logs and a hashed
  native result reference. Old attempts are not backfilled; missing records
  return `execution_unavailable`. Published and embedded JSON schemas match.
- A test-only neutral adapter covers success, failure, timeout, queued
  cancellation and spawn/record-write failures without optimization output.
  CLI regressions cover old-worker compatibility, zero exit without a native
  result, signals, malformed journals, recovery and idempotent record reads.


- A [rail-traffic prompt tutorial](tutorials/agentic/rail-traffic/README.md) with synthetic timetable recovery, service-delay caps, queue-preserving alternatives, independent enumeration, stress replay and a CI execution entry. It reuses the existing LP/IP worker.

- Three further [prompt tutorials](tutorials/agentic/README.md): surrogate observation reuse and oscillator calibration, LP/IP relaxation and binary choices, and SQP multistart/backend checks. The driver verifies artifacts and independent numerical checks, with an explicit exception for the deliberately uncertified infeasibility claim. `build --chapter` selects the needed workers. A CI matrix builds and executes all three with real workers on current stable Rust, preserving plain diagnostic output and result artifacts.

- [Five prompt-driven tutorials](tutorials/agentic/README.md) cover trebuchet
  design, production policies, energy sizing, curve fitting and GTOC1 route
  screening. Each chapter has a copyable prompt, a walkthrough with a
  measured pilot result and a follow-up prompt. `tutorials/agentic/run.py`
  builds the workers (the optional application workers of four fcmaes-rust
  tutorials, the curve-fit examples of fcmaes-rust and SQP-craft, the
  LP-IP-craft worker) and runs the pilots through `optimization-run`,
  checking worker payload schemas, the job and result schemas, accounting
  and evidence, and keeping every spec, result and figure.

- `docs/optimization-systems-for-ai-agents.md`: fcmaes & craft compared with
  GEMSEO, libEnsemble, Optees, Optuna/optuna-mcp, BO-MCP, cuOpt, Frontier,
  Dakota and smaller agent-facing projects. It covers a systems table, a
  capability matrix, strengths on both sides, tool selection for SpOC4
  Challenge 2, application areas and a benchmark plan, with pinned source
  revisions. It reviews documentation and source, is prepared for the
  maintainer, and runs no benchmarks. Linked from the README, the reference
  index, the landing page and `llms.txt` (catalog key `comparison`).

### Changed

- P1: extracted admission, process supervision and the internal execution
  lifecycle from the runner CLI. Optimization-specific result validation and
  manifest generation stay in an adapter; scheduling locks, conservative
  reservations, job/worker/result contracts and existing CLI/MCP tools remain.
- Errors fetching the boot ID after a process spawn now run the same guarded
  cleanup as process-record write errors, so the spawned child is reaped.


- The landing page catalog and `docs/discovery` record fcmaes-rust 0.2.1
  (PyPI and crates.io, 23 October 2026) after installing it from both
  registries, and every registry version was rechecked that day.
- README badges as in fcmaes-rust: pure-Rust runner, crates.io, docs.rs, MCP over stdio,
  Linux, the ecosystem overview and the AI agent guide.
- The landing page catalog and `docs/discovery` record the October 2026
  releases after installing each package from its registry: fcmaes 2.1.0,
  fcmaes-rust/`fcmaes-core` 0.2.0, lp-ip-craft 0.29.0 and sqp-craft 0.17.0
  (PyPI and crates.io), and these crates 0.3.0. The LP-IP-craft, SQP-craft
  and optimization-jobs cards link their registry pages.

## [0.3.0] - 2026-10-22

The first release on crates.io: `cargo install optimization-runner --locked`
installs `optimization-run` and `optimization-mcp`, and worker crates can
depend on `optimization-job-api = "0.3"`. The solver workers still pin this
repository through git. Envelope `optimization.job/0.1`, result contract
`optimization.result/0.2` and worker protocol `optimization.worker/0.2` are
unchanged from 0.2.0.

### Added

Discovery (October 2026):

- An ecosystem landing page for the five repositories (`site/`), built and
  validated by `scripts/build_site.py` (standard library only, no network)
  into `target/site`. One catalog, `site/catalog.json`, feeds the project
  cards, the JSON-LD, `llms.txt` and the sitemap. The workflow
  `Ecosystem discovery site` builds a preview on every pull request and
  deploys to GitHub Pages only when Pages uses GitHub Actions and the
  repository variable `PUBLISH_ECOSYSTEM_SITE` is `true`.
- `docs/discovery/`: the publication checklist, a release-first plan,
  directory submission drafts (proposals, not listings) and a reference
  index that separates the one verified third-party integration (the
  OptunaHub fcmaes sampler) from maintainer evidence. An issue form collects
  independent evaluations.
- The README and both crate READMEs link the overview and the shared agent
  guide; both crates set `homepage`. The runner's README carries the MCP
  Registry ownership line `mcp-name: io.github.dietmarwo/optimization-jobs`
  for a future listing and installs from a source checkout.
- The README opens with a banner (`docs/images/optimization-jobs.png`).

Findings of the rereview of agent workflows (October 2026):

- `ai-context.md` (and the copy `get_guide` serves): the Pareto rows call
  scalarization results candidates (R5). They cover ε-constraint ties (with
  a counterexample), supported versus unsupported points of weighted sums,
  degenerate faces, first-order points of a scalarized NLP versus Pareto
  optimality, and the dominance filtering and per-point evidence to report.
- The shared harness checks that each worker's schema and the worker agree
  when an optional top-level payload field is `null`. SQP-craft's schemas
  rejected a `null` the worker accepts (R4). The guide states the
  convention.

Findings of the October 2026 review of agent discovery:

- `ai-context.md`, the entry point for AI agents, reworked:
  - The chooser asks for the wanted output (one solution, a Pareto front,
    diverse solutions) and the guarantee before the structure, so a smooth
    bi-objective problem is no longer routed to a single SQP solve (F07).
    Linear and smooth Pareto fronts can be computed as weighted-sum or
    ε-constraint series of LP or SQP solves.
  - A table routes requests outside the toolbox (QP/MIQP, conic, large
    sparse NLP, MINLP with proofs, combinatorial structure, ask/tell,
    stochastic simulation, several machines, pause and resume) (F14).
  - A checklist for passing points from fcmaes to SQP (F15).
  - What to do when no registered worker or model fits.
  - The scalar `feasible` claim checks the declared constraints only, not
    penalties inside the objective (F08).
  - A section on large machines: the host report, memory per task, one
    owner per level of parallelism, the width of each surface and
    candidate layouts for 64 slots (F05, F09).
  - The MCP-only workflow from `describe_worker` examples through
    `put_input` to `validate_job`, with `get_guide` and `put_input` in the
    tools table.
- `AGENTS.md`, a short entry point for coding agents (F06).
- MCP `put_input` (F02): an MCP-only client stores the input files of a job,
  such as a new LP model, as `content` (UTF-8 text), `content_base64` or
  `from_artifact` (a file of an existing job), in the node's
  content-addressed store `NODE/mcp/inputs/<sha256>`, and gets `file`,
  `sha256`, `bytes` and `input_dir` for the job. Stored inputs share the
  directory, so one job can use several. At most 64 MiB per input; the new
  option `--input-store-bytes` (1 GiB) bounds the store, with the new tool
  error `input_store_full`; a starting server removes files unused for 7
  days.
- MCP `get_guide`: `ai-context.md`, whole or one section by heading, for
  clients that cannot read the repository. The crate carries a copy
  (`crates/optimization-runner/guide/ai-context.md`, kept identical by a
  test). The server instructions send agents without a chosen solver or
  profile there first.
- `node doctor` reports the host (F04): online, affinity and usable CPUs,
  the cgroup CPU quota and memory limit (v1 or v2), physical cores, NUMA
  nodes, total, available and usable memory, with `null` for what is
  unavailable, and `warnings`, such as a capacity above the usable CPUs.
  `node init --capacity N` prints the same warning. MCP `describe_node`
  includes both.
- The discovery convention (F01): a worker's `describe` lists
  `payload_schemas` (a strict JSON Schema per profile), `input_schemas` and
  runnable `examples`, documented in the guide's "Discovery for agents".
  The shared harness checks it strictly for every real worker (F16):
  schemas and examples for every profile, examples and their inputs valid
  against them, every example a job that validates, runs and completes, and
  every payload of the shared scripts valid against its schema
  (`scripts/job-api/discovery.py`). `fake_worker.py` lists schemas and
  examples, so these checks and the MCP-only flow (`describe_worker`,
  `put_input`, `validate_job`, `submit_job`, `wait_job`, `get_result`) run
  without real workers; CI runs that flow for every profile of each real
  worker. The mixed-node CI job fails until the three workers list these
  keys on their `main`.

Earlier additions:

- Worker-declared artifacts (prerequisites of `fcmaes.surrogate/1`, #5):
  - `artifact::declare` lets a task declare extra files of its attempt, such
    as an evaluation log (`records`: checked records) or a warm-start
    snapshot (`json`: replaced atomically). Declarations are checked records
    in `artifacts.jsonl`, so workers in other languages can write them;
    runners without this change ignore the file, so declaring workers run on
    them.
  - `jobs get` lists the artifacts with format and size (`artifact_index`)
    while the job runs. `jobs artifact` reads them while the job runs too:
    whole up to 1 MiB, or with `--offset`/`--limit` a page of complete,
    checked records. New codes `unknown_artifact` and `artifact_too_large`.
  - The sealed manifest lists every declared file that exists in
    `artifacts`; `runner.artifact_index` records format, size, SHA-256, task
    and description (the result schema 0.2 describes it as an optional
    runner property), and a whole read after the end checks the file against
    it. Problems with declarations go to `runner.artifact_errors` and never
    fail a job.
  - MCP `get_artifact` takes `offset` and `limit`; `get_result` summaries
    include the artifact index. The guide documents how a later job takes an
    artifact as input (`input_dir` set to the earlier job's directory).
- `optimization-mcp`, an MCP server over stdio for one node, as a second
  binary of `optimization-runner`, so `cargo build -p optimization-runner`
  builds it in every worker repository (#2). Fifteen tools serve the guide,
  describe the node and its workers, store input files, validate, submit,
  wait for, cancel, kill and repair jobs, and read their events, artifacts
  and results (a summary by default). Each
  tool drives the `optimization-run` command line. The server is dual-era:
  MCP 2026-07-28 statelessly, with `server/discover` and the Tasks extension
  (`submit_job` returns a task that completes with the job's result, task
  notifications through `subscriptions/listen`), and 2025-11-25 to
  2024-11-05 after `initialize`. Jobs run in a session of their own (or as
  systemd user units with `--launch systemd`) and outlive the server; task
  IDs are stored in the node root and survive a restart. The server
  registers no workers and never changes the node.
- `ai-context.md` for agents that run optimization through the runner or the
  MCP server, and the guide's "Choosing a worker and profile" routing table
  (#5). It is now the entry point for any AI that wants to optimize
  something: choosing among fast-cma-es, fcmaes-rust, LP-IP-craft and
  SQP-craft, library or job, installation of each (registries and source),
  a node with all three workers, the job API from the shell, the MCP server,
  and pointers to the detailed documentation.
- The shared harness runs `fcmaes.surrogate/1` when the fcmaes worker offers
  it: claims and evidence, identical results for 2 and 4 inner threads, and,
  with a worker that declares its files, the log in pages and a warm start
  from the snapshot artifact (#5).
- `scripts/job-api/test_mcp.py` tests the MCP server. `fake_worker.py`: mode
  `complete` takes an optional delay (`seconds`); mode `artifacts` declares
  and writes artifacts.
- Release workflow `publish-crates.yml` and `RELEASING.md`: a `v*` tag that
  matches the crate version validates both crates and publishes them to
  crates.io through Trusted Publishing once the repository variable
  `CRATES_IO_TRUSTED_PUBLISHING` is `true`. The crates carry the metadata
  crates.io needs. The README describes installation from source.

### Changed

- crates.io and docs.rs pages: both crates' rustdoc front page is their
  README; `optimization-job-api` links its API documentation on docs.rs (the
  runner keeps the guide) and is categorized under science and mathematics
  instead of API bindings; rustdoc references to `docs/job-api.md` are
  links to the guide's sections.
- CI: the mixed node with this checkout's SDK re-resolves the workers'
  lockfile entries, so a version bump of the shared crates (0.3.0) is
  tested too; before, Cargo ignored a patch whose version differed from the
  locked one.
- `publish-crates.yml`: while Trusted Publishing is not enabled
  (`CRATES_IO_TRUSTED_PUBLISHING`), a tag publishes the two crates with the
  secret `CARGO_REGISTRY_TOKEN`, the API crate first and skipping versions
  already on crates.io, so the first release needs no local toolchain.
  `RELEASING.md` describes the token and its removal afterwards.
- The shared guide's installation section names the registry releases of
  October 2026 (fcmaes 2.1.0, fcmaes-rust and `fcmaes-core` 0.2.0,
  LP-IP-craft 0.29.0, SQP-craft 0.17.0, these crates 0.3.0), which contain
  the MODE fixes and the exact Pareto archives.
- `RELEASING.md`: the tag command reads the version from the runner's
  manifest instead of a hard-coded number, and a section covers discovery
  after a release.
- `workers add` accepts a `describe` output of up to 1 MiB (was 64 KiB): payload
  schemas and examples make it long.
- The shared job API moved here from fcmaes-rust, LP-IP-craft and SQP-craft,
  which carried identical copies (#1): `optimization-job-api` and
  `optimization-runner` 0.2.0 with their tests, the guide, the plan, the
  JSON Schemas and the shared scripts. No API, protocol or behavior change.
- The shared scripts take the runner and the workers from `JOB_API_TARGET`
  and the tutorial jobs from `JOB_API_TUTORIALS`, so worker repositories run
  them from Cargo's checkout of this repository.
- `artifact::page` streams the file once (#6): records before the page are
  only counted, and only the page's records are parsed and checked. On a
  99 MB trace of 150,000 records a page took 31 ms instead of 240 ms and
  3 MB instead of 108 MB of memory. A record counts once its line is
  complete; a whole envelope still missing its newline is no longer counted.
- CI: the mixed node also builds the three workers with their shared
  dependencies patched to this checkout (`sdk_source.py` checks which one was
  used), next to their pinned revisions, and runs weekly.

### Fixed

Findings of the October 2026 review (#4):

- Cancellation escalates only. `jobs cancel`, the launcher's timeout and its
  signal handler write `cancel.request` under `cancel.lock`; before, a
  graceful request that read the marker first could replace a concurrent
  immediate one (and the timeout marker a concurrent cancellation).
- `Outcome::check` rejects inconsistent objective bounds: `primal` must be
  the objective of the returned feasible point, and a `dual` bound must not
  lie beyond it by more than `BOUND_TOLERANCE` (relative 1e-6). New
  `ObjectiveBounds::ordered` and `objectives_agree` let workers decide the
  same way before they publish a bound. The shared outcome cases mark rules
  the JSON Schema cannot express with `schema_valid`.
- Legacy `fcmaes.job/0.1` validation caps population x dimension at 1e7
  (`legacy::MAX_POPULATION_CELLS`); before, a one-evaluation DE job with
  dimension 10000 and population 1000000 passed validation and would have
  allocated 80 GB per population table.
- `optimization-mcp` limits messages to 64 MiB, requests in flight to 64
  (32 of them waiting) and concurrent validations to 4, and copies the input
  files of an inline job only for an otherwise valid envelope.
- The process-inspecting tests map PIDs through `NSpid`, so they pass where
  /proc belongs to an enclosing PID namespace; CI runs them in one.

Earlier fixes:

- `process::bounded_command_until` kills the command's process group while
  the exited leader is still a zombie, so a reused PID can no longer make it
  kill an unrelated process group.
- The runner reads a job file once, so `submitted.json` always records the
  content it validated.
- Documentation: the runner's build also makes `optimization-mcp`, and the
  Markdown files agree with the code (#3).

## [0.2.0] - 2026-10-19

Developed in fcmaes-rust (#9) and synchronized into LP-IP-craft and
SQP-craft.

- Result contract `optimization.result/0.2`: each outcome separates
  `termination`, `claim` and `evidence` (`claimed`, `rechecked` with the
  recomputed `checks`, `certified`), with refutations (`evidence.refuted`
  and its verdict), objective bounds and the `infeasible`, `unbounded`,
  `infeasible_or_unbounded`, `locally_infeasible` and `certified_optimum`
  claims; 0.1 manifests stay readable.
- Worker protocol `optimization.worker/0.2`; the runner accepts 0.1 and 0.2
  workers, and a 0.1 runner rejects 0.2 workers at registration.
- Coded runner errors (`{"error":{"code","message","retryable"}}`) and JSON
  Schemas of the job envelope and the result manifest.
- See the [plan](docs/job-api/PLAN.md) for the history since 0.1.0.

## [0.1.1] - 2026-10-19

The three repositories' copies of the shared crates brought together
(fcmaes-rust #8): a worker that writes an invalid journal record no longer
leaves its job `running` (the attempt is sealed `failed` with
`runner.journal_error`); staging under the node root, so a `noexec` `TMPDIR`
works; a signal during validation stops the validator; an append after a
torn journal tail no longer destroys earlier records; finished jobs are not
flagged after a reboot; `./model.json` is a valid input path; and the repair
of a job whose launcher died while queued.

## [0.1.0] - 2026-10-18

The shared agent job API, first in fcmaes-rust (#5): the versioned
`optimization.job/0.1` envelope, the worker SDK, checked journals and input
hashing (`optimization-job-api`), and the runner `optimization-run`
(`optimization-runner`) with CPU-slot admission
(`outer_workers * inner_threads <= cpu_slots`), staging of hashed inputs and
the worker binary, idempotent request keys, cancellation, deadlines and
conservative recovery from lost processes.

Repository: https://github.com/dietmarwo/optimization-jobs
