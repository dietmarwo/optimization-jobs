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
