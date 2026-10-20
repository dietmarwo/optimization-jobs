# Changelog

## Unreleased

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
