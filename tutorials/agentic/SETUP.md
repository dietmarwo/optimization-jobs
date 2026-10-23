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

The output directory must be empty or new. To run one chapter, choose `trebuchet`, `production`, `energy`, `curve-fit` or `gtoc1`. `--seed` changes the optimizer seed; production training/holdout simulation roots remain separately fixed. `--target-m` changes the trebuchet target. `--budget-scale` scales the four application searches; the curve-fitting reference jobs and exact LP check retain their own stated budgets. This is intentional and visible in the retained specs.

The build uses one target directory but copies the two curve-fit example binaries to distinct filenames before the next build can replace `examples/custom_worker`. `build-manifest.json` records their hashes. Simulator dependencies remain in standalone optional tutorial workspaces.

For independent agent trials: use a fresh conversation with only a chapter's prompt, setup paths and the prepared binaries. Keep implementation notes and earlier outcomes out of its context. Preserve the actual transcript and the new result directory. This tests tutorial usability; it is not an independent solver benchmark or a general model-capability ranking.
