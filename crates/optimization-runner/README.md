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

Install from a source checkout (Linux, Rust 1.88 or newer):

```sh
git clone https://github.com/dietmarwo/optimization-jobs
cd optimization-jobs
cargo install --path crates/optimization-runner --locked
optimization-run --root /tmp/node node init --capacity 8
optimization-run --root /tmp/node workers add --id fcmaes --executable /path/to/fcmaes-job-worker
optimization-run --root /tmp/node run --spec JOB.json
```

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
