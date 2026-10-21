# Publishing optimization-jobs

The repository produces two crates.io packages with one synchronized
version:

| Registry | Package | Contents |
|---|---|---|
| crates.io / docs.rs | `optimization-job-api` | Envelope, result contract, journals, artifacts, worker SDK |
| crates.io | `optimization-runner` | `optimization-run` and `optimization-mcp` |

Both versions are set in `crates/*/Cargo.toml`, and `optimization-runner`
names the same version in its dependency on `optimization-job-api`.
Publication is irreversible: never reuse a version.

Worker repositories (fcmaes-rust, LP-IP-craft, SQP-craft) keep depending on
a pinned git revision of this repository. A release does not change them;
they move their `rev` when they adopt a change.

## One-time registry setup

The workflow `publish-crates.yml` publishes through crates.io Trusted
Publishing, modeled on fcmaes-rust:

1. Create a GitHub environment named `release` (protect it if releases
   should need approval).
2. Publish the first version of each crate manually to establish ownership,
   from a clean checkout of the release commit:

   ```bash
   cargo login
   cargo publish --workspace --locked
   ```

3. For each crate, configure a crates.io Trusted Publisher: owner
   `dietmarwo`, repository `optimization-jobs`, workflow
   `publish-crates.yml`, environment `release`.
4. Set the GitHub repository variable `CRATES_IO_TRUSTED_PUBLISHING` to
   `true`.

Until the variable is set, the workflow runs every check on a tag and skips
the upload.

## Pre-release checks

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo build --release --locked -p optimization-runner
python3 scripts/job-api/test_review.py
python3 scripts/job-api/test_mcp.py
cargo publish --workspace --dry-run --locked
```

The release commit must have a clean working tree, the intended version in
both crate manifests (and in the runner's dependency on the API crate) and
`Cargo.lock`, a dated `CHANGELOG.md` entry, and passing CI, including the
mixed-node job with the three workers.

## Tag and publish

```bash
version="$(python3 -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("crates/optimization-runner/Cargo.toml").read_text())["package"]["version"])')"  # Python 3.11+
git tag -a "v$version" -m "Release optimization-jobs $version"
git push origin "v$version"
```

The tag must equal `v` plus the crate version; the workflow refuses any
other. It validates formatting, Clippy, the tests and both packages, then
publishes `optimization-job-api` and `optimization-runner` in dependency
order.

## Post-release verification

```bash
cargo install optimization-runner --version "$version"
optimization-run --version
cargo new job-api-check && cd job-api-check && cargo add optimization-job-api@"$version" && cargo build
```

Check the crate pages and the docs.rs build, then create the GitHub release.

## Discovery after a release

Follow the [ecosystem publication checklist](docs/discovery/README.md).
The [release-first plan](docs/discovery/release-first.md) puts registry releases
and clean-install verification before external integration outreach.
Package descriptions and README links reach registries only with a new
release. Check the rendered package page after publishing and update the
shared catalog when installation availability changes. Repository topics
and About text are GitHub settings, not fields a commit changes.
