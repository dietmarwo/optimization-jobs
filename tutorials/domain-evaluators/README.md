# Domain evaluators: executed command-job tutorials

Start with the [hydro-craft walkthrough](https://github.com/dietmarwo/hydro-craft/blob/main/docs/command-jobs.md).
It contains the complete setup and seven runnable chapters: one CLI evaluation,
a population optimizer, replay and identity, a dependent campaign, porting, and
when to implement a worker. This directory owns the domain-independent driver,
identity checks, comparison helper and CI; teaching about the models stays in
the evaluator repositories.

| Evaluator | Descriptor and adapter | What the independent CLI replay checks |
|---|---|---|
| Hydro | [jobs](https://github.com/dietmarwo/hydro-craft/tree/main/examples/jobs) | Synthetic catchment train/validation/test RMSE |
| Thermo | [jobs](https://github.com/dietmarwo/thermo-craft/tree/main/examples/jobs) | Nominal and held-out operating-scenario efficiency |

Keep `optimization-jobs`, `hydro-craft`, `thermo-craft` and `experiment-craft`
as sibling checkouts. After the linked setup, from their common parent:

```sh
python optimization-jobs/tutorials/domain-evaluators/run.py --sources . \
  --evaluator hydro-craft --output hydro-direct
python optimization-jobs/tutorials/domain-evaluators/run.py --sources . \
  --evaluator hydro-craft --output hydro-command --command-jobs --workers 2
python optimization-jobs/tutorials/domain-evaluators/compare.py \
  hydro-direct/summary.json hydro-command/summary.json
python experiment-craft/examples/campaigns/domain-evaluators/run.py --sources . \
  --evaluator hydro-craft --output hydro-campaign --workers 2
```

Substitute `thermo-craft` and new output paths to prove reuse. No driver branch
selects hydrology or thermodynamics. The [catalog](catalog.json) points to a
`domain-evaluator.tutorial/0.1` descriptor: name, module, CLI binary/request,
case, optimizer adapter, wheel, presets and optimizer names. The adapter owns
`configuration`, `decode`, `penalty` and `report`; shared support owns execution.
Paths in a descriptor are relative to its repository and cannot escape it.
The sibling checkouts themselves may be symbolic links.
The common CLI wrapper and replay checker live in hydro-craft, so both ports
need that sibling even when only thermo is selected.

The `smoke` preset has 400 evaluations × 2 seeds × 2 fcmaes optimizers.
`study` has 20,000 × 5 × 2. Every run writes `best.json`, `history.csv`, and
`identity.json`; each winner is replayed through a separately executed CLI
check. The driver retains failures and exits nonzero if any check fails.
`summary.json` contains the scientific records; `compare.py` excludes only
elapsed seconds. The replay check also requires the CLI to report the hash of
the model it was asked to evaluate. Checked-in smoke summaries are in each evaluator's
`examples/jobs/outputs/smoke-summary.json`. A dependency update requires
intentional baseline review; CI must not silently regenerate expected outputs.

The real-runner regression suite needs the builds and wheels from setup:

```sh
python -m unittest discover -s optimization-jobs/tutorials/domain-evaluators/tests -v
python -O -m unittest discover -s optimization-jobs/tutorials/domain-evaluators/tests -v
```

Commands are trusted under the runner user, not sandboxed. They are CLI-only;
MCP refuses them. Native command results carry exit and output integrity, not
scientific feasibility, optimality claims or evaluation accounting. That
accounting lives in the tutorial outputs. Installed wheel contents are checked
against a verified wheel; neither the Python environment nor host libraries
are a snapshot. These bounded synthetic examples establish no physical-model
qualification or optimizer ranking. See the walkthrough's porting/worker table.

The [workflow](../../.github/workflows/domain-evaluators.yml) builds the
sibling repositories and runs both ports directly, as command jobs and as
campaigns, on pull requests and weekly. It uses the siblings' `main` branches,
except that a pull request uses a sibling branch with the pull request's own
branch name where one exists. A change that spans repositories is therefore
checked before any part of it is merged: push the same branch name to each
repository involved. The workflow also checks each evaluator's `SHA256SUMS`.
It does not change `baseline-lock.json`, release versions, worker protocols or
evaluator packages.
