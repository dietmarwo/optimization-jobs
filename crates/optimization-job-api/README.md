# optimization-job-api

Versioned optimization jobs for agents and people: the job envelope
`optimization.job/0.1`, the result contract `optimization.result/0.2` with
claims and evidence, checked journals, input hashing, worker-declared
artifacts and the worker SDK (`worker::run`, `Worker`, `Prepared`).

A worker implements `Worker::prepare` and returns a `Prepared` task set; the
SDK owns concurrency, journal commits and the final manifest. The runner
[`optimization-runner`](https://crates.io/crates/optimization-runner)
(`optimization-run`, `optimization-mcp`) schedules registered workers on one
CPU budget.

Workers built on this crate: the fcmaes worker in
[fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust), the LP/MIP worker in
[LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) and the NLP worker in
[SQP-craft](https://github.com/dietmarwo/SQP-craft).

See the [guide](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md)
and the [JSON Schemas](https://github.com/dietmarwo/optimization-jobs/tree/main/docs/job-api/schemas).
Linux only for process supervision. MIT license.
