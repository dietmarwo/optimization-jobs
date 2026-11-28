## Pitfalls

- Do not promise options a worker did not list; profiles reject unknown
  payload fields instead of ignoring them.
- Do not present `best_found` as a global optimum, `first_order` as a global
  or second-order optimum, or `numerical_optimum` as an exact certificate.
- Python's `lp_ip_craft.solve` defaults to `backend="dummy"` and
  `sqp_craft.solve` to `method="dummy"`. Both only evaluate one point, so
  pass `backend="native"` and `method="sqp"`.
- A job that failed validation consumed nothing. A job that ran out of time
  can still carry useful completed tasks.
- Separate roots have separate CPU budgets. Use the same absolute root for
  every job that shares a machine.
- `interrupted` (a lost launcher or host) can be run again with a new
  request key. For a `failed` job, read `runner.journal_error`, the worker's
  `stderr.log` or the runner's message before retrying.
