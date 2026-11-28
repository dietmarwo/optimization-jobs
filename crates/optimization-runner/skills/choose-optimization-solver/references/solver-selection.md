## 2. Choose the solver

Decide in this order, so that structure never overrides the requested output:

1. **What the user needs**: one solution, a Pareto front, or many diverse
   solutions; and which guarantee (a good point, a local optimum with KKT
   evidence, an LP/MIP bound and gap). Keep both through the next steps.
2. **Structure the model has**: linear, smooth with derivatives, or a black
   box; its size, integer variables and evaluation cost.
3. **A method that keeps both**, from the tables below.
4. **An interface that has it** ([step 3](https://github.com/dietmarwo/optimization-jobs/blob/main/ai-context.md#3-choose-the-interface-library-or-job)):
   check that the model, profile and options exist where you will run it.

### One objective

| Structure | Solver | Limits to check |
| --- | --- | --- |
| Linear objective and constraints, continuous and/or integer variables | LP-IP-craft | A MIP needs finite bounds on every variable (or bounds presolve can infer); no QP/MIQP; optional MIP gap stops since 0.30 (`gap_limit` keeps a checked feasible point and claims no optimality); numerical statuses, no exact certificates. When peak speed decides, or for a large, hard industrial MIP, compare with a mature solver such as HiGHS under the same independent check |
| Smooth nonlinear objective and constraints, continuous variables, at most 256, gradient and Jacobian available; a local optimum suffices or good starts exist | SQP-craft | Local method with dense BFGS. Use multistart for multimodal models. For larger models with small overlapping cliques, see the structured row below |
| Expensive deterministic simulation (seconds to a minute per call), continuous box, 1–32 variables, at most 256 calls, few evaluations at a time | `fcmaes.surrogate/1` (fcmaes-rust job worker, experimental), compared with BiteOpt | Job-only: the simulation must be a Rust model in an fcmaes application worker; there is no Python surrogate. No constraints, noise or mixed variables. Prefer retry (BiteOpt first) for separable or many-modal problems with ten or more variables, and when many cores can evaluate in parallel. In Python, use fcmaes with a parallel population (fast-cma-es "Expensive objective") |
| Black box: nonsmooth, noisy or multimodal, box bounds; integers or categories decoded from continuous variables | fcmaes retry: BiteOpt first; DE for robust exploration and integer decoding; CMA-ES with a good start (`guess` in `fcmaes.retry/1`); CR-FM-NES for higher dimensions; PGPE for noise and very high dimensions | Benchmark at least two choices on equal budgets and seeds. Constraints become penalties or repairs: check the raw constraints separately ([Results](https://github.com/dietmarwo/optimization-jobs/blob/main/ai-context.md#results-claims-and-evidence)) |

### Several objectives (a Pareto front)

| Structure | Method | Notes |
| --- | --- | --- |
| Linear | A series of LPs/MIPs in LP-IP-craft: weighted sums with strictly positive weights, or ε-constraints (minimize one objective, bound the others as extra rows), one model per candidate point | Candidates, not certified Pareto points (below). Weighted sums reach only supported points: for an LP the front is convex and every efficient point is supported, but a MIP's front can have unsupported points that no weights reach. MODE would discard the structure |
| Smooth, at most 256 variables | ε-constraint or weighted-sum SQP solves with multistart (one model per bound or weight, or both as model parameters), or fcmaes MODE | A converged solve is a first-order point of the scalarized problem, not proof of local Pareto optimality. MODE needs no derivatives but more evaluations |
| Black box | fcmaes MODE (or weighted `moretry` in the libraries); with exactly two objectives keep every evaluation in the exact archive (`fcmaes.pareto`, `ParetoArchive2D`) | Constraints come after the objectives and are feasible at `g(x) <= 0`; MODE's final population is not the front of everything it evaluated |

Scalarization gives candidate points; check them before calling them a
front:

- **Ties.** An ε-constraint optimum can be dominated when the bound is not
  tight or the optimum is not unique. Minimizing `f1 = x` subject to
  `f2 = -y <= 0` on `[0,1]^2` may return `(0,0)` with objectives `(0,0)`,
  which `(0,1)` with `(0,-1)` dominates; the solver is right, the label would
  be wrong. Resolve ties with a second stage (fix the first objective at its
  optimum and minimize the others) or a small augmentation term, as in
  AUGMECON.
- **Unsupported points.** A weighted sum with a degenerate direction has a
  whole optimal face, and the solver returns one point of it. Of the
  efficient points `(0,3)`, `(2,2)` and `(3,0)` of a discrete problem, no
  positive weights make `(2,2)` optimal.
- **Filtering.** Evaluate every candidate's original objectives and
  constraints independently, and keep the non-dominated ones.
- **Reporting.** Report each point's own scalar evidence (termination, gap,
  KKT residuals), and call the result a set of non-dominated candidates, not
  a certified Pareto front.

### Many diverse solutions

fcmaes MAP-Elites (grid or CVT archives, CMA-ME/CMA-MAE emitters in the job
worker; Diversifier in the libraries). The behavior descriptors must express
the diversity the user wants; occupancy alone is not usefulness.

### Requests outside the toolbox

Say so, and name what would fit, instead of forcing the problem into one of the
solvers:

| Request | What to do |
| --- | --- |
| QP or MIQP, conic (SOCP, SDP) | No dedicated solver here. A small, smooth, continuous QP can be an SQP model; otherwise a QP/conic solver (OSQP, Clarabel directly, a MIQP-capable MIP solver) |
| Larger smooth NLP with a sparse Jacobian and small overlapping cliques | Experimental [structured SQP-craft](https://github.com/dietmarwo/SQP-craft/blob/main/docs/structured-sqp.md) (from 0.18.0). Use Clarabel with partitioned BFGS and declare the nonlinear objective support. The direct API also accepts an exact sparse Hessian callback. Compare first-order residuals with a reference solver |
| General large sparse NLP or dense Hessian above 256 variables | Start with a mature sparse solver such as IPOPT for large sparse problems, or a solver sized for the dense formulation |
| MINLP with a proof of optimality, any global-optimality certificate | Outside the guarantees: fcmaes on a decoded model is a heuristic, LP-IP-craft's statuses are numerical. Use a global MINLP solver (SCIP, BARON, Couenne) |
| Scheduling, routing, graphs and other combinatorial structure | Prefer an exact formulation (a MIP in LP-IP-craft, or a dedicated CP/routing solver) when the structure allows; decode-and-repair with fcmaes when it does not. Do not drop exploitable structure just because a black-box encoding is possible |
| Remote, asynchronous or human-in-the-loop evaluation | The library ask/tell interfaces (fast-cma-es, `fcmaes-core`); the job protocol has no ask/tell session |
| Stochastic simulation | Fixed seed sets for training and disjoint seeds for validation (see the fcmaes `ai-context.md` files); the job profiles recheck deterministic values only |
| Several machines, pause and resume of an optimizer's state | Not provided: one node per runner; a surrogate warm start from a snapshot is a new job, not a resumed one |

### Rules across the tables

- Do not pick a gradient-free optimizer just because the model is a
  simulation. If the whole map from decisions to objective is differentiable
  and the gradients are reliable, a gradient method uses far fewer
  evaluations.
- Global then local: points from an fcmaes run can be the starts of an SQP
  solve. In process this is ordinary code. As jobs, the agent passes the
  points between two jobs. Before using them, check that both sides have the
  same model ID and version, the same variable order, units and bounds, and
  the same data (SHA-256); recheck the points with the target worker's
  `evaluate` profile.
- No solver here certifies a global optimum, proves MINLP optimality or emits
  exact certificates. fcmaes on a decoded integer model is a heuristic.
- Recheck any point, including another tool's, independently. The
  `evaluate` profiles recompute objective and feasibility (`sqp.evaluate/1`
  only function values). The libraries also check optimality conditions:
  `lp_ip_craft.lp_residuals` and `safe_dual_bound` for LPs,
  `sqp_craft.kkt_residuals` for KKT points.
