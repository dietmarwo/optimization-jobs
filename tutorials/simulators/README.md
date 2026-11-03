# CRN and CFD optimization tutorials

Eight executable lessons connect the simulators to structured optimization,
global search and durable local campaigns. Numerical models and their evidence
live in the simulator repositories. This directory supplies discovery, shared
setup and the existing command-job route.

| ID | Lesson and canonical walkthrough |
|---|---|
| C1 | [Stochastic calibration with reusable topology](https://github.com/dietmarwo/CRN-craft/blob/main/tutorials/optimization/C1-calibration.md) |
| C2 | [BDF sensitivities, global/local fitting and stochastic transfer](https://github.com/dietmarwo/CRN-craft/blob/main/tutorials/optimization/C2-sensitivities.md) |
| C3 | [Oscillator Pareto fronts, archives and backend checks](https://github.com/dietmarwo/CRN-craft/blob/main/tutorials/optimization/C3-oscillators.md) |
| C4 | [Aggregation inference with bounded dynamic-species rules](https://github.com/dietmarwo/CRN-craft/blob/main/tutorials/optimization/C4-rules.md) |
| F1 | [CFD source allocation by LP, BiteOpt and GP](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/F1-allocation.md) |
| F2 | [Sensor coverage MIP and held-out identifiability](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/F2-sensors.md) |
| F3 | [Coupled-flow optimization with fixed fidelity gates](https://github.com/dietmarwo/CFD-craft/blob/main/tutorials/optimization/F3-coupled-flow.md) |
| X1 | [Complete campaigns and fixed-CPU layouts](https://github.com/dietmarwo/experiment-craft/blob/main/examples/campaigns/simulators/README.md) |

The machine-readable index is [catalog.json](catalog.json). Each walkthrough
contains an initial prompt, mathematical formulation, run commands, expected
artifacts, acceptance rules, interpretation and follow-up experiments. Begin
with C1 and F1, add C2/F2, then explore C3/F3/C4. X1 wraps C1/F1 and optionally
C2/F3. These IDs are local to this simulator series; the separate
[structured series](../structured/README.md) also has its own X1–X4 lessons.

## Prepare sibling checkouts

Use patched checkouts of CRN-craft, CFD-craft, fcmaes-rust, LP-IP-craft,
SQP-craft, optimization-jobs and experiment-craft under one parent directory.
The combined patch bundle records their exact source commits. Keep fast-cma-es
next to them when reproducing the complete repository audit; these new runnable
lessons use the native Rust bindings. This setup targets Linux and CPython 3.12.

Run the following from the parent directory. Activate one environment for all
commands and keep it active when launching a campaign:

```bash
python3.12 -m venv tutorial-env
source tutorial-env/bin/activate
python -m pip install -r optimization-jobs/tutorials/simulators/requirements.txt
python -m pip install --no-deps ./CRN-craft
python -m pip install -e ./experiment-craft
cargo build --release --locked --manifest-path CRN-craft/Cargo.toml
cargo build --release --locked --manifest-path CFD-craft/Cargo.toml
cargo build --release --locked --manifest-path optimization-jobs/Cargo.toml
cargo build --release --locked --manifest-path CFD-craft/integrations/fcmaes-cfd-worker/Cargo.toml
rustup toolchain install 1.89.0 --profile minimal
cargo +1.89.0 build --release --locked --manifest-path CRN-craft/integrations/diffsol/Cargo.toml
cargo build --release --locked --manifest-path fcmaes-rust/tutorials/oscillator-topology-search/Cargo.toml --example crn_reference
```

Use Rust 1.88 or newer for Python/jobs and the reference example, and 1.89 for
the isolated diffsol workspace. The CRN core's lower MSRV does not cover its
optional workspaces. For an all-source optimizer environment, build/install
the sibling Python projects instead of their pinned wheels, keeping the same
versions. Build directories are independent; a custom `CARGO_TARGET_DIR`
requires the corresponding explicit binary options in the commands below.

Installation/build is cold setup. Record its duration and toolchain if cost is
part of the study. Chapter timers use already installed binaries and packages;
no build-time speed comparison is claimed.

## Run directly, then through command jobs

From the parent directory:

```bash
python optimization-jobs/tutorials/simulators/run.py --chapter all --output /tmp/simulator-smoke
python optimization-jobs/tutorials/simulators/run.py --chapter C1 --preset study --threads 8 --output /tmp/simulator-c1-study
python optimization-jobs/tutorials/simulators/run.py --chapter all --command-jobs --output /tmp/simulator-command-smoke
python experiment-craft/examples/campaigns/simulators/run.py --cpu-slots 8 --tasks 8 --output /tmp/simulator-campaign
```

Use new output directories. `--sources` selects another sibling parent.
`--crn-binary`, `--ode-binary`, `--reference-binary`, `--cfd-binary`,
`--cfd-worker` and `--runner` override executable locations. `all` runs the
seven simulator chapters sequentially; run the X1 campaign separately as shown.
F2 keeps the same small exact scenario design for both presets. Other study
presets increase their documented search/path/fidelity budgets.

Command mode creates an isolated foreground node with commands explicitly
enabled. It stages a checked entry point and source manifest, declares CPU and
wall limits, and collects `summary.json` plus `evidence.zip`. The runtime owns
admission, process supervision, output sealing and native job handles. The
wrapper retains failures and never retries an uncertain job automatically.

The source manifest hashes scripts, input models and used binaries, records
repository heads, and checks installed package versions at launch. Tutorial
sources run from trusted sibling checkouts, which must remain unchanged during
the run. This is launch-time identity checking, not a hermetic environment or
snapshot of all Python/native dependencies. Generated command input files are
sealed by the runtime. The nested F1 GP node is serial inside its enclosing
serial command and does not add concurrent work beyond its slot allowance.

## Render the evidence

After a direct or command run, render standalone SVG/PNG figures from its collected summaries:

```bash
python optimization-jobs/tutorials/simulators/plot.py --results /tmp/simulator-command-smoke --output /tmp/simulator-figures
```

The figures use recorded losses, laws, ranks and fidelity changes. They do not turn a failed scientific design gate into an accepted result.

## Interpret results

A chapter's `passed` field validates its declared numerical/workflow checks.
Optimizer quality and scientific support have separate fields. In particular,
F3 can pass its workflow while supporting zero designs; F2 can solve the
coverage MIP optimally with a rank-deficient sensor subset. C1 checks exact
fresh/reusable traces, while C3 compares generator laws and shared metrics
across independent random streams.

Actual evaluations, CRN paths/events and CFD accepted/failed solves are retained.
F1's native GP counters are additional to the full-field solves in its summary.
The ReBop compatibility reference does not expose event counts. Missing cold
build costs and unavailable counters are stated rather than estimated.

There is no new job protocol, stock CRN MO/QD model, rules template API or
coupled-flow worker in this series. Existing command jobs are the initial route
for these application lessons. The [job guide](../../docs/job-api.md) and
[simulator discovery](../../ai-context.md#simulation-models) describe the existing
scalar application workers. X1 uses descriptive reports rather than extending
the campaign engine's formal comparison semantics.

The combined deliverable includes a verification record, source commits and
per-repository patches. The smoke evidence establishes reproducibility and
checks the workflows; it does not establish optimizer superiority or physical
validation. Use independent repetitions and predeclared statistical/fidelity
criteria before promoting a research claim.
