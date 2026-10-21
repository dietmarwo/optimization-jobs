# Release first, then approach the integration author

The intended sequence is **tested registry releases → clean-install verification
→ a small compatibility example → contact the integration's author**. The
Rust registry is **crates.io**; Cargo is its package manager. Nothing in these
documents publishes a package or sends a message.

## Release inventory

Registry APIs were checked on 2026-10-21. Versions below are inventory, not a
claim that the current main branches have passed release qualification.

| Repository | Registry artifacts | Observed release / source version | Next action |
| --- | --- | --- | --- |
| fast-cma-es | PyPI `fcmaes` | Published 2.0.3; source still declares 2.0.3 with unreleased changes | Select a new unused version, synchronize release notes and metadata, run wheel/sdist/native tests |
| fcmaes-rust | crates.io `fcmaes-core`; PyPI `fcmaes-rust` | Both published at 0.1.5; source still declares 0.1.5 with unreleased changes | Select one new unused synchronized version; test core, wheels and sdist |
| LP-IP-craft | crates.io `lp-ip-craft`, `lp-ip-craft-native`; PyPI `lp-ip-craft` | No release found for the main package names; source 0.28.0 | Complete first-publication setup and qualify the intended first version |
| SQP-craft | crates.io `sqp-craft`, `sqp-craft-parallel`, `sqp-craft-activeset`, `sqp-craft-clarabel`, `sqp-craft-solver`; PyPI `sqp-craft` | No release found for the main package names; source 0.16.0 | Complete first-publication setup and qualify the intended first version |
| optimization-jobs | crates.io `optimization-job-api`, `optimization-runner` | Neither found; both source crates 0.2.0 | Qualify and publish the API before the runner; both keep the same release version |

For the existing fcmaes packages, 2.0.4 and 0.1.6 are possible next patch-version
candidates only if the maintainers judge the changes compatible and those
versions remain unused. Breaking changes may need a different version. Do not
reuse 2.0.3/0.1.5: the new README and metadata cannot replace uploaded files.
Recheck all names and versions immediately before publishing; the inventory is
time-sensitive.

## Practical order

1. **Merge and qualify the discovery changes.** Deploy the landing page so
   package metadata does not link to an unavailable site. Choose clean release
   commits and update versions, lockfiles and dated changelogs together.
2. **Release the existing fcmaes packages.** This is the shortest route to a
   usable example for the existing OptunaHub adapter. Run the full release
   checks from fast-cma-es and fcmaes-rust, including installed-wheel and sdist
   tests outside the source checkout. The two projects have independent version
   numbers; only `fcmaes-core` and Python `fcmaes-rust` are synchronized.
3. **Bootstrap the craft libraries.** Publish each repository's library crates
   in dependency order, then its Python distribution from the same release
   commit. Complete the first-release ownership/Trusted Publisher setup described
   in that repository. Run real native solves after installation:
   `backend="native"` for LP-IP-craft and `method="sqp"` for SQP-craft; their
   default dummy paths are not solver smoke tests.
4. **Publish the shared job crates.** Publish API then runner, test both binaries
   and a real registered worker on Linux, and inspect the registry README. This
   track can proceed independently of the library releases: workers currently
   pin the job SDK through git, so registry publication does not repin them.
5. **Verify discovery and only then send outreach.** Check package project URLs,
   docs.rs, examples, hashes/provenance and the landing-page availability table.
   Update the shared catalog when packages are actually installable. MCP Registry
   publication has the separate executable-selection checks in the
   [directory pack](directory-submissions.md).

The job workers and the experimental surrogate remain source-only in this plan.
A library release must not imply that installing its Python package installs an
MCP server or arbitrary nonlinear model support.

## Release gates already supplied by the projects

Use the commands and workflow names from the exact release checkout:

- [fast-cma-es RELEASING.md](https://github.com/dietmarwo/fast-cma-es/blob/master/RELEASING.md):
  `wheels.yml`, native tests and documentation checks; environments `pypi`/`testpypi`.
- [fcmaes-rust RELEASING.md](https://github.com/dietmarwo/fcmaes-rust/blob/main/RELEASING.md):
  `publish-crates.yml`, `python-release.yml`, Rust tests/MSRV and Python smoke tests;
  environment `release`.
- [LP-IP-craft RELEASING.md](https://github.com/dietmarwo/LP-IP-craft/blob/main/RELEASING.md)
  and [SQP-craft RELEASING.md](https://github.com/dietmarwo/SQP-craft/blob/main/RELEASING.md):
  first crate ownership, pending PyPI Trusted Publishers, then their release
  workflows and clean-install smoke tests; environment `release`.
- [optimization-jobs RELEASING.md](../../RELEASING.md):
  API/runner packaging, runner and MCP regressions and mixed-worker checks;
  environment `release`.

A green documentation build is not a green release. Passing import-only tests
does not establish solver correctness. Complete the existing numerical and
packaging gates; do not waive them for a discovery-only change. Registry bootstrap,
Trusted Publisher configuration and authenticated upload remain maintainer actions
unless separately executed in an authorized release environment.

## What to bring to the integration's author

The [OptunaHub entry](https://hub.optuna.org/samplers/fcmaes/) credits its
author with `FastCmaesSampler` (see [references](references.md)). Before
outreach, verify the contact route from the current upstream profile or
contribution history.

Prepare a small reproducible compatibility example with:

- exact released `fcmaes`, Optuna and OptunaHub versions;
- a fixed seed, bounded objective and an explicit evaluation budget;
- installation and execution commands that work outside the source checkout;
- the tested adapter revision and any compatibility failures;
- a short explanation of what a Rust-backed adapter could add, if it has been
  implemented and tested, without claiming it already exists.

Ask whether maintaining or extending the integration would be useful to its
author. An existing adapter is a concrete basis for collaboration; it is not
permission to attribute support for the other four projects to that author.
No proposed integration is presented as completed.
