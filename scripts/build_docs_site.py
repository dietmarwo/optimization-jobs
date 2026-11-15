#!/usr/bin/env python3
"""Build a documentation site with mdBook from a repository's own Markdown.

The repository keeps `book/book.toml` and `book/SUMMARY.md`. SUMMARY.md lists
the pages to render, with paths relative to the repository root; a page that
exists under `book/` (for example `book/introduction.md`) is taken from there.
The canonical files are never changed: the pages are staged under
`target/docs-site/src`, and only the staged copies are rewritten:

- a link to a file that is not rendered becomes a link to that file on GitHub;
- a link to a rendered `README.md` becomes a link to its `index` page; the
  repository's root `README.md` is rendered as `overview`, because the first
  page of SUMMARY.md is the site's index;
- images that rendered pages show are copied next to them;
- GitHub and LaTeX math delimiters become mdBook MathJax spans.

mdBook then builds `target/docs-site/book`, warnings fail the build, and every
internal link and anchor of the built pages is checked. A link whose target
does not exist in the repository fails before mdBook runs.

Requires Python 3.11+ and `mdbook` on PATH (not needed with --prepare-only).
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMAGES = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}
ROOT_README = "overview.md"
SKIPPED_PAGES = {"404.html", "print.html", "toc.html"}

FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")
MARKDOWN_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


def escape_math(tex: str) -> str:
    """Backslash-escape TeX so CommonMark passes it to MathJax unchanged.

    pulldown-cmark treats a backslash before ASCII punctuation as an escape,
    reads ``_``/``*`` as emphasis and applies smart punctuation. Escaping
    every punctuation character makes the rendered text equal the TeX source.
    Blank lines would split the formula across paragraphs, and trailing
    spaces would become ``<br>``, so both are removed.
    """

    lines = [line.rstrip() for line in tex.split("\n")]
    return "\n".join(
        "".join("\\" + c if c in MARKDOWN_PUNCTUATION else c for c in line)
        for line in lines
        if line.strip()
    )


def inline_dollar_end(text: str, start: int) -> int | None:
    """Return the closing ``$`` of inline math opened at ``start``, if any.

    Pandoc's rule: the opening ``$`` is followed by a non-space, the closing
    one is preceded by a non-space and not followed by a digit, and both lie
    on the same line. This keeps prices such as ``$5 and $10`` as text.
    """

    if start + 1 >= len(text) or text[start + 1] in " \t\n$":
        return None
    position = start + 1
    while position < len(text) and text[position] != "\n":
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character == "$":
            if text[position - 1] in " \t":
                return None
            if position + 1 < len(text) and text[position + 1].isdigit():
                return None
            return position
        position += 1
    return None


def convert_math_prose(text: str) -> tuple[str, int]:
    """Rewrite GitHub/LaTeX math delimiters in prose as mdBook MathJax spans.

    Sources keep the delimiters GitHub renders (``$...$``, ``$$...$$``) or
    plain LaTeX (``\\(...\\)``, ``\\[...\\]``). mdBook's MathJax expects
    ``\\\\(...\\\\)`` and ``\\\\[...\\\\]`` with Markdown-escaped contents.
    Inline code spans are copied unchanged.
    """

    output: list[str] = []
    count = 0
    position = 0
    while position < len(text):
        character = text[position]
        if character == "`":
            run = len(text[position:]) - len(text[position:].lstrip("`"))
            closing = re.compile(r"(?<!`)" + "`" * run + r"(?!`)")
            match = closing.search(text, position + run)
            end = match.end() if match else position + run
            output.append(text[position:end])
            position = end
            continue
        display = None
        if text.startswith("$$", position):
            end = text.find("$$", position + 2)
            if end != -1:
                display = (text[position + 2 : end], end + 2, "[", "]")
        elif text.startswith("\\[", position):
            end = text.find("\\]", position + 2)
            if end != -1:
                display = (text[position + 2 : end], end + 2, "[", "]")
        elif text.startswith("\\(", position):
            end = text.find("\\)", position + 2)
            if end != -1 and "\n\n" not in text[position:end]:
                display = (text[position + 2 : end], end + 2, "(", ")")
        elif character == "$":
            end = inline_dollar_end(text, position)
            if end is not None:
                display = (text[position + 1 : end], end + 1, "(", ")")
        if display is not None:
            tex, end, opening, closing_delimiter = display
            output.append(
                f"\\\\{opening}{escape_math(tex.strip())}\\\\{closing_delimiter}"
            )
            count += 1
            position = end
            continue
        if character == "\\":
            output.append(text[position : position + 2])
            position += 2
            continue
        output.append(character)
        position += 1
    return "".join(output), count


def convert_math(document: str) -> tuple[str, int]:
    """Convert math outside fenced code blocks; return text and span count."""

    pieces: list[str] = []
    prose: list[str] = []
    count = 0
    fence: str | None = None

    def flush() -> None:
        nonlocal count
        if prose:
            converted, found = convert_math_prose("".join(prose))
            pieces.append(converted)
            count += found
            prose.clear()

    for line in document.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence is None:
            if match:
                flush()
                fence = match.group("fence")
                pieces.append(line)
            else:
                prose.append(line)
        else:
            pieces.append(line)
            closes = (
                match is not None
                and match.group("fence")[0] == fence[0]
                and len(match.group("fence")) >= len(fence)
                and not line.strip(" \t\r\n" + fence[0])
            )
            if closes:
                fence = None
    flush()
    return "".join(pieces), count


CODE_SPAN = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
INLINE_LINK = re.compile(r"(\]\(\s*<?)([^\s)>]+)(>?(?:\s+\"[^\"]*\")?\s*\))")
REFERENCE = re.compile(r"^(\s{0,3}\[[^]]+\]:\s*<?)([^\s>]+)", re.MULTILINE)
HTML_LINK = re.compile(r"(<(?:a|img)\b[^>]*?\b(?:href|src)=[\"'])([^\"']+)([\"'])")


def map_prose(document: str, change) -> str:
    """Apply `change` to the text outside fenced code and inline code spans."""
    pieces: list[str] = []
    prose: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if not prose:
            return
        text = "".join(prose)
        position = 0
        for span in CODE_SPAN.finditer(text):
            pieces.append(change(text[position:span.start()]))
            pieces.append(span.group(0))
            position = span.end()
        pieces.append(change(text[position:]))
        prose.clear()

    for line in document.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence is None:
            if match:
                flush()
                fence = match.group("fence")
                pieces.append(line)
            else:
                prose.append(line)
        else:
            pieces.append(line)
            if (match is not None and match.group("fence")[0] == fence[0]
                    and len(match.group("fence")) >= len(fence)
                    and not line.strip(" \t\r\n" + fence[0])):
                fence = None
    flush()
    return "".join(pieces)


class Site:
    def __init__(self, repo: Path, branch: str = "main"):
        self.repo = repo.resolve()
        self.book = self.repo / "book"
        self.staging = self.repo / "target" / "docs-site"
        self.source = self.staging / "src"
        self.output = self.staging / "book"
        config = tomllib.loads((self.book / "book.toml").read_text(encoding="utf-8"))
        self.url = config["output"]["html"]["git-repository-url"].rstrip("/")
        self.branch = branch
        summary = (self.book / "SUMMARY.md").read_text(encoding="utf-8")
        self.pages = list(dict.fromkeys(
            unquote(target) for target in re.findall(r"\]\(([^)#\s]+\.md)\)", summary)))
        if not self.pages:
            raise ValueError("book/SUMMARY.md lists no pages")
        if "README.md" in self.pages and ROOT_README in self.pages:
            raise ValueError(f"the root README.md is rendered as {ROOT_README}, which SUMMARY.md also lists")
        self.errors: list[str] = []
        self.images: set[str] = set()

    def origin(self, page: str) -> Path:
        """The canonical file of a page: book/ first, then the repository root."""
        relative = Path(page)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"SUMMARY.md path leaves the repository: {page}")
        for base in (self.book, self.repo):
            if (base / relative).is_file():
                return base / relative
        raise ValueError(f"SUMMARY.md names a missing page: {page}")

    def rewrite(self, page: str, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return url
        fragment = "#" + parsed.fragment if parsed.fragment else ""
        directory = Path(page).parent
        path = unquote(parsed.path)
        joined = Path(path.lstrip("/")) if path.startswith("/") else directory / path
        target = Path(os.path.normpath(joined)).as_posix()
        if target == ".." or target.startswith("../"):
            self.errors.append(f"{page}: link leaves the repository: {url}")
            return url
        absolute = self.repo / target
        if absolute.is_dir() and f"{target}/README.md" in self.pages:
            target = f"{target}/README.md"
        if target in self.pages:
            if target == "README.md":
                target = ROOT_README
            elif Path(target).name == "README.md":
                target = (Path(target).parent / "index.md").as_posix()
            return Path(os.path.relpath(target, directory)).as_posix() + fragment
        if not absolute.exists():
            self.errors.append(f"{page}: missing link target: {url}")
            return url
        if absolute.is_file() and absolute.suffix.lower() in IMAGES:
            self.images.add(target)
            return Path(os.path.relpath(target, directory)).as_posix()
        kind = "tree" if absolute.is_dir() else "blob"
        return f"{self.url}/{kind}/{self.branch}/{target}{fragment}"

    def rewrite_links(self, page: str, text: str) -> str:
        def change(prose: str) -> str:
            for pattern in (INLINE_LINK, HTML_LINK):
                prose = pattern.sub(lambda m: m.group(1) + self.rewrite(page, m.group(2)) + m.group(3), prose)
            return REFERENCE.sub(lambda m: m.group(1) + self.rewrite(page, m.group(2)), prose)
        return map_prose(text, change)

    def prepare(self) -> None:
        if self.staging.exists():
            shutil.rmtree(self.staging)
        self.source.mkdir(parents=True)
        shutil.copy2(self.book / "book.toml", self.staging / "book.toml")
        summary = (self.book / "SUMMARY.md").read_text(encoding="utf-8")
        (self.source / "SUMMARY.md").write_text(
            summary.replace("](README.md)", f"]({ROOT_README})"), encoding="utf-8")
        spans = 0
        for page in self.pages:
            text = self.rewrite_links(page, self.origin(page).read_text(encoding="utf-8"))
            text, count = convert_math(text)
            spans += count
            destination = self.source / (ROOT_README if page == "README.md" else page)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        for image in sorted(self.images):
            destination = self.source / image
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.repo / image, destination)
        if self.errors:
            raise ValueError("\n".join(self.errors))
        print(f"staged {len(self.pages)} pages and {len(self.images)} images; "
              f"converted {spans} math spans")

    def build(self) -> None:
        result = subprocess.run(["mdbook", "build", str(self.staging), "--dest-dir", str(self.output)],
                                capture_output=True, text=True)
        log = result.stdout + result.stderr
        print(log, end="")
        if result.returncode or re.search(r"(^|[^A-Za-z])(WARN|WARNING|Warning|ERROR)", log):
            raise ValueError("mdBook failed or reported warnings")

    def check(self) -> int:
        """Every internal link, image and anchor of the built pages must resolve."""
        pages = {path: Page(path) for path in self.output.rglob("*.html")
                 if path.name not in SKIPPED_PAGES}
        errors, checked = [], 0
        for path, page in pages.items():
            for url in page.links:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or url.startswith(("data:", "javascript:")):
                    continue
                checked += 1
                target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
                if target.is_dir():
                    target = target / "index.html"
                if not target.is_relative_to(self.output.resolve()) or not target.is_file():
                    errors.append(f"{path.relative_to(self.output)}: missing {url}")
                elif parsed.fragment and target in pages \
                        and unquote(parsed.fragment) not in pages[target].ids:
                    errors.append(f"{path.relative_to(self.output)}: missing anchor {url}")
        if errors:
            raise ValueError("\n".join(errors))
        print(f"checked {checked} internal links in {len(pages)} built pages")
        return checked


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for key in ("id", "name"):
            if values.get(key):
                self.ids.add(values[key])
        for key in ("href", "src"):
            if values.get(key) and tag in {"a", "img", "link", "script"}:
                self.links.append(values[key])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository root (default: .)")
    parser.add_argument("--branch", default="main", help="branch that GitHub links name")
    parser.add_argument("--prepare-only", action="store_true",
                        help="stage and rewrite the pages, but do not run mdBook")
    args = parser.parse_args()
    site = Site(args.repo, args.branch)
    site.prepare()
    if not args.prepare_only:
        site.build()
        site.check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
