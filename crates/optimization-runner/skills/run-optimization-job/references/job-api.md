## 5. The job API

A job is a JSON envelope. Its life runs like this:

1. The selected worker validates it and resolves its defaults.
2. The runner admits it against the node's CPU slots.
3. It runs as independent tasks, each committing a checked record to a
   journal.
4. It is sealed as a result manifest whose outcomes separate why a task
   stopped, what the worker claims and what was rechecked.
5. The job directory stays the durable record.

The guide [docs/job-api.md](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md) is the reference, and the JSON
Schemas describe
[the job](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api/schemas/optimization.job-0.1.schema.json) and
[the result](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api/schemas/optimization.result-0.2.schema.json).

### Envelope

The LP tutorial job: two tasks solve the model in `continuous-lp-model.json`,
which lies next to the job file.

```json
{
  "schema_version": "optimization.job/0.1",
  "request_key": "my-project.lp.v1",
  "worker": "lp-ip",
  "payload_schema": "lp-ip.solve/1",
  "resources": {"cpu_slots": 2, "outer_workers": 2, "inner_threads": 1},
  "limits": {"wall_time_seconds": 30.0, "grace_seconds": 1.0},
  "inputs": [{"name": "model", "file": "continuous-lp-model.json",
              "sha256": "5679c7093f7672b3e4f5185d0558d40c444bbd3e589e738150120f1a7dd2a5b5"}],
  "payload": {"model_input": "model", "starts": [null, null],
              "node_limit": 10000, "iteration_limit": 100000,
              "feasibility_tolerance": 1e-07, "integrality_tolerance": 1e-07,
              "presolve": true}
}
```

| Field | Rule |
| --- | --- |
| `request_key` | 1–200 bytes, chosen by the caller. The same key with the same content and the same worker binary returns the existing job and never starts a second one. A different content, or a rebuilt and re-registered worker, gives `request_key_conflict`. Use a new key per experiment |
| `worker`, `payload_schema` | A registered worker ID and one of its profiles |
| `payload` | Strict and profile-specific: unknown fields are errors. Copy field names from `describe_worker` / `problems describe` and the tutorial jobs |
| `resources` | `outer_workers * inner_threads <= cpu_slots <= node capacity`. Outer workers run independent tasks; inner threads parallelize inside one task where the profile allows (`8/8/1` for eight runs, `8/1/8` for one large LP or SQP solve) |
| `limits` | Wall time starts after CPU admission. At the deadline the job ends `timed_out`, and its committed tasks stay in the result |
| `inputs` | Files relative to the job file, each with its SHA-256; at most 16 files of 64 MiB each. Never edit a file and keep its old hash |

