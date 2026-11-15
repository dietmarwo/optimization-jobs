#!/usr/bin/env python3
"""Check the relative links of a repository's tracked Markdown files.

Every relative link must name a tracked or existing file or directory inside
the repository, and a fragment on a Markdown target must be one of its
heading anchors (GitHub's rules). External URLs are not fetched. Links inside
fenced code and inline code are ignored. Requires Python 3.10+ and Git.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

MARKDOWN = {".md", ".markdown"}


def without_fences(text: str) -> str:
    """Blank out fenced code blocks, keeping line boundaries."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            lines.append("")
        else:
            lines.append(line if fence is None else "")
    return "\n".join(lines)


def prose(text: str) -> str:
    """Text outside fenced code and inline code spans."""
    # A code span opens and closes with backtick runs of equal length.
    return re.sub(r"(`+)(?!`).*?(?<!`)\1(?!`)", "", without_fences(text))


def links(text: str) -> list[str]:
    """Inline links and images, reference definitions in use, and HTML href/src."""
    source = prose(text)
    refs = {m.group(1).casefold(): m.group(2) for m in re.finditer(
        r"^\s{0,3}\[([^]]+)\]:\s*<?([^\s>]+)>?", source, re.MULTILINE)}
    found = re.findall(r"!?\[[^]\n]*\]\(\s*<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\s*\)", source)
    for match in re.finditer(r"!?\[([^]\n]+)\]\[([^]\n]*)\]", source):
        key = (match.group(2) or match.group(1)).casefold()
        if key in refs:
            found.append(refs[key])
    found.extend(re.findall(r"<(?:a|img)\b[^>]*?\b(?:href|src)=[\"']([^\"']+)[\"']", source))
    return list(dict.fromkeys(html.unescape(value) for value in found))


def anchors(text: str) -> set[str]:
    """GitHub heading slugs with duplicate suffixes, and explicit HTML ids."""
    source = without_fences(text)
    found = set(re.findall(r"\b(?:id|name)=[\"']([^\"']+)[\"']", source))
    counts: dict[str, int] = {}
    headings = []
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.append(match.group(1))
        elif index and re.match(r"^\s{0,3}(?:=+|-+)\s*$", line) and lines[index - 1].strip() \
                and not lines[index - 1].lstrip().startswith(("|", "-", "*", ">", "#")):
            headings.append(lines[index - 1].strip())
    for value in headings:
        value = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", value)
        value = html.unescape(re.sub(r"<[^>]+>", "", value)).lower()
        value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).replace(" ", "-")
        number = counts.get(value, 0)
        counts[value] = number + 1
        found.add(value if number == 0 else f"{value}-{number}")
    return found


def tracked_markdown(root: Path) -> list[Path]:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError("not a Git checkout: " + str(root))
    return [root / name for name in result.stdout.split("\0")
            if name and Path(name).suffix.lower() in MARKDOWN]


def check_file(root: Path, page: Path, cache: dict[Path, set[str]]) -> list[dict]:
    errors = []
    text = page.read_text(encoding="utf-8")

    def page_anchors(path: Path) -> set[str]:
        if path not in cache:
            cache[path] = anchors(path.read_text(encoding="utf-8"))
        return cache[path]

    for url in links(text):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        fragment = unquote(parsed.fragment)
        if not parsed.path:
            if fragment and fragment not in page_anchors(page):
                errors.append({"link": url, "error": "missing anchor in this page"})
            continue
        path = unquote(parsed.path)
        target = (root / path.lstrip("/") if path.startswith("/") else page.parent / path).resolve()
        if not target.is_relative_to(root):
            errors.append({"link": url, "error": "link leaves the repository"})
        elif not target.exists():
            errors.append({"link": url, "error": "missing target"})
        elif fragment and target.is_file() and target.suffix.lower() in MARKDOWN \
                and fragment not in page_anchors(target):
            errors.append({"link": url, "error": "missing anchor in target"})
    return errors


def check(root: Path, exclude: list[str] | None = None) -> dict:
    root = root.resolve()
    cache: dict[Path, set[str]] = {}
    report = {"files": 0, "errors": []}
    for page in tracked_markdown(root):
        relative = page.relative_to(root).as_posix()
        if any(relative == prefix or relative.startswith(prefix.rstrip("/") + "/")
               for prefix in exclude or []):
            continue
        if not page.is_file():
            continue
        report["files"] += 1
        for error in check_file(root, page, cache):
            report["errors"].append({"file": relative, **error})
    report["passed"] = not report["errors"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root (default: .)")
    parser.add_argument("--exclude", action="append", default=[],
                        help="tracked file or directory to skip, relative to the root; repeatable")
    args = parser.parse_args()
    report = check(args.root, args.exclude)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
