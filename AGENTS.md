# AGENTS.md

This repository is **optimization-jobs**: the shared job API of fcmaes-rust,
LP-IP-craft and SQP-craft. It has no solver of its own. It contains:

- the crate `optimization-job-api`: the job envelope, the result contract,
  checked journals, artifacts and the worker SDK;
- the crate `optimization-runner`, with two binaries: the runner
  `optimization-run` and the MCP server `optimization-mcp`;
- the guide [`docs/job-api.md`](docs/job-api.md), the JSON Schemas and the
  shared test scripts.

## Read first

- [`ai-context.md`](ai-context.md) is the entry point for any AI that wants
  to optimize something, over MCP or a shell. It covers choosing a solver
  among fast-cma-es, fcmaes-rust, LP-IP-craft and SQP-craft, library or job,
  installation, the job API and the MCP server. Over MCP, the tool
  `get_guide` returns the same file.
- [`docs/job-api.md`](docs/job-api.md) is the reference for envelopes,
  resources, errors, results, artifacts, discovery and MCP.

## Build and test

```sh
cargo build --release --locked          # target/release/optimization-run, optimization-mcp
cargo fmt --all -- --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo test --release --locked
RUSTDOCFLAGS="-D warnings" cargo doc --locked --no-deps
python3 -m pip install "jsonschema>=4.18,<5"
JOB_API_REQUIRE_SCHEMA=1 python3 scripts/job-api/test_review.py   # runner regressions, fake worker
python3 scripts/job-api/test_mcp.py                               # MCP server
```

`scripts/job-api/test_integration.py` runs the shared harness against the
three real workers ([README](README.md#tests)). CI builds them from their
repositories' `main` branches.

## Conventions

- Linux only. Rust 1.88 (`rust-version`); CI checks it.
- A change to the envelope, the result contract or the worker protocol lands
  here first. The worker repositories then move their pinned `rev`.
- The embedded copies `crates/optimization-runner/schemas/*` and
  `crates/optimization-runner/guide/ai-context.md` must equal
  `docs/job-api/schemas/*` and `ai-context.md`; tests check this. Update
  both.
- Every runner and MCP error has a code (`{"error":{"code","message","retryable"}}`).
  Document new codes in the guide's tables.
- Record changes in `CHANGELOG.md` under `[Unreleased]`.
  [`RELEASING.md`](RELEASING.md) describes releases. Do not tag or publish.
