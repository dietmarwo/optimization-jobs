# Twenty structured-optimization tutorials

The four foundation chapters and sixteen application chapters are executable
through the existing native Rust solvers' Python APIs. The models stay in
their owning repositories. This directory supplies one driver, provenance,
figures, and optional trusted command-job execution.

## Setup

Apply the supplied patches to sibling checkouts named `LP-IP-craft`,
`SQP-craft`, `fcmaes-rust`, `optimization-jobs` and `experiment-craft`.
Use Python 3.12 in a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r tutorials/structured/requirements.txt
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python tutorials/structured/run.py --chapter LP1 --output /absolute/new/allocation
python tutorials/structured/run.py --chapter all --output /absolute/new/smoke
```

The driver defaults to the sibling source layout; `--sources` selects another
root. Output must be new. Owner entry points allow new or empty directories,
which also accommodates the command runner's prepared output directories.
Every run retains `summary.json`; the shared driver renders PNG/SVG figures
and writes a complete `report.json` and package/source environment record.

The pinned distributions have the same numerical implementations as the
reviewed source revisions. They supply actual Rust optimisation, not a
SciPy substitution. SciPy provides independent numerical references, replay,
root isolation and validation. Larger studies use `--preset study`.

## Catalogue

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
| LP10 | Maintained rail formulation | optimization-jobs |
| SQP1 | Constrained calibration and derivatives | SQP-craft |
| SQP2 | Multistart, coordinate units and backends | SQP-craft |
| SQP3 | Hanging chain and discretization error | SQP-craft |
| SQP4 | Brachistochrone/orbit collocation and replay | SQP-craft |
| SQP5 | pykep-core Earth–Mars rendezvous | SQP-craft |
| SQP6 | Reaction sensitivities and identifiability | SQP-craft |
| X1 | One problem, four solver choices | optimization-jobs |
| X2 | DC dispatch versus AC physics | SQP-craft |
| X3 | Truss bounds and checked sizing | fcmaes-rust |
| X4 | Sphere charges: global/local search | fcmaes-rust |

The machine-readable [catalogue](catalog.json) names each owner and path. Each
chapter has a README, executable entry, prompt, follow-up, and recorded smoke
result. The original nine [agent tutorials](../agentic/README.md) retain their
existing numerical workflows.

## Native FEM reference for X3

Build the checked catalogue-design replay of the original FEM:

```bash
cargo build --release --locked --manifest-path ../fcmaes-rust/tutorials/truss-sizing/Cargo.toml --example structured_replay
export TRUSS_REPLAY_BIN="$PWD/../fcmaes-rust/tutorials/truss-sizing/target/release/examples/structured_replay"
```

X3 reports this check as unrun when the variable is absent. The delivery's
acceptance run includes parity for both the published and rounded designs.

## Execute through optimization-run

The same maintained scripts can run as trusted commands on a local node:

```bash
cargo build --release --locked
python tutorials/structured/run.py --runner target/release/optimization-run --chapter all --output /absolute/new/command-smoke
```

The driver explicitly enables commands on its new private node. It stages
checked entry/identity inputs, keeps the native handle, and collects the
sealed summary with the native transfer API. A separate execution record
records exit status and containment. MCP still refuses arbitrary command
jobs: these walkthroughs use a shell and the CLI. Callbacks are never
serialized as job payloads.

Source identities are checked at launch. The scripts read trusted sibling
checkouts and installed packages; this is not an immutable filesystem
sandbox or an offline environment bundle. Keep those sources stable during
a run. A changed watched file fails admission-time application checks.

Command completion is an execution observation. Solver claims and reference
arguments remain in the application artifact. An individual nonconvergent
attempt can be an intended lesson: the original coast model and the first
truss backend attempt are retained beside successful declared alternatives.

## Campaigns and scientific comparisons

The experiment-craft example
`examples/campaigns/structured-tutorials/run.py` runs the twenty application
commands, a dependent artifact checker, and four stock-worker jobs. Its two
predeclared native comparison groups vary LP presolve and SQP backend only.
Application/formulation/mesh/global-local tables remain descriptive. The
existing comparison allowlist and all protocol versions remain unchanged.

## Validation

```bash
python -m unittest discover -s tutorials/structured/tests -v
```

These tests target wrong constraints, incorrect certificates, derivative
errors, coordinate/multiplier mistakes, source drift and output preservation.
The full executable suite is separate from those unit tests. Remote-host
commissioning and fresh external-model usability trials are separate from
this delivery's local execution evidence.

## Limits and work accounting

The direct SQP helper caps function-plus-derivative callbacks at 20,000; ordinary runs use up to 500 major iterations, with up to 1,500 for the separately declared throttle-floor retry. Individual wall limits are 60–180 seconds. These are common maxima, not expected work; native counters and termination reasons record actual work. LP solves use explicit time/node/pivot limits and one numerical worker. The Thomson arm counters measure search pair interactions; independent derivative/Hessian audits are outside those arm counts.
