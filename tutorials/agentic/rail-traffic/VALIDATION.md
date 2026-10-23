# Executed rail tutorial checks

Executed 23 October 2026 on Linux with current stable Rust/Cargo 1.99.1, Python 3.12.14, jsonschema 4.26.0 and matplotlib 3.11.2. The source defaults were fetched after the preceding three tutorials merged. Exact revisions and binary hashes are in [validation.json](validation.json). Native numerical code and dependency pins are unchanged.

The selected `build --chapter rail-traffic` built the runner, MCP executable and LP/IP worker with `--locked`, two Cargo jobs and native release profiles. The source directory contained only optimization-jobs and LP-IP-craft. Numerical jobs used two CPU slots, two outer tasks where a baseline warm start was feasible, and one inner thread per task. Limits were 300 seconds per job, 10,000 MIP nodes and 100,000 simplex iterations per task; both tolerances stayed at 1e-7.

## Campaigns

| Scenario | FCFS | Weighted | Cap 10 | Cap 8 | Preserve queues, cap 10 |
|---|---:|---:|---:|---:|---:|
| Default | 7,950 | 7,050 | 7,200 | 9,840 | 7,950 |
| RB202 passengers 90 to 180 | 8,400 | 7,560 | 8,100 | 10,560 | 8,400 |
| ICE101 passengers 420 to 210 | 5,850 | 4,500 | 5,100 | 8,160 | 5,850 |

Values are passenger-minutes, rounded for display. Each scenario completed seven jobs with 13 result records, for **21 jobs / 39 records** in total. Each included four cold/warm MIP comparisons, an evaluation job, a continuous relaxation and a five-extra-minute stress solve. All feasible MIP tasks matched the independent exhaustive optimum and had rechecked `numerical_optimum` claims with consistent bounds. The conflicting evaluation point retained claim `none`. The deliberately impossible stress solve retained `infeasible` / `claimed`; it exports no certificate.

The independent checker validated releases, horizon, exclusive occupancy plus clearance, caps, queue precedence and recomputed objectives. Every oracle visited all 720 orders; it does not reuse the MIP matrix. All held-fixed stress sequences were replayed for the preselected extra delays 0, 2 and 5. These are deterministic cases, not a probabilistic robustness estimate.

## Integration re-run

When the chapter was integrated (23 October 2026), `run.py build --chapter rail-traffic` and all three campaigns were executed again with Rust/Cargo 1.97.0 and matplotlib 3.11.2:
- the default fixture and both passenger-count follow-ups again completed 21 jobs with 39 result records;
- every claim, objective, bound, solution vector, node and simplex-iteration count, oracle result and stress replay equals [validation.json](validation.json); only the remaining job time passed to the worker (`time_limit_seconds`) differs, because it reflects elapsed setup time;
- the three figures are byte-identical to those beside this page;
- the six rail tests and the six evidence-contract tests pass, and the existing LP/IP chapter (four jobs, seven records) still runs through the shared driver with unchanged numerical results.

## Program checks and limits

- Six formulation/checker tests pass, including comparison of all 720 orders under four policies, infeasibility, stress propagation and seven malformed-input cases.
- The existing six series evidence-contract tests pass.
- CI syntax, changed-document links and the documentation-site build are checked for this addition. The new workflow entry runs the rail tests and real campaign with current stable Rust and locked builds.
- Published scenario, objective, tolerances and budgets were not tuned after seeing the results. Both prescribed passenger-count follow-ups were retained.

The local shell agent implemented and executed these experiments. No separate fresh-context model trial was performed. GitHub-hosted Actions were not triggered. Numerical consistency and small-model optimality do not validate the railway abstraction or establish production scale. Figures are generated from these runs; no copied publication result is presented as a new execution.
