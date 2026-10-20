# Changelog

## Unreleased

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
