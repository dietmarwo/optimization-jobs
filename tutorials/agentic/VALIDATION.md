# Executed validation

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

## Fresh model trial

A fresh-context `gpt-6.1-sol` shell agent read the five prompt files and linked instructions, used prepared binaries, and completed all five chapters sequentially: 25 jobs/40 result records. It had no earlier results or implementation notes in its starting context. It inspected discovery, specs, outcome evidence, checksums, plots and replay files, and wrote a chronological log. This tests prompt usability with a shell agent, not a chat interface or clean-machine installation. It is one fresh starting context across five chapters, not five independently reset trials or a model-ranking study.

Its review found no blocking defect. It prompted a route-helper help improvement and additional load/emissions plots. Its initial production narrative confused registry defaults with executed parameters; auditing retained specs corrected the report to two replications and a 120-minute horizon. This illustrates why an agent's prose needs to be checked against recorded jobs. An energy error-sentinel correction from source review was covered by the native parity suite. The same model session repeated the revised trebuchet and energy prompts: 13 further jobs/16 result records passed, numerical outcomes and budgets matched the initial runs, and the added plots and route-helper help were checked. The error-sentinel path is covered by the Rust parity test, not by those normal-path campaigns. The trial transcripts and audit notes were reviewed during integration and are not published.

## Boundaries

These are executable adaptations of model definitions and experiment workflows. They do not reproduce original publication budgets, optimizer trajectories or statistical studies. Production's generic MODE uses rounded real encodings, GTOC1 uses generic BiteOpt retries instead of coordinated DE-CMA-ES, and energy retains microlp. Existing curve-fit examples are not a fair solver comparison. LP-IP-craft, SQP-craft and fast-cma-es patches add relevant documentation links; their numerical implementations are unchanged. Full Python binding suites and full publication campaigns were not run. Browser replay files were generated and inspected; browser interaction was not exercised.
