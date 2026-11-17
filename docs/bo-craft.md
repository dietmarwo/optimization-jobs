# BO-craft and adaptive campaigns

[BO-craft](https://github.com/dietmarwo/BO-craft) is an experimental Python
package for Bayesian optimization proposals. It is not published to a package
index; install it from its repository. Its backends:

- BoTorch for noisy continuous, constrained, multiobjective and scalar
  multifidelity problems;
- Optuna TPE for mixed and conditional spaces;
- optional Vizier and read-only BO-MCP adapters.

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

Choosing between the surrogates: `fcmaes.surrogate/1` is the lightweight
default for deterministic boxes, and the experimental `fcmaes.surrogate/2`
adds a larger archive, asynchronous callbacks and a BiteOpt handoff (see
fcmaes-rust's
[advanced surrogate guide](https://github.com/dietmarwo/fcmaes-rust/blob/main/docs/surrogate/ADVANCED.md)).
BO-craft is for noise, mixed or conditional spaces, constraints and multiple
objectives.
