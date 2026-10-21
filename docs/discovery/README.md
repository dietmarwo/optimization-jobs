# Publishing the optimization ecosystem's discovery entry points

The public entry point is **Optimization tools for AI agents — fcmaes & craft**,
at <https://dietmarwo.github.io/optimization-jobs/> after Pages is enabled and
deployed. The existing [ai-context.md](../../ai-context.md) remains the canonical
solver-selection and operating guide, including the copy returned by MCP
`get_guide`. The landing page is a short route into it, not another API manual.

**Priority: release before outreach.** Follow the
[release-first sequence](release-first.md) before contacting the author of
the OptunaHub integration or asking others to try the ecosystem. It lists the registry inventory, release
gates and the compatibility example to prepare.

## What is in the repositories

- Prominent links in both fcmaes repository READMEs, their registry README
  sources, and the LP-IP-craft and SQP-craft READMEs.
- A static, accessible page with concrete problem classes, installation
  availability, constraints, tutorial links and a third-party reference.
- One [catalog](../../site/catalog.json) for the page's five project cards,
  JSON-LD source-code metadata, downloadable JSON, and `llms.txt` navigation.
- Package URL metadata and keywords, plus links in published-crate README
  sources. These become public registry metadata on the next release.
- [Directory submission text](directory-submissions.md), an
  [evidence index](references.md), and an issue form for independent evaluations.

No package, directory listing or independent benchmark is created merely by
merging these files. The sections below distinguish local preparation from
the remaining public actions. Search engines and agents may discover these
links; indexing and selection are not guaranteed. `llms.txt` is an optional
navigation aid, not a universal agent-discovery standard.

## 1. Deploy the landing page before advertising its URL

Build locally with Python 3.11 or newer; this requires no external packages:

```sh
python3 scripts/build_site.py
python3 -m http.server 8000 --directory target/site
```

Open `http://localhost:8000/`. The build validates the catalog, HTML anchors,
local resources, canonical URL and structured project list. It produces
`index.html`, `style.css`, `catalog.json`, `llms.txt`, `sitemap.xml` and
`.nojekyll`. It does not call the network or rewrite the agent guide.

Deployment sequence:

1. The `Ecosystem discovery site` workflow builds a downloadable preview
   (artifact `ecosystem-site-preview`) on pull requests and on main.
2. In this repository's **Settings → Pages**, select **GitHub Actions** as
   the publishing source. In **Settings → Secrets and variables → Actions →
   Variables**, set `PUBLISH_ECOSYSTEM_SITE` to `true`.
3. Run `Ecosystem discovery site` on `main` from Actions. The workflow deploys
   through `github-pages`; future changes to the site sources deploy on main.
4. Verify the public homepage, `/catalog.json`, `/llms.txt` and `/sitemap.xml`
   under `/optimization-jobs/`. Check the guide and three job tutorials.
5. The sibling READMEs and package metadata already link the overview; the
   direct GitHub guide links next to it work while deployment is pending.

Forks build previews but do not deploy automatically. To host a fork, update
the catalog URL, repository links and deployment repository guard first.
For a custom domain, also change the canonical URL in the catalog and configure
Pages DNS. Generated output belongs in `target/site`, not in git.

The sitemap lists this page; submit it to a search engine's webmaster console
only after the page is live, if desired. A `robots.txt` in a project subdirectory
would not control the domain's crawlers, so this site does not pretend to supply
one. Follow GitHub's [custom-workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## 2. Set GitHub About fields and topics

These are repository settings; a commit cannot change them. Use each
entry's `summary` and `topics` in [site/catalog.json](../../site/catalog.json).
Use the existing project documentation homepage for the two fcmaes repositories;
use the ecosystem URL for optimization-jobs and its project anchors for the two
craft repositories. For example, after deployment:

```sh
gh repo edit dietmarwo/optimization-jobs \
  --description 'Durable optimization jobs for AI agents: local Rust runner, worker SDK and MCP server with a shared CPU budget.' \
  --homepage https://dietmarwo.github.io/optimization-jobs/ \
  --add-topic optimization --add-topic mcp --add-topic mcp-server \
  --add-topic ai-agents --add-topic rust --add-topic job-scheduler \
  --add-topic parallel-computing --add-topic operations-research
```

Apply the corresponding catalog entry to each sibling. Keep useful existing
topics; `--add-topic` adds rather than replaces. GitHub permits 20 topics, so
review the combined set first. Spell out *linear programming*, *nonlinear
optimization* and *black-box optimization* in descriptions; `NLP` alone is
ambiguous in an AI search. The word “jobs” alone can also mean employment.

| Repository | Homepage setting |
| --- | --- |
| fast-cma-es | https://dietmarwo.github.io/fast-cma-es/ |
| fcmaes-rust | https://dietmarwo.github.io/fcmaes-rust/ |
| LP-IP-craft | https://dietmarwo.github.io/optimization-jobs/#LP-IP-craft |
| SQP-craft | https://dietmarwo.github.io/optimization-jobs/#SQP-craft |
| optimization-jobs | https://dietmarwo.github.io/optimization-jobs/ |

## 3. Release accurate package metadata

Availability recorded in the catalog on 2026-10-21:

| Repository | Already published | Still source-only |
| --- | --- | --- |
| fast-cma-es | PyPI `fcmaes` | Changes after its latest release |
| fcmaes-rust | crates.io `fcmaes-core`, PyPI `fcmaes-rust` | Job worker, surrogate and other internal crates |
| LP-IP-craft | None recorded | Library crates, Python distribution, worker |
| SQP-craft | None recorded | Library crates, Python distribution, worker |
| optimization-jobs | None recorded | API crate, runner/MCP crate |

Use each repository's `RELEASING.md` and existing tested release workflows.
The discovery changes touched no package version, release tag, dependency pin,
publication permission or solver behavior. Do not mark a package published just
because a workflow or crates.io URL exists in a README.

For the next release, inspect the built wheel's metadata/README and Cargo package
README, then check the rendered PyPI/crates.io pages, documentation URLs and
examples after publication. Update the catalog's availability fields and
`availability_checked` date only after verifying real package installation.
Core libraries and source-only workers must remain distinguishable.

## 4. Prepare directory entries and genuine independent evidence

The [submission pack](directory-submissions.md) contains concise text and the
remaining eligibility checks for the MCP Registry and Rust directories. It does
not claim those entries have been accepted. Read each directory's current rules
before sending a contribution; avoid duplicate or irrelevant listings.

The [reference index](references.md) records one verified outside integration,
its author, scope and limits. Add further references only after reading the
actual work. A maintainer-written post on another host is still maintainer
evidence. A package page is distribution evidence, not independent evaluation.

For useful external reproductions, provide a pinned revision, one command to run,
input provenance, raw results including failures, and the baseline's exact
configuration. The repository's `Independent evaluation or integration` issue
form captures these details. Do not ask for a predetermined favorable result.

## Maintenance and discovery checks

Keep the catalog aligned with the live READMEs and agent guides when package
availability or capabilities change. Do not copy benchmark rankings into the
landing page. API schema/model/resource details come from runtime discovery.

After deployment and after major releases, record results for neutral queries
such as `parallel black-box optimization Python`, `Rust nonlinear optimization`,
`MCP mathematical optimization jobs` and `mixed integer optimization Rust`.
Use a fresh search context without project names; then repeat with names as a
control. Record engine, date, query, result positions and URLs. A missed result
in one query is not evidence that a repository is globally unindexed. The
useful outcome is discoverability plus successful installation and problem
matching, not just a higher keyword count.