The worker repositories' tutorials have complete jobs for every profile
([fcmaes](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/job-api),
[LP-IP](https://github.com/dietmarwo/LP-IP-craft/tree/main/tutorials/job-api),
[SQP](https://github.com/dietmarwo/SQP-craft/tree/main/tutorials/job-api);
the surrogate jobs are in fcmaes-rust's
[tutorials/surrogate](https://github.com/dietmarwo/fcmaes-rust/tree/main/tutorials/surrogate)).
The LP model format (`lp-ip.model/1`: sparse CSR, `null` for infinite bounds)
is described in LP-IP-craft's
[ai-context](https://github.com/dietmarwo/LP-IP-craft/blob/main/ai-context.md#job-specification).

### From the shell

Every command prints JSON. A runner error exits with status 2 and prints one
line on stderr: `{"error":{"code":...,"message":...,"retryable":...}}`.

```sh
job() { "$RUN" --root "$NODE" "$@"; }    # RUN and NODE as above
job problems describe lp-ip              # profiles, models, options, claims, resource limits
job validate --spec job.json             # the resolved job with task_count; runs nothing
job run --spec job.json                  # blocks until the end, prints the final job
job jobs list                            # every job (by id, not by time), with id, state, directory, artifact_index
job jobs get JOB_ID                      # state and progress
job jobs execution JOB_ID                # how the worker process ended (from 0.4.0)
job jobs wait JOB_ID --timeout 60        # returns at the end or after the timeout
job result JOB_DIRECTORY                 # the result manifest
job jobs artifact JOB_ID results --offset 0 --limit 100   # a page of checked records
job jobs cancel JOB_ID                   # graceful; add --now to stop at once
job jobs repair JOB_ID                   # finalize a job whose launcher was lost
```

To keep a long job from blocking, start `run` in a session of its own, as
the MCP server does, and follow it with `jobs get` or `jobs wait`:

```sh
setsid "$RUN" --root "$NODE" run --spec job.json > job.out 2>&1 &
```

Repeating `run` with the same key prints that job's current state and starts
nothing. `submit` instead launches a systemd user unit (`node doctor` tells
whether one is available). Lifecycle states:

- `submitted`, `starting`, `waiting` (for CPU slots), `running`;
- then `completed`, `cancelled`, `timed_out`, `failed` or `interrupted`.

`completed` means the tasks returned normally, not that the solution is
optimal; read the outcomes.

From 0.4.0 the runner also keeps an execution record of
each finished job (`jobs execution JOB_ID`, `execution.record/0.1`): the
worker's exit code or signal, the stop reason, whether its process group is
verifiably stopped, and the size and SHA-256 of `run.json`. It holds no
claim, objective or work; report those from the result manifest. A job that
has not finished returns `attempt_active` (wait, then ask again); one finished
by an older runner returns `execution_unavailable`.
`node capabilities` (and `capabilities` in `node doctor` and MCP
`describe_node`) returns `execution.capabilities/0.3`: optimization jobs and
opt-in trusted local commands, enabled kinds, binary file transfer limits and
CLI-only command/file interfaces. Commands use `execution.command/0.1` with
literal argv, explicit environment, hashed inputs, declared bounded outputs and
no automatic replay; enable with `node commands --enable`. Use `files put/get`
and `jobs collect` for binary transfer. A command may declare a `progress`
file of JSON lines that `jobs progress JOB_ID` reads while it runs (runner
0.5.0 or later); it is an observation channel, not a sealed output. Their separate `command-result.json`
records process/output facts, never mathematical claims. MCP submission and
result summaries remain optimization-only. Commands share admission/cancellation
but are not a sandbox or kernel resource limits
([guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#execution-discovery-and-terminal-observations)).
On a coordinator, `fleet nodes add` pins an SSH node's endpoint and identity,
`fleet submit --node NAME --spec FILE` places one optimization or command job
there, and `fleet reconcile`, `cancel`, `repair` and `collect` follow it. A
fixed helper receives every request as JSON on stdin, and remote launch
requires a systemd user manager with lingering. Staging can resume, but an
uncertain start is never moved or started again. Placement is explicit and
CLI-only, not available over MCP; real-host service, logout and reboot
behavior must be commissioned by the node's owner
([SSH guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#explicit-ssh-placement-and-recovery)).

### Results, claims and evidence

Each task outcome in the manifest's `results` reports three things. Report
them to the user separately
([guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#termination-claim-and-evidence)):

- **`termination`:** why the task stopped, such as `evaluation_limit`,
  `time_limit`, `optimizer_stop`, `cancelled`, or a solver status like
  `optimal` or `converged`. It is never a claim.
- **`claim`:** what the worker asserts: `none`, `feasible`, `best_found`,
  `numerical_optimum`, `first_order`, `non_dominated_set`, `elite_archive`,
  `infeasible`, `unbounded`, `infeasible_or_unbounded` or
  `locally_infeasible`. No current worker emits `certified_optimum`.
- **`evidence.level`:** either `claimed` (the solver's report only) or
  `rechecked` (recomputed outside the solver, with the checks listed in
  `evidence.checks`). `evidence.refuted` means an independent check rejected
  the solver's claim; `claim` then holds only what survived. Tell the user.

`feasible` means feasible for the constraints the model declares. A scalar
fcmaes model declares only its bounds, so constraints written as penalties
inside its objective are not checked: a low-penalty point can be reported
`feasible` and still violate them. Keep the raw constraint values, and check
them yourself, or evaluate the point with a model that declares them (a
multi-objective fcmaes model with constraints, an LP, an SQP model).

`objective_bounds` holds the primal objective and, where one exists, a dual
bound. `work` counts evaluations, nodes, iterations or callbacks per profile.
Never add work counters across profiles as if they measured the same thing.

Besides the `results` journal, a worker can declare artifacts such as an
evaluation log or a warm-start snapshot. They are listed in `artifact_index`
(`jobs get`, `jobs list`, the result) and can be read while the job runs.
`records` artifacts are read in pages; continue at `next_offset` while it is
below `available`. A later job takes an artifact as an input: its `file`,
with the SHA-256 from `runner.artifact_index` of the sealed result (`jobs
get` lists no hashes). Over MCP, pass the earlier job's `directory` as
`input_dir`; with the CLI, copy the file next to the new job file. Jobs are
never resumed in place.
