# Changelog

## Unreleased

Fixes from the October 2026 review:

- Cancellation escalates only. `jobs cancel`, the launcher's timeout and its
  signal handler write `cancel.request` under `cancel.lock`; before, a graceful
  request that read the marker first could replace a concurrent immediate one
  (and the timeout marker a concurrent cancellation).
- `Outcome::check` rejects inconsistent objective bounds: `primal` must be the
  objective of the returned feasible point, and a `dual` bound must not lie
  beyond it by more than `BOUND_TOLERANCE` (relative 1e-6). New
  `ObjectiveBounds::ordered` and `objectives_agree` let workers decide the same
  way before they publish a bound. The shared outcome cases mark rules the
  JSON Schema cannot express with `schema_valid`.
- Legacy `fcmaes.job/0.1` validation caps population x dimension at 1e7
  (`legacy::MAX_POPULATION_CELLS`); before, a one-evaluation DE job with
  dimension 10000 and population 1000000 passed validation and would have
  allocated 80 GB per population table.
- `optimization-mcp` limits messages to 64 MiB, requests in flight to 64 (32
  of them waiting) and concurrent validations to 4, and copies the input files
  of an inline job only for an otherwise valid envelope.
- The process-inspecting tests map PIDs through `NSpid`, so they pass where
  /proc belongs to an enclosing PID namespace; CI runs them in one.
- CI: the mixed node also builds the three workers with their shared
  dependencies patched to this checkout (`sdk_source.py` checks which one was
  used), next to their pinned revisions, and runs weekly.

- `optimization-mcp`, an MCP server over stdio for one node, as a second
  binary of `optimization-runner`, so `cargo build -p optimization-runner`
  builds it in every worker repository. Thirteen tools describe the node and
  its workers, validate, submit, wait for, cancel, kill and repair jobs, and
  read their events, artifacts and results (a summary by default). Each tool
  drives the `optimization-run` command line. The server is dual-era: MCP
  2026-07-28 statelessly, with `server/discover` and the Tasks extension
  (`submit_job` returns a task that completes with the job's result, task
  notifications through `subscriptions/listen`), and 2025-11-25 to 2024-11-05
  after `initialize`. Jobs run in a session of their own (or as systemd user
  units with `--launch systemd`) and outlive the server; task IDs are stored
  in the node root and survive a restart. The server registers no workers and
  never changes the node. `scripts/job-api/test_mcp.py` tests it.
- `process::bounded_command_until` kills the command's process group while
  the exited leader is still a zombie, so a reused PID can no longer make it
  kill an unrelated process group.
- The runner reads a job file once, so `submitted.json` always records the
  content it validated.
- `fake_worker.py`: mode `complete` takes an optional delay (`seconds`).
- The shared job API moved here from fcmaes-rust, LP-IP-craft and SQP-craft,
  which carried identical copies: `optimization-job-api` and
  `optimization-runner` 0.2.0 with their tests, the guide, the plan, the JSON
  Schemas and the shared scripts. No API, protocol or behavior change. Worker
  repositories depend on the crates through git at a pinned revision.
- The shared scripts take the runner and the workers from `JOB_API_TARGET`
  and the tutorial jobs from `JOB_API_TUTORIALS`, so worker repositories run
  them from Cargo's checkout of this repository.

## 0.2.0 (October 2026)

Result contract 0.2 (evidence, refutations, objective bounds, infeasibility
and certified claims), worker protocol 0.2, coded runner errors and the JSON
Schemas of the job envelope and the result manifest; see the
[plan](docs/job-api/PLAN.md) for the history since 0.1.0.
