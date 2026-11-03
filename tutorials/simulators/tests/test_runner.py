"""Runner, layout and figure boundaries of the simulator series."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load("run")


def git(path, *argv):
    subprocess.run(
        ["git", "-C", str(path), *argv],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "PATH": "/usr/bin:/bin",
        },
    )


class Runner(unittest.TestCase):
    def test_lessons_write_no_bytecode_into_checkouts(self):
        self.assertEqual(run.child_environment()["PYTHONDONTWRITEBYTECODE"], "1")
        with tempfile.TemporaryDirectory() as temp:
            sources = Path(temp) / "sources"
            for repo, rel in [
                ("CRN-craft", "tutorials/optimization/run.py"),
                ("CFD-craft", "tutorials/optimization/run.py"),
                ("optimization-jobs", "tutorials/simulators/run.py"),
            ]:
                (sources / repo / rel).parent.mkdir(parents=True)
                (sources / repo / rel).write_text("")
            binary = Path(temp) / "crn-craft"
            binary.write_bytes(b"binary")
            bins = dict(crn_binary=binary)
            folder = Path(temp) / "C4"
            folder.mkdir()
            original = run.packages
            run.packages = lambda: {}
            try:
                spec = run.command_spec(sources, "C4", "smoke", folder, bins)
            finally:
                run.packages = original
            self.assertEqual(spec["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(spec["replay"], "never")
            staged = (folder / "source.json").read_text()
            self.assertIn(str(binary), staged)

    def test_source_identity_reports_a_modified_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "CRN-craft"
            repo.mkdir()
            git(repo, "init", "-q")
            (repo / "a.txt").write_text("a\n")
            git(repo, "add", "a.txt")
            git(repo, "commit", "-q", "-m", "a")
            clean = run.source_identity(Path(temp))["CRN-craft"]
            self.assertFalse(clean["modified"])
            self.assertIsNone(clean["diff_sha256"])
            (repo / "a.txt").write_text("b\n")
            changed = run.source_identity(Path(temp))["CRN-craft"]
            self.assertTrue(changed["modified"])
            self.assertEqual(changed["commit"], clean["commit"])
            self.assertIsNotNone(changed["diff_sha256"])
            self.assertIsNone(run.source_identity(Path(temp))["CFD-craft"]["commit"])


class Figures(unittest.TestCase):
    def test_missing_fidelity_comparison_is_not_zero_change(self):
        try:
            plot = load("plot")
        except ModuleNotFoundError as error:
            self.skipTest(str(error))
        rows = plot.f3_bars(
            [
                dict(
                    relative_energy_grid_change=None,
                    supported_at_requested_fidelity=False,
                ),
                dict(
                    relative_energy_grid_change=0.05,
                    supported_at_requested_fidelity=False,
                ),
                dict(
                    relative_energy_grid_change=0.05,
                    supported_at_requested_fidelity=True,
                ),
            ]
        )
        self.assertEqual(rows[0][0], None)
        self.assertEqual(
            [label for _, label in rows[1:]], ["not supported", "supported"]
        )


if __name__ == "__main__":
    unittest.main()
