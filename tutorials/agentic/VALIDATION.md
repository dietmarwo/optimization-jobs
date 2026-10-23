# Executed validation

The original five chapters and the three additional chapters have separate validation records below. The rail-traffic chapter has [its own record](rail-traffic/VALIDATION.md).

Validated on Linux with Rust/Cargo 1.90.0, Python 3.12.14, jsonschema 4.26.0 and matplotlib 3.10.8. Numerical campaigns use seed 42, two CPU slots and the documented pilot budgets. The container exposes eight usable CPUs (nine affinity CPUs); Cargo builds use four jobs with release LTO disabled and 16 codegen units. This is functional validation, not a timing benchmark. Rust 1.88 is the documented minimum but was not separately exercised here.

The checkouts were refreshed to these merged heads before implementation:

| Repository | Base revision |
|---|---|
| optimization-jobs | `248a55b1b79d01dce489446a1af78c9c0d823591` |
| fcmaes-rust | `540412f43c1ae1c86a1733f5ee7c351c3a36af2f` |
| LP-IP-craft | `dfb336c8c81be423ace58777c6efb85c84fddc0a` |
| SQP-craft | `b2c2c4322ad8df3d4b586888f18467100d674618` |
| fast-cma-es | `f599a13c9d48dea4eaf7f04c1f1cbaf5c7ba19a3` |

The tutorials were developed as patches on these revisions and merged into the five repositories afterwards; worker dependency pins remain unchanged. [pilot-summary.json](validation/pilot-summary.json) retains numerical findings, work counts and binary hashes. The complete specs, results and execution logs of these runs were reviewed when the tutorials were integrated but are not part of the repository; `run.py` regenerates the scripted campaign. Each chapter shows a measured example with limits on its interpretation.

## Program checks

| Check | Result |
|---|---|
| Four optional application workers and all reused binaries | Locked release builds pass |
| Application Rust suites, including 12 new adapter tests | 113 pass: trebuchet 14, production 13, energy 27, GTOC1 59 |
| Generic fcmaes worker suite | 49 pass |
| optimization-jobs Rust suite | 46 pass |
| Runner regression/schema suite | 24 pass |
| MCP regression suite, with real workers available | 36 pass |
| Clippy with warnings denied | Four application workspaces and optimization-jobs pass |
| Formatting and original default-feature builds | Pass |
| optimization-jobs rustdoc with warnings denied | Pass |
| Invalid driver settings, occupied output directory, invalid route | Five negative checks pass |
| Documentation inventory, relative links, static site | Pass |

Application parity tests compare native scalar, multi-objective and QD values, replayed seeds and training/holdout constraints. They reject bad/unused parameters; the trebuchet invalid-geometry check rejects the design, and the energy tests preserve native error penalties and QD feasibility gating. The suites do not independently validate physical models.

The final scripted campaign completed 25 jobs/40 result records. Every job and payload passed the published/worker JSON Schemas, every result passed the result schema, accounting was complete and numerical claims carried rechecked evidence. CSV residual losses, the SQP anchor and the one-hour LP were recomputed separately. Pilot work is retained by job; objective calls, validation calls, LP pivots and SQP iterations are different units.

## Integration re-run

When the series was merged (23 October 2026), `run.py build` and `run.py run --chapter all --cores 2` were executed again on the merged sources:
- toolchain: Rust/Cargo 1.97.0 and matplotlib 3.11.2;
- every number quoted in the five chapters reproduced bit for bit: trebuchet, production training and holdout throughput, energy baseline, search, holdout LCOE and LP, curve-fit losses, and both GTOC1 scores;
- the campaign again ran 25 jobs with 40 result records and the same 12,058 counted evaluations, with all schema, accounting and evidence checks passing.

The four application test suites with `--features job-worker` (113 tests) also passed; fcmaes-rust CI now runs them. The fresh-model trials below were not repeated.

## Fresh model trial

A fresh-context `gpt-6.1-sol` shell agent read the five prompt files and linked instructions, used prepared binaries, and completed all five chapters sequentially: 25 jobs/40 result records. It had no earlier results or implementation notes in its starting context. It inspected discovery, specs, outcome evidence, checksums, plots and replay files, and wrote a chronological log. This tests prompt usability with a shell agent, not a chat interface or clean-machine installation. It is one fresh starting context across five chapters, not five independently reset trials or a model-ranking study.

Its review found no blocking defect. It prompted a route-helper help improvement and additional load/emissions plots. Its initial production narrative confused registry defaults with executed parameters; auditing retained specs corrected the report to two replications and a 120-minute horizon. This illustrates why an agent's prose needs to be checked against recorded jobs. An energy error-sentinel correction from source review was covered by the native parity suite. The same model session repeated the revised trebuchet and energy prompts: 13 further jobs/16 result records passed, numerical outcomes and budgets matched the initial runs, and the added plots and route-helper help were checked. The error-sentinel path is covered by the Rust parity test, not by those normal-path campaigns. The trial transcripts and audit notes were reviewed during integration and are not published.

