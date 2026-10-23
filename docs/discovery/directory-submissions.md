# Directory submission pack

Prepared 2026-10-21. **These are proposals, not accepted listings.** Use only
after checking the target directory's current contribution rules. The
[publication checklist](README.md) covers deployment and package releases.

## MCP Registry: optimization-jobs

Proposed name: `io.github.dietmarwo/optimization-jobs`.

Proposed short description:

> Durable optimization jobs for AI agents, with solver discovery, CPU budgets,
> cancellation and result artifacts over MCP.

Proposed directory entry:

> [optimization-jobs](https://github.com/dietmarwo/optimization-jobs) — A local
> Rust MCP server and job runner for registered black-box, LP/MIP and smooth
> nonlinear solver workers. Linux, stdio transport; build and register workers
> before connecting. [Guide](https://github.com/dietmarwo/optimization-jobs/blob/main/ai-context.md).

Actual installed-server command:

```text
/absolute/path/to/optimization-mcp --root /absolute/path/to/initialized-node
```

Typical client configuration after building, initializing a node and registering
workers (replace both absolute paths; the JSON layout is client-dependent):

```json
{
  "mcpServers": {
    "optimization-jobs": {
      "command": "/absolute/path/to/optimization-mcp",
      "args": ["--root", "/absolute/path/to/initialized-node"]
    }
  }
}
```

The [official Registry package guide](https://modelcontextprotocol.io/registry/package-types)
now documents Cargo packages. The runner crate is published (0.3.0, October
2026), so this distribution route is open; a source checkout alone is not that
registry artifact.
The runner's crate README includes the proposed visible `mcp-name:` token needed
for Cargo ownership verification. It is preparation, not evidence of registration.

Before generating and publishing a `server.json`:

1. Publish and install the intended `optimization-runner` crate version using
   [RELEASING.md](../../RELEASING.md). Verify that the rendered crate README
   contains the visible ownership token. Done for 0.3.0 (22 October 2026):
   `cargo install optimization-runner --locked` installs both binaries, and
   the packaged README carries the `mcp-name:` line; check the rendered
   crates.io page before submitting.
2. Resolve executable selection in the target registry/client. The package is
   `optimization-runner`, but the MCP binary is `optimization-mcp`, and the same
   package also ships `optimization-run`. The inspected
   [2025-12-11 schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json)
   has no explicit package executable field. Do not assume a generic runtime
   hint or the crate name launches the correct binary. Test the generated launch
   command, or use a separately tested MCPB distribution with explicit launch
   configuration. Do not change the existing CLI merely to fit directory metadata.
3. Use the current official publisher/schema to generate metadata for the tested
   distribution, with exact version and stdio transport; supply the initialized
   node path as a required argument. Do not advertise a remote HTTP service.
4. Verify `initialize`, `tools/list`, `get_guide`, worker discovery and one real
   job from a clean client installation. Follow the
   [official publishing quickstart](https://modelcontextprotocol.io/registry/quickstart).

No publishable `server.json` is included because package availability and correct
client executable selection remain unverified. A schema-valid guessed launch
manifest would not be a usable installation. No new npm/PyPI wrapper or public
service is invented for the listing. Registry submission requires a separate
public action by the maintainer.

## Rust optimization directories

For a directory that accepts a published Rust library, the strongest current
entry is the published core of fcmaes-rust:

```markdown
- [dietmarwo/fcmaes-rust](https://github.com/dietmarwo/fcmaes-rust) [[fcmaes-core](https://crates.io/crates/fcmaes-core)] - Native Rust gradient-free optimizers with parallel retry, multi-objective search and quality diversity.
```

Check [awesome-rust's contribution rules](https://github.com/rust-unofficial/awesome-rust/blob/main/CONTRIBUTING.md)
before proposing it. At the review date those rules ask for more than 50 stars
or more than 2,000 downloads as well as usefulness/stability; this pack does not
assert eligibility. A new source-only crate must not be presented as a published
one. Scientific-computing directories may have different requirements.

After their first releases and eligibility checks, possible craft entries are:

```markdown
- [LP-IP-craft](https://github.com/dietmarwo/LP-IP-craft) - Native Rust LP/MIP models, simplex and branch-and-bound, Python bindings and an optimization job worker.
- [SQP-craft](https://github.com/dietmarwo/SQP-craft) - Rust SQP for smooth constrained problems up to 256 variables, with Python bindings and an optimization job worker.
```

## Python and cross-language directories

```markdown
- [fcmaes](https://github.com/dietmarwo/fast-cma-es) - Python gradient-free optimization with native C++ algorithms, parallel retry, multi-objective search and quality diversity.
- [fcmaes & craft optimization tools](https://dietmarwo.github.io/optimization-jobs/) - Python/Rust black-box, LP/MIP and smooth nonlinear solvers, connected by a local MCP/shell job layer.
```

OptunaHub already has a [fcmaes sampler](https://hub.optuna.org/samplers/fcmaes/).
Link the existing entry; do not submit a duplicate. A new Optuna integration for
another backend would require implemented, tested adapter code and compatibility
evidence; none is claimed here.

## Record the outcome

For each submission, keep the target, date, author, proposal URL, decision and
accepted URL. Add accepted listings to [references.md](references.md) as
*directory listings*, not independent performance evaluations. Preserve the
maintainer relationship even when an entry is hosted by a third party.
