# Supported native comparisons; application reports remain command artifacts

Protocol: `40addd3f670f7344946a75f904a0097331c105981c8587ad8753db41d69d4a55`

Campaign status: `completed` (25 succeeded). A campaign that is not completed gives a snapshot, not a final result.

| Group | Common cap | Replication | Design | Description |
|---|---|---|---|---|
| lp | 30.0 wall seconds | deterministic | unpaired | Same model and starts, supported settings only; pipeline check |
| sqp | 30.0 wall seconds | deterministic | unpaired | Same model and starts, supported settings only; pipeline check |

| Group | Arm | Planned | Complete | Metric (unit) | Complete feasible n | Available feasible n | Mean (complete) | Median (complete) | Target hits / planned; unresolved |
|---|---|---:|---:|---|---:|---:|---:|---:|---|
| lp | lp-on | 1 | 1 | objective (native model objective) | 1 | 1 | 16 | 16 |  |
| lp | lp-off | 1 | 1 | objective (native model objective) | 1 | 1 | 16 | 16 |  |
| sqp | sqp-active_set | 1 | 1 | objective (native model objective) | 1 | 1 | 0.25 | 0.25 |  |
| sqp | sqp-clarabel | 1 | 1 | objective (native model objective) | 1 | 1 | 0.24999999999999997 | 0.24999999999999997 |  |

## Declared paired differences

Differences are left minus right; only complete feasible pairs enter these descriptive summaries.

| Group | Left arm | Right arm | Metric | Planned | Included | Excluded | Mean difference |
|---|---|---|---|---:|---:|---:|---:|

## Native accounting and evidence

| Group | Arm | Feasibility | Claims | Evidence levels | Known work and missing runs |
|---|---|---|---|---|---|
| lp | lp-on | {"true":1} | {"numerical_optimum":1} | {"rechecked":1} | {"nodes":{"known_runs":1,"known_total":1,"unknown_runs":0},"simplex_iterations":{"known_runs":1,"known_total":1,"unknown_runs":0},"validation_evaluations":{"known_runs":1,"known_total":1,"unknown_runs":0}} |
| lp | lp-off | {"true":1} | {"numerical_optimum":1} | {"rechecked":1} | {"nodes":{"known_runs":1,"known_total":3,"unknown_runs":0},"simplex_iterations":{"known_runs":1,"known_total":3,"unknown_runs":0},"validation_evaluations":{"known_runs":1,"known_total":1,"unknown_runs":0}} |
| sqp | sqp-active_set | {"true":1} | {"first_order":1} | {"rechecked":1} | {"derivatives":{"known_runs":1,"known_total":2,"unknown_runs":0},"functions":{"known_runs":1,"known_total":3,"unknown_runs":0},"iterations":{"known_runs":1,"known_total":1,"unknown_runs":0},"qp_iterations":{"known_runs":1,"known_total":0,"unknown_runs":0},"validation_calls":{"known_runs":1,"known_total":2,"unknown_runs":0}} |
| sqp | sqp-clarabel | {"true":1} | {"first_order":1} | {"rechecked":1} | {"derivatives":{"known_runs":1,"known_total":2,"unknown_runs":0},"functions":{"known_runs":1,"known_total":3,"unknown_runs":0},"iterations":{"known_runs":1,"known_total":1,"unknown_runs":0},"qp_iterations":{"known_runs":1,"known_total":13,"unknown_runs":0},"validation_calls":{"known_runs":1,"known_total":2,"unknown_runs":0}} |

## All campaign steps

| Step | State | Included / exclusion |
|---|---|---|
| LP1 | succeeded | Application command output; no inferred solver metrics |
| LP10 | succeeded | Application command output; no inferred solver metrics |
| LP2 | succeeded | Application command output; no inferred solver metrics |
| LP3 | succeeded | Application command output; no inferred solver metrics |
| LP4 | succeeded | Application command output; no inferred solver metrics |
| LP5 | succeeded | Application command output; no inferred solver metrics |
| LP6 | succeeded | Application command output; no inferred solver metrics |
| LP7 | succeeded | Application command output; no inferred solver metrics |
| LP8 | succeeded | Application command output; no inferred solver metrics |
| LP9 | succeeded | Application command output; no inferred solver metrics |
| SQP1 | succeeded | Application command output; no inferred solver metrics |
| SQP2 | succeeded | Application command output; no inferred solver metrics |
| SQP3 | succeeded | Application command output; no inferred solver metrics |
| SQP4 | succeeded | Application command output; no inferred solver metrics |
| SQP5 | succeeded | Application command output; no inferred solver metrics |
| SQP6 | succeeded | Application command output; no inferred solver metrics |
| X1 | succeeded | Application command output; no inferred solver metrics |
| X2 | succeeded | Application command output; no inferred solver metrics |
| X3 | succeeded | Application command output; no inferred solver metrics |
| X4 | succeeded | Application command output; no inferred solver metrics |
| lp-off | succeeded | included |
| lp-on | succeeded | included |
| sqp-active_set | succeeded | included |
| sqp-clarabel | succeeded | included |
| application-checks | succeeded | Application command output; no inferred solver metrics |

Descriptive summaries only; no ranking, significance test or optimality certification.
Fixed-work and fixed-time protocols use declared caps; actual work and early termination remain visible.
Complete-feasible metrics require an accepted complete single-task result, known accounting and feasibility=true.
Available-feasible metrics may include partial or failed runs and are reported separately.
Targets use all planned runs as the denominator; failures, missing and unknown outcomes are unresolved.
Deterministic repeats measure timing reproducibility, not independent quality discoveries.
Elapsed times describe this execution environment and are not home-fleet performance.
