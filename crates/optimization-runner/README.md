# optimization-runner

[Optimization ecosystem](https://dietmarwo.github.io/optimization-jobs/) ·
[Shared solver-selection and agent guide](https://github.com/dietmarwo/optimization-jobs/blob/main/ai-context.md)

Two binaries for versioned optimization jobs on one node:

- `optimization-run`: worker registration, staging of hashed inputs,
  idempotent request keys, CPU-slot admission
  (`outer_workers * inner_threads <= cpu_slots`), process supervision,
  cancellation, deadlines, journal recovery and coded errors.
- `optimization-mcp`: a Model Context Protocol server over stdio that gives
  agents the same jobs as tools and tasks.

Install on Linux with Rust 1.88 or newer, from crates.io or, for changes
after the latest release, from a source checkout:

```sh
cargo install optimization-runner --locked
# or: git clone https://github.com/dietmarwo/optimization-jobs && cd optimization-jobs \
#     && cargo install --path crates/optimization-runner --locked
optimization-run --root /tmp/node node init --capacity 8
optimization-run --root /tmp/node workers add --id fcmaes --executable /path/to/fcmaes-job-worker
optimization-run --root /tmp/node run --spec JOB.json
```

Built from `main` after 0.3.0, the runner also has `optimization-run node
capabilities`, which lists the execution kinds and schemas it supports (only
optimization jobs), and `optimization-run --root NODE jobs execution JOB_ID`,
which prints how a finished job's worker process ended and the hash of its
native result. The execution lifecycle behind them is internal, not a plugin
API.

Workers come from their own repositories:
[fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust),
[LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) and
[SQP-craft](https://github.com/dietmarwo/SQP-craft). The job contract is
[`optimization-job-api`](https://crates.io/crates/optimization-job-api).
See the [guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md).
Linux only. MIT license.

MCP Registry ownership token (prepared for a future listing):
`mcp-name: io.github.dietmarwo/optimization-jobs`.
The installed MCP executable is `optimization-mcp`, not the package name
`optimization-runner`. See the
[directory publication requirements](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/discovery/directory-submissions.md)
before creating registry launch metadata.

## Trusted local commands and binary files

Source after 0.3.0 supports opt-in `execution.command/0.1` jobs and verified
binary transfers on the same local admission budget. Commands are trusted
programs under the runner user, not a sandbox. Read the
[command and file guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#trusted-local-command-jobs-and-binary-files)
for `node commands --enable`, request/result schemas, transfer limits and the
build–run–collect example. MCP submission remains optimization-only.

## Explicit remote execution

Source after 0.3.0 adds `fleet nodes add/probe`, `fleet submit --node`,
`fleet reconcile/resume/cancel/repair` and verified terminal `fleet collect`.
A fixed SSH helper, pinned node identity and persisted dispatch/launch intent
keep uncertain work on the selected node. Remote launch requires a responding
systemd user manager and lingering. Read the
[SSH guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#explicit-ssh-placement-and-recovery)
for provisioning, bounded transfers, recovery rules and validation limits.
