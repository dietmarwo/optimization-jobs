# Review and implementation decisions — revision 2

**29 October 2026. Scope: all twenty chapters (the original four plus sixteen extensions).**

The mathematical catalogue is sound and provides useful independent checks. The implementation keeps all twenty lessons and changes the execution architecture to reuse the direct Python APIs backed by native Rust solvers. The companion revised plan retains the original chapter cards as mathematical specifications and extended exercises; this review supersedes their proposed worker/ownership and experiment details where stated here.

## Accepted design changes

1. **Use direct solver APIs for the canonical teaching models.** LP models use the existing native Rust engine and expose duals; SQP models supply checked derivatives to the existing Rust SQP. The numerical definitions stay in their owning repositories. There is no new generic expression evaluator or callback serialization protocol.
2. **Use existing trusted command jobs for orchestration.** A shared Python CLI driver runs every chapter directly or as a checked command; experiment-craft composes these commands and consumes their sealed artifacts. These are CLI command workflows, not new MCP model profiles. The originally proposed per-model registered Rust workers and diagnostic payload extensions are unnecessary for this teaching implementation and are removed from the implementation scope.
3. **Preserve existing scientific-comparison semantics.** The campaign adds four stock-worker jobs in two supported groups: LP presolve and SQP backend. Application, formulation, mesh and cross-solver comparisons stay descriptive.
4. **Correct the brachistochrone initial-control statement.** At zero speed, theta still affects acceleration through g*cos(theta). It is not an irrelevant/unidentifiable first control under the stated equations.
5. **Correct the hanging-chain limit.** 128 is the largest power-of-two mesh under the limit; 129 links use exactly 256 variables and are also admissible.
6. **Treat zero-throttle coasts as an observed numerical issue.** Retain the original failed coast-permitting attempt. Solve and independently replay a separate model imposing throttle norm at least 0.02. Do not present the latter as the identical physical formulation or silently regularize the original Jacobian.
7. **Report actual Thomson work.** The arms have common requested callback caps; convergence and invalid candidates consume different pair counts. Counts are measured and retained. Compare only checked sphere points: keep raw infeasible attempts, explicitly normalize any reported fallback, and never transfer a first-order claim through that projection. Classify curvature only at an independently checked first-order point. The study therefore is not labelled an equal-consumed-work performance comparison.
8. **Keep truss bound scopes explicit.** Recompute the yield-only bound for both nominal and moved geometry. The continuous section family fixes inner/outer diameter ratio to 0.8; catalogue designs are separately rechecked. Safe binary64 dual certificates use the declared largest-section area cap and corresponding force caps; their scope is the bounded model. The original Rust FEM is the independent catalogue replay for the published and rounded designs.
9. **Distinguish derivative consistency from physical accuracy.** A consistently discretized coarse ODE can pass derivative checking. Deliberately mixing coarse derivatives with fine function values is an inconsistency probe; integration refinement and closed-form replay assess fidelity separately.
10. **Preserve missing bounds and failures.** Full-table SpOC smoke runs can end at a time limit with no native bound. The native field stays null; a separately checked dyadic resource bound supplies independent context.
11. **Correct the propagator attribution.** Fixed Sims–Flanagan legs use Lagrangian Kepler drifts and analytic state-transition Jacobians. The independent replay uses SciPy DOP853. The original plan generalized ZOH/ODE propagation paths incorrectly.

12. **Freeze executable presets and separate exercises.** Every chapter has a smoke and study entry; where no larger fixture is declared, study repeats the same canonical teaching case. X4 smoke uses 12 charges and study 60; 32 is an additional exercise. SQP6 includes seeded noisy fitting, disjoint held-out times, exact symmetry/equal-rate tests and a coarse/fine derivative-consistency probe. One primary PNG/SVG figure per run is required; the original cards’ extra figures and optional variants remain follow-up exercises.

## Repository ownership and deliverables

| Repository | Implementation |
|---|---|
| LP-IP-craft | LP1–LP9, named model/checking helpers, tutorial index |
| SQP-craft | SQP1–SQP6 and X2, direct models/derivatives, replay and KKT helpers |
| optimization-jobs | LP10 and X1, twenty-chapter driver/catalogue, prompts, figures and adversarial tests |
| fcmaes-rust | X3/X4 workshops and a small original-FEM catalogue replay executable |
| experiment-craft | Twenty application commands, a dependent artifact checker and four supported native comparison jobs |

The complete source is delivered as repository patches. Reproduction records pin numerical distributions (LP-IP 0.29.0, SQP 0.17.0, fcmaes-rust 0.2.1 and pykep-rust 0.1.4), source revisions, actual outcomes and validation limits. Source-built stock binaries supply the job/campaign acceptance checks. The baseline lock continues to name merged upstream commits; unmerged patches are not disguised as a new released baseline.

## Acceptance and follow-up

Every chapter has a runnable entry, a mathematical reference, independent checks, a prompt/follow-up, retained smoke and study output and a primary generated figure. Study presets are recorded separately, including full matching-II, the 128-link chain, the 60-interval orbit transcription, the 40-segment rendezvous and the 60-charge sphere case. Original formulations' unsuccessful attempts are kept beside explicitly declared successful alternatives. Exact references do not strengthen a native numerical claim automatically.

Home-machine commissioning, hardware scaling and inaccessible private application data remain deferred until January 2027. External fresh-context LLM trials are distinct from executed software/prompt-driver tests and must be labelled according to what was actually run. Larger domain exercises remain exercises, rather than being silently claimed as measured studies.

## Exercises beyond this implementation

All twenty core lessons are implemented. The following extensions from the original cards remain explicitly labeled exercises: additional Sudoku rule sets; part-time staffing; incremental disaggregation and custom big-M mutations; additional cutting-stock datasets; chain arch/continuation variants; expanded control/trajectory figures; departure-date and cut-location sweeps; extra AC starts/networks; and the truss virtual-displacement plot. The campaign demonstrates checked command dependencies and supported native comparisons, rather than the original per-wave mesh/scenario pipeline designs. Fresh external-model usability trials are not software execution tests and remain unrun.
