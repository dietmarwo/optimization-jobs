# Setup appendix

Clone the five repositories side by side under one parent directory, keeping their names; their `main` (fast-cma-es: `master`) branches contain everything these tutorials use. [VALIDATION.md](VALIDATION.md) lists the revisions of the validated pilot. Do not modify the repositories' pinned dependency versions to make the examples work.

```sh
mkdir -p /path/to/checkouts && cd /path/to/checkouts
for repo in optimization-jobs fcmaes-rust LP-IP-craft SQP-craft fast-cma-es; do
  git clone https://github.com/dietmarwo/$repo
done
```

Linux, Rust 1.88 or newer, a C linker, and Python 3.10 or newer are required. Install `jsonschema>=4.18,<5` and `matplotlib>=3.7,<4` in a virtual environment. Cargo needs network access on the first build. Workers and the runner are source builds, even where numerical solver libraries are on package registries.

From `optimization-jobs`, after replacing `/path/to/checkouts` with the common parent:

```sh
python3 tutorials/agentic/run.py build --sources /path/to/checkouts \
  --bin-dir /path/to/checkouts/prompt-bin \
  --build-dir /path/to/checkouts/prompt-target
python3 tutorials/agentic/run.py run --sources /path/to/checkouts \
  --bin-dir /path/to/checkouts/prompt-bin \
  --output /path/to/checkouts/prompt-results --chapter all --cores 2
```

The output directory must be empty or new. To run one chapter, choose `trebuchet`, `production`, `energy`, `curve-fit`, `gtoc1`, `surrogate`, `lp-ip`, `sqp` or `rail-traffic`. `--seed` changes the optimizer seed; production training/holdout simulation roots remain separately fixed. `--target-m` changes the trebuchet target. `--budget-scale` scales the four application searches; the curve-fitting reference jobs and exact LP check retain their own stated budgets. This is intentional and visible in the retained specs.

The build uses one target directory but copies the two curve-fit example binaries to distinct filenames before the next build can replace `examples/custom_worker`. `build-manifest.json` records their hashes. Simulator dependencies remain in standalone optional tutorial workspaces.

For independent agent trials: use a fresh conversation with only a chapter's prompt, setup paths and the prepared binaries. Keep implementation notes and earlier outcomes out of its context. Preserve the actual transcript and the new result directory. This tests tutorial usability; it is not an independent solver benchmark or a general model-capability ranking.

The `--chapter` option also selects which workers to build; its default `all` builds the complete series. For example, `build --chapter surrogate` needs only optimization-jobs and fcmaes-rust. LP/IP needs LP-IP-craft; SQP needs SQP-craft. Each selected build always includes the runner and MCP binaries. The source-only stock workers and the existing oscillator example need no new model adapter.

`--lp-capacity` changes the project budget (default 10, strictly between 0 and 15); `--sqp-dimension` changes the allocation dimension (default 4, range 2–32). Surrogate budgets stay at 48 Branin calls, eight warm calls, and 32 calls for each oscillator method; `--budget-scale` does not change these or the LP/SQP chapters.

The driver validates payloads and input schemas from discovery. Its infeasibility exception is limited to explicitly expected infeasible jobs. Run `python3 tutorials/agentic/test_contract.py` for the evidence acceptance boundaries and independent analytic checks. The agentic tutorial CI matrix builds and executes the surrogate, LP/IP, SQP and rail chapters with real workers and current stable Rust, retains results and runs these tests. It uses the repositories' existing pinned job-API dependencies.

The [rail-traffic tutorial](rail-traffic/README.md) uses the LP/IP worker and an independently checked six-train model. `build --chapter rail-traffic` needs only optimization-jobs and LP-IP-craft. `--rail-scenario` selects a scenario copy for demand-sensitivity experiments. Its fixed solve budgets do not use `--budget-scale`. See its [setup](rail-traffic/SETUP.md) and [validation](rail-traffic/VALIDATION.md).
