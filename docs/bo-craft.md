# BO-craft and adaptive campaigns

[BO-craft](https://github.com/dietmarwo/BO-craft) is an experimental Python
package for Bayesian optimization proposals. It is not published to a package
index; install it from its repository. Its backends:

- BoTorch for noisy continuous problems, integer and categorical parameters
  (experimental), constraints, several objectives and scalar multifidelity;
- Optuna TPE for mixed and conditional spaces, and Optuna's GP sampler for
  unconditional ones (experimental);
- optional Vizier and read-only BO-MCP adapters.

Answers are the best observed point (empirical), the observed point a fitted
GP ranks best (model), or a labelled posterior prediction.

Its [capability matrix](https://github.com/dietmarwo/BO-craft/blob/main/docs/capabilities.md)
states which combinations are supported and tested.

The job layer is unchanged. BO-craft adds no worker, job profile, envelope
field or MCP tool:

- [experiment-craft](https://github.com/dietmarwo/experiment-craft)'s
  [adaptive campaigns](https://github.com/dietmarwo/experiment-craft/blob/main/docs/adaptive-bo.md)
  own the trial ledger and run each proposal as a trusted command job, with a
  CPU-slot reservation and a wall limit.
- Evaluations are command jobs, or one-point `fcmaes.evaluate/1` jobs for a
  registered scalar simulation. Independent replicates need distinct
  `run_seed` values.
- Command jobs are CLI-only: `optimization-mcp` refuses to submit them, so an
  agent drives these campaigns with `experiment-craft` and `optimization-run`
  commands.

Native results keep their claims and evidence. BO-craft's statistical
summaries and predicted recommendations are separate artifacts; a native
recheck of one seeded evaluation does not certify an expected value.

## Choosing a surrogate

| Problem | First choice | Measured |
|---|---|---|
| Deterministic continuous box, expensive | `fcmaes.surrogate/1` (or the experimental `/2`) | fcmaes-rust's comparison: Hartmann-6, 96 calls, median regret 5.0e-7 against 2.0e-2 for default BoTorch, at 0.33 s instead of 115 s of proposals per run |
| Many cheap evaluations, multimodal | BiteOpt or CMA-ES through the fcmaes worker | the same comparison: Styblinski–Tang-10, BiteOpt 16.7 against 56.7 (surrogate) and 87.8 (BoTorch) |
| Noisy objective | BO-craft BoTorch, with fresh validation replicates of the answer | the model answer was not reliably better than the empirical one on fresh seeds |
| Integer or categorical parameters | BO-craft Optuna TPE; a GP route when the noise is small | the GP routes were 2.4–73× better than TPE on three of four mixed strata, but not on noisy categorical Branin |
| Conditional parameters, unknown constraints, several objectives | BO-craft (TPE for conditional spaces, BoTorch otherwise) | supported; little evidence yet |

`fcmaes.surrogate/2` adds a larger archive, asynchronous callbacks and a
BiteOpt handoff (see fcmaes-rust's
[advanced surrogate guide](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/surrogate/ADVANCED.md)).
BO-craft's measurements are in its
[benchmarks of 17 November](https://github.com/dietmarwo/BO-craft/blob/main/docs/evidence/plan-2026-11-17/README.md).
In adaptive campaigns, `proposal_lookahead: 0` gave lower regret at 1.23× the
wall time in BO-craft's simulation; see experiment-craft's guide.
