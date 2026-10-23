# Optimization through prompts

These five tutorials let an agent execute maintained numerical models, validate the results and return decisions and figures. The reader supplies prompts; the original Rust tutorials remain the numerical references.

| Chapter | Question | Main lesson |
|---|---|---|
| [Trebuchet](trebuchet/README.md) | How should this mechanism throw to a target? | One solution, Pareto front, diverse trajectories |
| [Production line](production/README.md) | Which operating policies remain good under new random events? | Fixed seeds and disjoint holdout |
| [Energy hub](energy/README.md) | Which capacities balance cost, service and emissions? | Outer search, inner LP and explicit constraints |
| [Curve fitting](curve-fit/README.md) | What does each solver verify about this fit? | Best-found versus first-order/KKT evidence |
| [GTOC1 routes](gtoc1/README.md) | Which planet orders deserve further work? | Agent proposals, native scoring and bounded claims |

Start with [SETUP.md](SETUP.md), then paste a chapter's `prompt.md`. Each chapter has a follow-up prompt that changes or examines the experiment. [VALIDATION.md](VALIDATION.md) separates program tests, executed pilot campaigns and fresh model trials.

## Execution contract

- Read the shared [solver-selection guide](../../ai-context.md) and the selected worker's discovery. These workers are source-only, optional tutorial builds.
- Reuse native objectives. Do not replace them with a simplified Python simulator. Numerical evaluations stay inside the worker; prompts operate at experiment level.
- The default campaign uses two slots, fixed seeds and small budgets. Hardware quotas, not advertised machine size, determine available capacity. Builds may take longer than the numerical pilots.
- Record requested and actual work. A completed job need not have a feasible or converged solution. No current worker reports `certified_optimum`.
- An MCP client can use workers already registered by the node owner. Installing/building/registering workers needs a shell. The prompts are provider independent; no Sol-specific API or paid model key is required for numerical execution.
- Job records survive loss of an MCP connection while the host remains alive. They do not guarantee that an ephemeral Work environment survives, and interrupted optimizers are not resumed in place.
- A replay with the same implementation is a useful consistency check, not independent validation of the simulator's physical fidelity.

## Maintainer interface

[run.py](run.py) builds workers and drives all five pilots through `optimization-run`. It validates worker payload schemas and published job/result schemas; retains every input/spec/result; checks exact LP and curve-fit quantities; and renders measured figures. Agent-facing pages contain the prompts and interpretation; setup commands live in the appendix.

Optional application workers live beside their models in fcmaes-rust. LP-IP-craft and SQP-craft use their existing workers. fast-cma-es remains the Python in-process route and does not acquire an MCP worker through this series.
