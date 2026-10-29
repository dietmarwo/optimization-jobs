# Twenty structured-optimization tutorials

Twenty chapters show how to formulate a problem, solve it with the native
Rust solvers through their Python APIs, and check the answer against an
independent reference. The models stay in the repositories of their solvers.
This directory supplies one driver, provenance records, figures and optional
execution as trusted command jobs.

## Setup

Clone the repositories side by side, keeping their names:

```bash
for repo in optimization-jobs LP-IP-craft SQP-craft fcmaes-rust; do
  git clone https://github.com/dietmarwo/$repo
done
cd optimization-jobs
python -m venv .venv
. .venv/bin/activate
python -m pip install -r tutorials/structured/requirements.txt
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python tutorials/structured/run.py --chapter LP1 --output /absolute/new/allocation
python tutorials/structured/run.py --chapter all --output /absolute/new/smoke
```

The driver expects the checkouts next to this one; `--sources` selects
another directory, and the names are matched case-insensitively. It passes
that directory to every chapter as `STRUCTURED_SOURCES`, so the chapters
import their sibling support code from the tree the driver records. Output
must be a new directory; a chapter's own entry point also accepts an empty
one. Every run keeps each chapter's `summary.json`; the driver renders PNG
and SVG figures and writes `report.json` and `environment.json` (package
versions, the commit of each checkout, hashes of its uncommitted changes and
of `git status`).

The pinned packages in `requirements.txt` provide the native optimization:
LP-IP-craft, SQP-craft, fcmaes-rust and pykep-rust. SciPy supplies only the
independent references, replays, root isolation and checks. `--preset study`
runs the larger declared cases; chapters without them repeat the smoke case.

## Chapters

| ID | Chapter | Owner |
|---|---|---|
| LP1 | Resource allocation and integrality | LP-IP-craft |
| LP2 | Battery dispatch and mode constraints | LP-IP-craft |
| LP3 | Sudoku feasibility and uniqueness | LP-IP-craft |
| LP4 | Staffing and an exact rational bound | LP-IP-craft |
| LP5 | Transportation, assignment and dual prices | LP-IP-craft |
| LP6 | Facility location and formulation strength | LP-IP-craft |
| LP7 | Cutting stock and exact pricing | LP-IP-craft |
| LP8 | Two-stage planning and information value | LP-IP-craft |
| LP9 | Full-table SpOC4 matching at a budget | LP-IP-craft |
| LP10 | [Rail timetable formulation](../rail-formulation/README.md) | optimization-jobs |
| SQP1 | Constrained calibration and derivatives | SQP-craft |
| SQP2 | Multistart, coordinate units and backends | SQP-craft |
| SQP3 | Hanging chain and discretization error | SQP-craft |
| SQP4 | Brachistochrone and orbit collocation with replay | SQP-craft |
| SQP5 | pykep-core Earth–Mars rendezvous | SQP-craft |
| SQP6 | Reaction sensitivities and identifiability | SQP-craft |
| X1 | [One problem, four solver choices](../solver-choice/README.md) | optimization-jobs |
| X2 | DC dispatch versus AC physics | SQP-craft |
| X3 | Truss bounds and checked sizing | fcmaes-rust |
| X4 | Sphere charges: global and local search | fcmaes-rust |

[catalog.json](catalog.json) names each chapter's repository and directory.
Each chapter has a README, an entry point (`run.py`), a prompt, a follow-up
exercise and recorded smoke and study results. The nine
[agent tutorials](../agentic/README.md) keep their own workflows.

## Native FEM reference for X3

Build the replay of a catalogue design through the original truss FEM:

```bash
cargo build --release --locked --manifest-path ../fcmaes-rust/tutorials/truss-sizing/Cargo.toml --example structured_replay
export TRUSS_REPLAY_BIN="$PWD/../fcmaes-rust/tutorials/truss-sizing/target/release/examples/structured_replay"
```

Without the variable, X3 records the native parity as `null`. The recorded
X3 results include parity for both the published and the rounded design.

## Execute through optimization-run

The same scripts can run as trusted command jobs on a local node:

```bash
cargo build --release --locked
python tutorials/structured/run.py --runner target/release/optimization-run --chapter all --output /absolute/new/command-smoke
```

The driver enables commands on its new private node. It stages a launcher
and a source manifest as hashed inputs, keeps the native handle, and collects
the sealed summary with the native transfer API. The execution record of
each job, including a failed one, is kept as `execution.json`. MCP still
refuses command jobs: these walkthroughs use a shell and the CLI. Callbacks
are never serialized into job payloads.

The launcher checks the hashes of the watched sources and data before it
starts a chapter, and refuses to run if any changed. The chapters still read
trusted checkouts and installed packages: this is a launch-time identity
check, not a filesystem sandbox or an offline environment bundle. Keep the
sources stable during a run.

A completed command job is an execution observation. Solver claims and
reference arguments stay in the chapter's summary. An individual
nonconvergent attempt can be the intended lesson: SQP5's coast-permitting
model and X3's first QP backend attempt are kept beside the declared
alternatives that converge.

## Campaigns and scientific comparisons

experiment-craft's `examples/campaigns/structured-tutorials/run.py` runs the
twenty chapters as command steps, a dependent artifact checker and four
stock-worker jobs. Its two predeclared comparison groups vary only LP presolve
and the SQP backend, the settings its comparison adapter supports. Tables
across formulations, meshes, solvers or global/local splits are descriptive.

## Validation

```bash
python -m unittest discover -s tutorials/structured/tests -v
```

These tests cover wrong constraints and certificates, derivative and
multiplier errors, infeasible points, checks that must survive `python -O`,
source drift, the sibling tree the chapters import from, the catalog, and
refusal to overwrite output. The
[`structured-tutorials` workflow](../../.github/workflows/structured-tutorials.yml)
runs them, both presets of all twenty chapters, and the command-job route for
LP10 and X1.

## Limits and work accounting

The SQP chapters cap function-plus-derivative callbacks at 20,000; ordinary
runs use up to 500 major iterations, and SQP5's declared throttle-floor model
up to 1,500. Wall limits are 60–180 seconds per solve. These are maxima, not
expected work; the native counters and termination reasons record the actual
work. LP solves use explicit time, node and iteration limits and one
numerical thread. The Thomson arm counters measure search pair interactions;
the independent derivative and Hessian audits are not counted there.
