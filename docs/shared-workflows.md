# Shared workflows for the related repositories

Two reusable GitHub Actions workflows live here, with the scripts they run. A
repository calls them with a few lines and keeps no copy of the logic. Both
check out `main` of this repository for the scripts; a caller can name
another branch or commit with the `tools-ref` input.

| Workflow | Used by | What it does |
| --- | --- | --- |
| [`docs-site.yml`](../.github/workflows/docs-site.yml) | LP-IP-craft, SQP-craft | Builds a documentation site from the repository's own Markdown and checks its links |
| [`evaluator-checks.yml`](../.github/workflows/evaluator-checks.yml) | thermo-craft, hydro-craft, rail-craft, robotics-control-craft, population-epidemiology | Build, tests, validation, checksums and links of a domain evaluator |

## Documentation site

The site renders the pages a user needs and nothing else. Plans, logs and
evidence stay in the repository; a link to them from a rendered page becomes a
link to the file on GitHub. No file is moved and no canonical file is changed.

A repository adds two files and one workflow:

- `book/book.toml`: the mdBook configuration. `output.html.git-repository-url`
  is required; the builder derives the GitHub links from it.
- `book/SUMMARY.md`: the pages to render, with paths relative to the repository
  root. A page that exists under `book/`, such as `book/introduction.md`, is
  taken from there; its links are written as if it were in the repository root.
- `.github/workflows/docs.yml`:

```yaml
name: Documentation site
on:
  pull_request:
    paths: ['**.md', 'book/**', 'docs/**', 'tutorials/**', '.github/workflows/docs.yml']
  push:
    branches: [main]
    paths: ['**.md', 'book/**', 'docs/**', 'tutorials/**', '.github/workflows/docs.yml']
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: docs-site-${{ github.ref }}
  cancel-in-progress: true
jobs:
  site:
    uses: dietmarwo/optimization-jobs/.github/workflows/docs-site.yml@main
    permissions:
      contents: read
      pages: write
      id-token: write
    with:
      publish: ${{ vars.PUBLISH_DOCS_SITE == 'true' }}
```

Every run checks the relative links of all tracked Markdown files, builds the
site, fails on an mdBook warning, checks every internal link and anchor of the
built pages, and uploads the site as the artifact `docs-site-preview`.

**Publishing is off until the owner turns it on**, as for the ecosystem page:

1. In the repository's settings, under Pages, set the source to "GitHub
   Actions".
2. Create the repository variable `PUBLISH_DOCS_SITE` with the value `true`.

From then on a push to the default branch deploys the site. A pull request
never deploys.

[`scripts/build_docs_site.py`](../scripts/build_docs_site.py) does the work and
runs locally with `mdbook` on the path:

```sh
python ../optimization-jobs/scripts/build_docs_site.py --repo .
```

It stages the listed pages under `target/docs-site/src` and rewrites only the
staged copies:

- A link to a page that is not rendered becomes a GitHub link. A link whose
  target does not exist fails the build before mdBook runs.
- A link to a rendered `README.md` becomes a link to that directory's index
  page. The root `README.md` is rendered as `overview`, because the first page
  of `SUMMARY.md` is the site's index.
- Images that rendered pages show are copied next to them.
- GitHub math (`$...$`, `$$...$$`) becomes MathJax spans. Set
  `mathjax-support = true` in `book.toml` when pages contain math.

## Evaluator checks

The five domain evaluators share one layout, so one workflow covers them. A
caller is:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  checks:
    uses: dietmarwo/optimization-jobs/.github/workflows/evaluator-checks.yml@main
```

The workflow expects a crate whose package name is its command-line tool, a
wheel in `packages/`, `validation/validate.py`, `validation/installed.py` and a
`SHA256SUMS` that lists every tracked file. It runs:

1. `sha256sum --check SHA256SUMS`, and a comparison of the listed files with
   the tracked files, so a new file without an entry fails.
2. `cargo build --release --locked` and `cargo test --release --locked` on
   stable Rust.
3. `validation/validate.py` against the built tool. The script rewrites its
   recorded example and evidence; other bytes than the tracked ones are
   reported as a warning, not as a failure, because reference values from
   numpy and scipy can differ in the last digits between hosts.
4. `validation/installed.py` with the wheel from `packages/`, outside the
   source tree.
5. The relative links of all tracked Markdown files.

It does not run Clippy or rustfmt. A new stable Rust regularly adds lint
findings, and these repositories change rarely; a lint step would fail the
next unrelated pull request.

## Link checker

[`scripts/check_markdown_links.py`](../scripts/check_markdown_links.py) checks
the relative links of a repository's tracked Markdown files: the target must
exist inside the repository, and a fragment on a Markdown target must be one
of its heading anchors. It does not fetch external URLs. `--exclude` skips a
file or directory, for example a copy whose links are relative to another
place.

```sh
python scripts/check_markdown_links.py --root . --exclude crates/optimization-runner/guide
```