## Boundaries

These are executable adaptations of model definitions and experiment workflows. They do not reproduce original publication budgets, optimizer trajectories or statistical studies. Production's generic MODE uses rounded real encodings, GTOC1 uses generic BiteOpt retries instead of coordinated DE-CMA-ES, and energy retains microlp. Existing curve-fit examples are not a fair solver comparison. The LP-IP-craft, SQP-craft and fast-cma-es changes add documentation links; their numerical implementations are unchanged. Full Python binding suites and full publication campaigns were not run. Browser replay files were generated and inspected; browser interaction was not exercised.

## Surrogate, LP/IP and SQP extension

The three additional chapters were retested after the first five tutorials and their integration fixes were merged. The current source revisions, numerical summaries, binary hashes, work counts and follow-up results are published in [additional-pilot-summary.json](validation/additional-pilot-summary.json). These checks used current stable Rust/Cargo **1.99.1**, Python 3.12.14, jsonschema 4.26.0 and matplotlib 3.11.2 on Linux. They do not supersede or reattribute the original integration record above.

| Check | Result |
|---|---|
| Current stable Clippy, warnings denied, all targets of the three workers | Pass |
| fcmaes worker + surrogate Rust suites | 67 pass |
| LP/IP worker Rust suite | 12 pass |
| SQP worker Rust suite | 19 pass |
| Tutorial evidence-contract and analytic tests | 6 pass |
| Existing real surrogate MCP/cancellation integration suite | 2 pass |
| Stale snapshot hash, wrong model identity and invalid CLI settings | 9 rejection checks pass |
| New CI workflow | actionlint passes; each selected build/run tested locally with only optimization-jobs and its required solver checkout |
| Documentation | mdBook 0.5.4 builds; all internal links/anchors across 141 pages pass; native inventory and static site pass |
| Three default chapters, seed 42 and two slots | 14 completed jobs / 33 records |
| Four follow-ups: seeds 7/19, LP capacity 9, SQP dimension 8 | 19 completed jobs / 40 records |
| All eight chapters, shared-driver regression | 39 completed jobs / 73 records |

The selected builds use the native workspace release profiles; the all-chapter regression uses four Cargo jobs with LTO disabled and 16 codegen units. Both use the same current stable toolchain. The CI-style local runs use two build jobs and two numerical slots. GitHub-hosted Actions were not triggered as part of this validation; the new workflow runs these checks on pull requests, main and a weekly schedule.

Every campaign completed with full accounting and schema checks. All positive numerical claims carry rechecked evidence. Each deliberately impossible LP/IP job retains `infeasible` with `claimed` evidence: the worker exports no certificate. Its elementary cost contradiction is a separate check. Infeasible point evaluations correctly use `none`.

The numerical checks recompute Branin objectives and analytic oscillator losses, verify all surrogate artifacts and retained/new observation counts, enumerate the tiny binary decision model and its fractional bound, and recompute simplex/Rosenbrock objectives and stationarity. The eight-share follow-up's objective 0.125 was recorded before execution. All eight chapters' reported points, scalar objectives, feasibility flags and claims exactly matched the earlier implementation run; elapsed times are not compared.

The earlier fresh-context `gpt-6.1-sol` trial of these three prompts is historical usability evidence: 33 jobs/73 records for the requested runs, five further jobs/19 records after correcting a prediction-order lapse, and nine jobs/26 records after improving a plot and an integrality assertion. No model trial was repeated after the chapters were rebased onto the merged series. The earlier trial did not change numerical budgets or tolerances. Its complete transcript and execution logs are not published in the repository; the checked-in summaries and `run.py` provide the numerical examples and regeneration path.

When these chapters were merged (23 October 2026), the selected builds and runs were repeated with Rust/Cargo 1.97.0. The three default chapters and the four follow-ups (33 jobs / 73 records) matched the published summary in every numerical field; only timing fields differ (proposal and evaluation seconds, remaining time limits). An all-chapter run (39 jobs / 73 records) reproduced the first five chapters' quoted values unchanged.

The new GitHub Actions matrix builds each selected chapter with locked dependencies, runs worker/contract tests and the numerical campaign, and retains specs, results and figures. Rust diagnostic steps register the existing ecosystem problem matcher and explicitly disable color after the cache step. The existing optional-feature CI, shared test-helper lint fix, book entry and lockfile repairs from the first integration remain intact.

## Rail traffic

The rail-traffic chapter was added after the surrogate, LP/IP and SQP chapters merged. It reuses the LP/IP worker and adds an independent timetable checker and an exhaustive order oracle. Its campaigns, follow-ups, program checks and limits are recorded in [rail-traffic/VALIDATION.md](rail-traffic/VALIDATION.md) and [rail-traffic/validation.json](rail-traffic/validation.json).
