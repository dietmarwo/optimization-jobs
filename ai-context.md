# AI context for running optimization jobs through optimization-jobs

Last reviewed 2026-10-20 against `main` at `eb1c9de` (crates
`optimization-job-api` and `optimization-runner` 0.2.0, envelope
`optimization.job/0.1`, result contract `optimization.result/0.2`). In another
checkout, check `Cargo.toml`, `describe_node`/`describe_worker` output and the
[guide](docs/job-api.md) before relying on a command or capability.

This file is operational context for an AI that runs optimization for a user
through this repository's runner (`optimization-run`) or MCP server
(`optimization-mcp`). This repository contains no solver. It turns a problem
into a durable, budgeted job for one of the registered workers and reports
what the worker can support. Choosing the solver, modelling the problem and
reading the claim are the agent's job; each worker repository's
`ai-context.md` covers its solver in depth.

## What is where

| Part | Where |
| --- | --- |
| Envelope, resources, lifecycle, errors, results, MCP | [docs/job-api.md](docs/job-api.md) |
| JSON Schemas of job and result | [docs/job-api/schemas](docs/job-api/schemas/optimization.job-0.1.schema.json) |
| Runner CLI `optimization-run` and MCP server `optimization-mcp` | [crates/optimization-runner](crates/optimization-runner) |
| Worker SDK for new workers | [crates/optimization-job-api](crates/optimization-job-api) |
| fcmaes worker: black-box, multi-objective, quality-diversity, surrogate | [fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust), [ai-context](https://github.com/dietmarwo/fcmaes-rust/blob/main/ai-context.md) |
| LP/MIP worker | [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft), [ai-context](https://github.com/dietmarwo/LP-IP-craft/blob/main/ai-context.md) |
| Smooth NLP worker | [SQP-craft](https://github.com/dietmarwo/SQP-craft), [ai-context](https://github.com/dietmarwo/SQP-craft/blob/main/ai-context.md) |

The Python package `fcmaes` ([fast-cma-es](https://github.com/dietmarwo/fast-cma-es))
is a separate library with its own C++ backend; it has no worker for this API.

## Choosing a worker and profile

Use the table in
[Choosing a worker and profile](docs/job-api.md#choosing-a-worker-and-profile).
In short: linear models go to `lp-ip.solve/1`; smooth constrained models with
derivatives to `sqp.solve/1`; black-box scalar objectives with box bounds to
`fcmaes.retry/1`; expensive deterministic simulations with at most 256 calls
to the experimental `fcmaes.surrogate/1`; several objectives to
`fcmaes.mode/1`; diverse solution sets over behavior descriptors to
`fcmaes.map-elites/1`; and checks of given points to the `evaluate` profile
of the same worker. A profile can only run models its worker registered:
`describe_worker` lists them with their parameters, inputs and options.
Python callables or source code cannot be submitted.

## Workflow over MCP

The node owner initializes the node and registers workers with the CLI; the
MCP server cannot do either. Connect as described in
[Connect a client](docs/job-api.md#connect-a-client), then:

1. `describe_node`: capacity, launch mode and registered workers with their
   profiles. If the needed worker is missing, tell the user; do not improvise
   with another profile.
2. `describe_worker`: models, payload options with defaults, and claims.
3. Write the envelope: `schema_version`, a new `request_key` per experiment,
   `worker`, `payload_schema`, `payload`, `resources`, `limits`, and `inputs`
   with SHA-256 hashes for every file. Unknown fields are errors; copy field
   names from `describe_worker` and the worker's tutorial jobs.
4. `validate_job` until it returns the resolved job with its `task_count`.
5. `submit_job`; with the MCP Tasks extension the submission is a task.
6. `wait_job` (at most 600 s per call) or `get_job` until the job ends.
7. `get_result` for the summary, `tasks` or `full` for records,
   `get_artifact` for files the result names.
8. `cancel_job` keeps completed tasks; `kill_job` stops at once; `repair_job`
   finalizes a job whose launcher was lost.

The CLI equivalents print JSON with coded errors; see
[Run, inspect and stop](docs/job-api.md#run-inspect-and-stop).

## Resources and repeatability

- `outer_workers * inner_threads <= cpu_slots <= node capacity`. Outer workers
  run independent tasks; inner threads parallelize within one task where the
  profile supports it.
- `limits.wall_time_seconds` starts after CPU admission. At the deadline the
  workers stop cooperatively and the job ends `timed_out`; the wall time plus
  `grace_seconds` bounds the processes. Tasks committed before the stop stay
  in the result.
- The same `request_key` with the same content returns the existing job; with
  different content it is rejected (`request_key_conflict`). Use a new key for
  a new experiment.
- Inputs are copied only when their hash matches. Never edit a file and reuse
  its old hash.

## Reading a result

Report three things separately (see
[Termination, claim and evidence](docs/job-api.md#termination-claim-and-evidence)):

- `termination`: why a task stopped. It is never a claim.
- `claim`: what the worker asserts (`best_found`, `numerical_optimum`,
  `first_order`, `non_dominated_set`, `elite_archive`, `infeasible`, ...).
  None of the current workers certifies a global optimum; `certified_optimum`
  is never emitted yet.
- `evidence.level`: `claimed` (solver report only) or `rechecked` (points
  recomputed outside the solver, with `evidence.checks`). A refutation in
  `evidence.refuted` means an independent check rejected the solver's claim;
  `claim` then holds only what survived. Say so to the user.

Work counters (`work.evaluations` and friends) are per profile and must not be
added across profiles as if they measured the same work.

## Pitfalls

- Do not promise options a worker did not list; profiles reject unknown
  payload fields instead of ignoring them.
- Do not present `best_found` as a global optimum, `first_order` as a global
  or second-order optimum, or `numerical_optimum` as an exact certificate.
- A job that failed validation consumed nothing; a job that ran out of time
  can still carry useful completed tasks.
- Logs and artifacts live in the node's job directories; MCP returns at most
  1 MiB per call (`result_too_large` points to the files).
