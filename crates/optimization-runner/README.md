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

The P1 source iteration also provides `optimization-run node capabilities`
and `optimization-run --root NODE jobs execution JOB_ID`. Capability discovery
advertises only optimization; the neutral terminal record references the
native result without interpreting mathematical claims. The internal adapter
boundary is private. Command jobs and fleet execution remain future work;
these additions are not in the published 0.3.0 binaries.

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
