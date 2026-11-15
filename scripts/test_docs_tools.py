#!/usr/bin/env python3
"""Tests for the Markdown link checker and the documentation site builder.

Neither needs mdBook: the site tests stage pages and check hand-written HTML.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from build_docs_site import ROOT_README, Site, convert_math
from check_markdown_links import anchors, check, links


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Repository(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()

    def track(self):
        for argv in (["init", "-q"], ["add", "-A"]):
            subprocess.run(["git", "-C", str(self.root), *argv], check=True, capture_output=True)


class LinkChecker(Repository):
    def test_links_ignore_code_and_include_html_and_references(self):
        text = ("[A](a.md#run) ![I](img/x.png) [B][b] `[C](code.md)`\n"
                "<img src=\"img/y.png\"> <a href=\"z.md\">z</a>\n"
                "[b]: b.md\n```\n[X](fenced.md)\n```\n")
        self.assertEqual(links(text), ["a.md#run", "img/x.png", "b.md", "img/y.png", "z.md"])

    def test_anchors_follow_github_slugs(self):
        text = "# The `run` command!\n## Setup\n## Setup\n```sh\n# not a heading\n```\n<a id=\"own\"></a>\n"
        self.assertEqual(anchors(text), {"the-run-command", "setup", "setup-1", "own"})

    def test_each_kind_of_broken_link_is_reported(self):
        write(self.root / "README.md",
              "# Top\n[ok](docs/a.md#part) [dir](docs) [self](#top) [web](https://example.org/x.md)\n"
              "[gone](docs/missing.md) [anchor](docs/a.md#absent) [here](#nowhere) [out](../outside.md)\n")
        write(self.root / "docs/a.md", "# A\n## Part\n[up](../README.md#top) [code](../src/lib.rs#L3)\n")
        write(self.root / "src/lib.rs", "// code\n")
        write(self.root / "skipped/b.md", "[gone](nothing.md)\n")
        self.track()
        report = check(self.root, ["skipped"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["files"], 2)
        self.assertEqual({(e["file"], e["link"], e["error"]) for e in report["errors"]}, {
            ("README.md", "docs/missing.md", "missing target"),
            ("README.md", "docs/a.md#absent", "missing anchor in target"),
            ("README.md", "#nowhere", "missing anchor in this page"),
            ("README.md", "../outside.md", "link leaves the repository"),
        })
        self.assertTrue(check(self.root, ["skipped", "README.md"])["passed"])

    def test_untracked_files_are_not_checked(self):
        write(self.root / "README.md", "# Top\n")
        self.track()
        write(self.root / "scratch.md", "[gone](nothing.md)\n")
        self.assertTrue(check(self.root)["passed"])


class SiteBuilder(Repository):
    def setUp(self):
        super().setUp()
        write(self.root / "book/book.toml",
              '[book]\ntitle = "T"\nsrc = "src"\n[output.html]\n'
              'git-repository-url = "https://github.com/owner/repo"\n')
        write(self.root / "book/SUMMARY.md",
              "# Summary\n- [Introduction](introduction.md)\n- [Overview](README.md)\n"
              "- [Guide](docs/guide.md)\n- [Tutorials](tutorials/README.md)\n")
        write(self.root / "book/introduction.md", "# Site\n[Overview](README.md) [Guide](docs/guide.md)\n")
        write(self.root / "README.md", "# Repo\n<img src=\"docs/images/banner.png\">\n[Guide](docs/guide.md)\n")
        write(self.root / "docs/images/banner.png", "png")
        write(self.root / "docs/logs/run.md", "# Log\n")
        write(self.root / "tutorials/README.md", "# Tutorials\n## First\n")

    def guide(self, text: str) -> str:
        write(self.root / "docs/guide.md", text)
        site = Site(self.root, "trunk")
        site.prepare()
        return (site.source / "docs/guide.md").read_text(encoding="utf-8")

    def test_links_are_rewritten_only_where_needed(self):
        staged = self.guide(
            "# Guide\n[Top](../README.md#repo) [T](../tutorials/README.md#first) [D](../tutorials)\n"
            "[Log](logs/run.md#log) [Logs](logs) [Web](https://example.org) [Here](#guide)\n"
            "`[Code](logs/run.md)`\n```\n[Fenced](logs/run.md)\n```\n[ref]: logs/run.md\n")
        self.assertIn(f"[Top](../{ROOT_README}#repo)", staged)
        self.assertIn("[T](../tutorials/index.md#first)", staged)
        self.assertIn("[D](../tutorials/index.md)", staged)
        self.assertIn("[Log](https://github.com/owner/repo/blob/trunk/docs/logs/run.md#log)", staged)
        self.assertIn("[Logs](https://github.com/owner/repo/tree/trunk/docs/logs)", staged)
        self.assertIn("[Web](https://example.org) [Here](#guide)", staged)
        self.assertIn("`[Code](logs/run.md)`", staged)
        self.assertIn("[Fenced](logs/run.md)", staged)
        self.assertIn("[ref]: https://github.com/owner/repo/blob/trunk/docs/logs/run.md", staged)

    def test_root_readme_becomes_the_overview_and_images_are_copied(self):
        self.guide("# Guide\n")
        source = self.root / "target/docs-site/src"
        self.assertIn(f"]({ROOT_README})", (source / "SUMMARY.md").read_text())
        self.assertFalse((source / "README.md").exists())
        overview = (source / ROOT_README).read_text()
        self.assertIn('<img src="docs/images/banner.png">', overview)
        self.assertTrue((source / "docs/images/banner.png").is_file())
        self.assertIn(f"[Overview]({ROOT_README})", (source / "introduction.md").read_text())
        self.assertFalse((source / "docs/logs/run.md").exists())
        self.assertEqual((self.root / "README.md").read_text().count("docs/guide.md"), 1)

    def test_missing_targets_and_pages_fail_before_mdbook(self):
        with self.assertRaisesRegex(ValueError, "missing link target: gone.md"):
            self.guide("# Guide\n[Gone](gone.md)\n")
        with self.assertRaisesRegex(ValueError, "leaves the repository"):
            self.guide("# Guide\n[Out](../../elsewhere.md)\n")
        write(self.root / "book/SUMMARY.md", "- [Missing](docs/none.md)\n")
        with self.assertRaisesRegex(ValueError, "missing page"):
            Site(self.root).prepare()

    def test_math_is_converted_outside_code(self):
        text, count = convert_math("Cost $a_i x$ and `$b$`.\n\n$$\nx^2\n$$\n```\n$c$\n```\nPrice $5 and $10.\n")
        self.assertEqual(count, 2)
        self.assertIn("\\\\(a\\_i x\\\\)", text)
        self.assertIn("`$b$`", text)
        self.assertIn("\\\\[x\\^2\\\\]", text)
        self.assertIn("$c$", text)
        self.assertIn("Price $5 and $10.", text)

    def test_built_pages_are_checked_for_links_and_anchors(self):
        self.guide("# Guide\n")
        site = Site(self.root)
        write(site.output / "index.html", '<h1 id="top">T</h1><a href="docs/guide.html#part">g</a>'
                                           '<a href="https://example.org/x">w</a><img src="img/a.png">')
        write(site.output / "docs/guide.html", '<h2 id="part">P</h2><a href="../index.html#top">t</a>')
        write(site.output / "img/a.png", "png")
        write(site.output / "print.html", '<a href="nowhere.html">skipped page</a>')
        self.assertEqual(site.check(), 3)
        write(site.output / "docs/guide.html", '<h2 id="other">P</h2><a href="../gone.html">t</a>')
        with self.assertRaisesRegex(ValueError, "missing anchor docs/guide.html#part"):
            site.check()
        write(site.output / "index.html", '<a href="docs/guide.html">g</a>')
        with self.assertRaisesRegex(ValueError, r"missing \.\./gone\.html"):
            site.check()


if __name__ == "__main__":
    unittest.main()
