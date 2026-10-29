# X1: One workshop story, four solver choices

This executable chapter uses the existing native Rust solver through its Python API. The numerical definitions live with this chapter's owner; the shared driver supplies orchestration and figures.

## Model and decision

Linear production uses capacities 2P+Q<=100 and P+Q<=80. Add batch sizes and setup costs for a MIP, decreasing margins for a smooth constrained model, then treat a six-product batch model as a black-box objective.

## Work through the lesson

The common workshop has machine limit $2P+Q\le100$ and labor limit $P+Q\le80$. Each variant declares a different decision model.

| Variant | Structure and native solver | Independent answer |
|---|---|---|
| A | Linear profit $40P+30Q$; LP-IP LP | $(20,60)$, profit 2600; vertices and duals |
| B | Batches of 7 and 9, setup cost 150; LP-IP MIP | $(21,54)$, profit 2160; batch enumeration |
| C | Profit $(40-.25P)P+(30-.2Q)Q$; SQP | $(200/7,300/7)$, profit $91000/49$; KKT |
| D | Six products exposed through a black-box callback; fcmaes Bite | Feasibility and measured gap to the same model's enumerated/MIP optimum |

Work through A→D and identify what changed before choosing a solver. D's returned value is `best_found`; a known MIP optimum provides a measured gap for that fixture, not a general guarantee for black-box optimization. The profit bars represent different models and are not a solver speed or quality ranking.

## Run

Install the pinned solver distributions and scientific dependencies using the [shared setup](https://github.com/dietmarwo/optimization-jobs/blob/main/tutorials/structured/README.md). Keep the patched repositories as sibling directories. From this repository's root:

```bash
python tutorials/structured/run.py --chapter X1 --output /absolute/new/x1
```

For the owner entry point, run `python tutorials/solver-choice/run.py --preset smoke --output /absolute/new/x1-direct`. It produces JSON; the shared driver additionally renders PNG/SVG figures. `--preset study` selects the declared larger cases. Output may be new or empty, and an occupied directory is refused.

## Independent answer and validation

Linear profit is 2600 at (20,60). The two-product batch optimum is 2160 at (21,54). Concave profit is 91000/49 at (200/7,300/7). The six-product native MIP is checked against enumeration, then the fcmaes best-found gap is measured against that reference.

Every run retains native status, points and available diagnostics. LP candidates are checked against row/bound/integrality requirements; SQP results retain derivative checks and independently reconstructed KKT residuals. Application-specific references are computed separately. All failures remain in the report.

## Read the result

Read `summary.json` before interpreting `figure.png`. The report records the actual result; expected reference values are not substituted for missing numerical outcomes. A completed command job means that the chapter's executable checks completed, while individual solver attempts can still be nonconvergent where the lesson explicitly retains them.

These are different formulations, not a shared solver performance ranking. Use linear/integer structure when available; global search is useful when that structure is unavailable.

## Agent prompt

> Choose a fitting solver for each of the four production-mix variants. Explain what changed in the decision model, verify every answer with its own reference, and report black-box search as best found with a measured gap to the same-model MIP optimum.

Use the complete [prompt](prompt.md) for the workflow and evidence requirements.

## Follow-up exercise

Choose a solver from the shared guide before running each variant. Explain why a black-box approximation to an LP still returns best-found evidence.

## Provenance and limits

The original plan's probes are historical planning evidence. The checked-in `results/smoke/summary.json` and figures record this implementation's executed case. Source and installed-package identities are also recorded by the shared driver. These are reproducible teaching experiments, not industrial or hardware performance certifications. Cross-formulation and cross-solver tables are descriptive.

## Recorded example

![Recorded X1 smoke result](results/smoke/figure.png)

Inspect the [complete smoke summary](results/smoke/summary.json) alongside the figure.

The [study summary](results/study/summary.json) and [study figure](results/study/figure.png) retain the declared study preset separately.
