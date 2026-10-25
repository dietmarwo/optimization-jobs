#!/usr/bin/env python3
"""Build the static discovery site with Python 3.11+; no network or dependencies."""

from __future__ import annotations

import datetime
import html
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "site"
OUTPUT = ROOT / "target" / "site"
PROJECTS = {"fast-cma-es", "fcmaes-rust", "LP-IP-craft", "SQP-craft", "optimization-jobs",
            "experiment-craft"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def load_catalog() -> dict:
    data = json.loads((SOURCE / "catalog.json").read_text(encoding="utf-8"))
    require(data["schema_version"] == 1, "unsupported catalog schema")
    require(https_url(data["url"]) and data["url"].endswith("/"), "invalid site URL")
    require(https_url(data["guide"]), "invalid guide URL")
    require(https_url(data["comparison"]), "invalid comparison URL")
    datetime.date.fromisoformat(data["availability_checked"])
    entries = data["projects"]
    require(len(entries) == len(PROJECTS) and {p["id"] for p in entries} == PROJECTS,
            "catalog must contain each project once")
    for project in entries:
        for key in ("repository", "guide", "tutorial", "documentation"):
            require(https_url(project[key]), f"invalid {project['id']} {key}")
        for key in ("name", "branch", "summary", "fit", "limits", "availability"):
            require(bool(project[key].strip()), f"empty {project['id']} {key}")
        require(project["languages"] and project["packages"], "missing language or packages")
        require(len(project["topics"]) <= 20, "GitHub allows at most 20 topics")
        for topic in project["topics"]:
            require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", topic) is not None,
                    f"invalid topic: {topic}")
        for package in project["packages"]:
            require(package["status"] in {"published", "source-only"}, "unknown package status")
            if package["status"] == "published":
                require(https_url(package["url"]), "published package needs a URL")
                expected_host = {"PyPI": "pypi.org", "crates.io": "crates.io"}[package["registry"]]
                require(urlsplit(package["url"]).netloc == expected_host, "wrong registry URL")
            else:
                require(package["registry"] == "source" and "url" not in package,
                        "source-only package must not advertise a registry installation")
    return data


def project_html(project: dict) -> str:
    p = {key: html.escape(value, quote=True) for key, value in project.items()
         if isinstance(value, str)}
    package_links = " · ".join(
        f'<a href="{html.escape(package["url"], quote=True)}">'
        f'{html.escape(package["registry"])}: {html.escape(package["name"])}</a>'
        for package in project["packages"] if package["status"] == "published"
    )
    return f'''<article class="project" id="{p['id']}">
  <div>
    <h3><a href="{p['repository']}">{p['name']}</a></h3>
    <p class="project-summary">{p['summary']}</p>
    <nav class="project-nav" aria-label="{p['name']} documentation">
      <a href="{p['guide']}">Agent guide</a>
      <a href="{p['tutorial']}">Tutorial</a>
      <a href="{p['documentation']}">Documentation</a>
    </nav>
    <p class="package-links">{package_links}</p>
  </div>
  <div>
    <p><span class="label">Use for.</span> {p['fit']}</p>
    <p><span class="label">Check first.</span> {p['limits']}</p>
    <p><span class="label">Install.</span> {p['availability']}</p>
  </div>
</article>'''


def structured_data(data: dict) -> str:
    graph = [{
        "@type": "WebSite", "@id": data["url"] + "#website",
        "url": data["url"], "name": data["title"], "description": data["description"],
    }, {
        "@type": "ItemList", "name": "fcmaes and craft optimization repositories",
        "itemListElement": [{
            "@type": "ListItem", "position": i,
            "item": {
                "@type": "SoftwareSourceCode", "name": project["name"],
                "url": project["repository"], "codeRepository": project["repository"],
                "description": project["summary"],
                "programmingLanguage": project["languages"],
                "license": project["repository"] + "/blob/" + project["branch"] + "/LICENSE",
            },
        } for i, project in enumerate(data["projects"], 1)],
    }]
    # Safe inside a script data block even if a future description contains HTML.
    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      ensure_ascii=False, indent=2).replace("<", "\\u003c")


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.refs: list[str] = []
        self.canonicals: list[str] = []
        self.h1_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            require(a["id"] not in self.ids, f"duplicate HTML id: {a['id']}")
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1_count += 1
        if tag == "link" and a.get("rel") == "canonical":
            self.canonicals.append(a.get("href", ""))
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])


def validate_page(output: Path, canonical: str) -> None:
    text = (output / "index.html").read_text(encoding="utf-8")
    require("{{" not in text and "}}" not in text, "unexpanded template token")
    page = Page()
    page.feed(text)
    require(page.h1_count == 1, "page must have one h1")
    require(page.canonicals == [canonical], "wrong canonical URL")
    require(PROJECTS <= page.ids, "project cards missing")
    for ref in page.refs:
        url = urlsplit(ref)
        if url.scheme or url.netloc:
            require(https_url(ref), f"unexpected external URL: {ref}")
            continue
        if not url.path:
            require(not url.fragment or unquote(url.fragment) in page.ids,
                    f"missing HTML anchor: {ref}")
        else:
            path = (output / unquote(url.path)).resolve()
            require(path.is_relative_to(output.resolve()) and path.exists(),
                    f"missing or escaping local resource: {ref}")
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    require(match is not None, "structured data missing")
    ld = json.loads(match[1])
    require(len(ld["@graph"][1]["itemListElement"]) == len(PROJECTS),
            "structured project list incomplete")


def build() -> Path:
    data = load_catalog()
    # Only the fixed generated directory is replaced; source files are never written.
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    substitutions = {key.upper(): html.escape(data[key], quote=True)
                     for key in ("title", "description", "url", "guide", "comparison")}
    substitutions.update({
        "CHECKED": html.escape(data["availability_checked"]),
        "PROJECTS": "\n".join(project_html(p) for p in data["projects"]),
        "JSON_LD": structured_data(data),
    })
    template = (SOURCE / "index.html").read_text(encoding="utf-8")
    rendered = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: substitutions[m[1]], template)
    (OUTPUT / "index.html").write_text(rendered, encoding="utf-8")
    shutil.copyfile(SOURCE / "style.css", OUTPUT / "style.css")
    shutil.copyfile(SOURCE / "catalog.json", OUTPUT / "catalog.json")
    (OUTPUT / ".nojekyll").touch()
    (OUTPUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{html.escape(data["url"])}</loc></url>\n</urlset>\n', encoding="utf-8")
    index = [f'# {data["title"]}', '', f'> {data["description"]}', '',
             '## Start here', '', f'- [Shared selection and operating guide]({data["guide"]})',
             f'- [Human overview]({data["url"]})',
             f'- [Catalog with package availability]({data["url"]}catalog.json)',
             f'- [Comparison with other optimization systems for agents]({data["comparison"]})', '',
             '## Project guides', '']
    index += [f'- [{p["name"]}]({p["guide"]}): {p["summary"]}' for p in data["projects"]]
    index += ['', 'Use runtime worker discovery for schemas, supported models and resource limits.',
              'This text index is a navigation aid, not a guarantee of search or agent discovery.', '']
    (OUTPUT / "llms.txt").write_text('\n'.join(index), encoding="utf-8")
    validate_page(OUTPUT, data["url"])
    return OUTPUT


if __name__ == "__main__":
    print(f"Built and validated {build()}")
