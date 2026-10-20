# Changelog

All notable changes to `optimization-job-api` and `optimization-runner`
(`optimization-run`, `optimization-mcp`) are documented here. Both crates
share one version. Until 0.2.0 the crates lived in fcmaes-rust, LP-IP-craft
and SQP-craft; worker repositories depend on them through git at a pinned
revision. No version has been published to crates.io yet.

## [Unreleased]

### Added

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
  builds it in every worker repository (#2). Thirteen tools describe the node
  and its workers, validate, submit, wait for, cancel, kill and repair jobs,
  and read their events, artifacts and results (a summary by default). Each
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
