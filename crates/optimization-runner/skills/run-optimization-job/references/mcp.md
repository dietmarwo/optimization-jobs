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

Protocol support is MCP 2026-07-28 through `server/discover` and
per-request metadata, and 2025-11-25 back to 2024-11-05 after `initialize`.
Every revision offers tools. The July revision also offers Tasks and lets
clients discover workflows for solver selection, job execution and result
interpretation with `skills/list`.

Trust: the server cannot register workers, change the node or run code.
`put_input` stores data, never code. Every connected client acts for the
node's owner, so connect only trusted clients.

The guide's [Agents and MCP](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#agents-and-mcp) covers tasks,
durability and error codes.
