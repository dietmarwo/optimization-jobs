# External references and reproducible evaluations

This index separates distribution, integrations and evaluations. It does not
rank the five projects. Checked 2026-10-21; links and claims should be rechecked
when updating the page.

## Verified third-party integration

| Source | Attribution | What it supports | What it does not support |
| --- | --- | --- | --- |
| [OptunaHub: Optuna Wrapper for Fast CMA-ES](https://hub.optuna.org/samplers/fcmaes/) and [adapter source](https://github.com/optuna/optunahub-registry/tree/main/package/samplers/fcmaes) | The listing names Jacob Pfeil as author; it records Optuna 4.5.0 as its verified version and 2025-11-04 as its last update | A named outside author has integrated fcmaes CMA-ES with Optuna and published an example | No broad performance ranking, no validation of fcmaes-rust/LP-IP-craft/SQP-craft/optimization-jobs, and no claim that we reran that integration on newer dependencies |

This is an attributable third-party integration, not a claim that every
contributor relationship has been independently audited. No additional outside
evaluation is asserted for the other four repositories in this index. This is
not an exhaustive literature search or proof that none exists.

## Maintainer-provided evidence

The projects' own source, tests, benchmark harnesses and application tutorials
are useful starting points for reproduction. Their authorship stays explicit:

- [fast-cma-es performance tutorial](https://dietmarwo.github.io/fast-cma-es/tutorials/Performance.html).
- [fcmaes-rust benchmark sources](https://github.com/dietmarwo/fcmaes-rust/tree/main/benchmarks).
- [LP-IP-craft parallel reproduction guide](https://github.com/dietmarwo/LP-IP-craft/blob/main/docs/parallel-028/REPRODUCE.md).
- [SQP-craft benchmark results](https://github.com/dietmarwo/SQP-craft/blob/main/docs/benchmark-results.md).
- [optimization-jobs acceptance harness](https://github.com/dietmarwo/optimization-jobs/tree/main/scripts/job-api).

These links expose project evidence. Hosting it on GitHub or having an AI review
it does not make it an independently reproduced comparison. Registry entries
on PyPI/crates.io likewise show distribution, not comparative performance.

## Adding an independent reproduction

Use the [evaluation issue form](https://github.com/dietmarwo/optimization-jobs/issues/new?template=independent-evaluation.yml).
For a benchmark, include:

1. Problem/application, input provenance, exact revisions and author relationship.
2. Hardware, CPU allocation, compiler/OS, outer and inner parallelism, and
   thread limits in libraries such as BLAS.
3. Objective/constraint definitions, tolerances and independent correctness
   checks. Numerical termination and global-optimality proof are different.
4. The same evaluation or wall-time budget for each comparison, stated clearly;
   report total CPU effort too, especially when comparing parallel with serial.
5. Seeds, held-out cases, failures, raw results and reproduction commands.
6. Conclusions limited to the tested workloads and versions, with uncertainty.

Negative results are useful. Publish raw data before turning a result into a
headline. When adding a reference, identify whether it is an integration,
directory listing, application report or independently reproduced benchmark.
