"""Execution and scientific boundaries, with the real command runner."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import run as driver
import support
from compare import compare

SOURCES = Path(os.environ.get("DOMAIN_SOURCES", HERE.parents[2])).resolve()
RUNNER = SOURCES / "optimization-jobs/target/release/optimization-run"


class Contract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.node = self.root / "node"
        if not RUNNER.is_file():
            self.fail("build the real runner; missing binaries are not skipped")
        driver.call([RUNNER, "--root", self.node, "node", "init", "--capacity", 2, "--allow-commands"])

    def tearDown(self):
        self.temp.cleanup()

    def staged(self, name):
        folder = self.root / name
        driver.stage(SOURCES, "hydro-craft", folder)
        return folder

    def test_exit_two_is_data_and_failed_outputs_are_sealed(self):
        folder = self.staged("invalid")
        request = json.loads((folder / "request.json").read_text())
        request["candidates"][0]["parameters"][2] = 2.0
        support.write(folder / "request.json", request)
        job = driver.command_spec(folder, ["wrap_cli.py"], {"result":"result.json", "status":"status.json"})
        driver.execute(folder, job, RUNNER, self.node, "wrapped")
        status = json.loads((folder / "status.json").read_text())
        self.assertEqual(status["cli_exit"], 2)
        self.assertFalse(status["all_complete"])
        folder = self.root / "raw"
        folder.mkdir()
        (folder / "fail.py").write_text("from pathlib import Path\nPath('kept.json').write_text('{}')\nraise SystemExit(2)\n")
        job = driver.command_spec(folder, ["fail.py"], {"kept":"kept.json"})
        with self.assertRaisesRegex(RuntimeError, "failed"):
            driver.execute(folder, job, RUNNER, self.node, "raw")
        self.assertTrue((folder / "kept.json").is_file())

    def test_rejected_cli_is_failure(self):
        folder = self.staged("malformed")
        (folder / "request.json").write_text('{"schema":"bad"}')
        job = driver.command_spec(folder, ["wrap_cli.py"], {"status":"status.json"})
        with self.assertRaisesRegex(RuntimeError, "failed"):
            driver.execute(folder, job, RUNNER, self.node, "malformed")
        self.assertEqual(json.loads((folder / "status.json").read_text())["status"], "wrapper_failed")

    def test_timeout_never_becomes_short_success(self):
        folder = self.root / "timeout"
        folder.mkdir()
        (folder / "sleep.py").write_text("import time\ntime.sleep(10)\n")
        job = driver.command_spec(folder, ["sleep.py"], {}, wall=1)
        with self.assertRaisesRegex(RuntimeError, "timed_out"):
            driver.execute(folder, job, RUNNER, self.node, "timeout")
        self.assertEqual(json.loads((folder / "native.json").read_text())["state"], "timed_out")

    def test_exact_budget_and_worker_count_replay(self):
        for optimizer in ["cmaes", "de"]:
            outputs = []
            for workers in [1,2]:
                folder = self.staged(f"{optimizer}-{workers}")
                job = driver.search_spec(folder, 7, 401, optimizer, workers)
                driver.execute(folder, job, RUNNER, self.node, f"{optimizer}-{workers}")
                best = json.loads((folder / "best.json").read_text())
                self.assertEqual(best["evaluations"], 401)
                self.assertEqual(sum(best["statuses"].values()), 401)
                outputs.append((best, (folder / "history.csv").read_bytes()))
            self.assertEqual(*outputs)

    def test_installed_package_and_wheel_identity(self):
        repo, _, desc = driver.load(SOURCES, "hydro-craft")
        identity = driver.wheel_identity(repo, desc)
        support.installed_identity(identity)
        identity["package_files"]["__init__.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "installed package"):
            support.installed_identity(identity)
        self.assertRaises(ValueError, driver.relative, repo, "../escape")

    def test_work_limit_keeps_unsuccessful_candidates(self):
        folder = self.staged("work-limit")
        case = json.loads((folder / "case.json").read_text())
        case["max_steps"] = 1
        support.write(folder / "case.json", case)
        driver.execute(folder, driver.search_spec(folder, 2, 16, "de", 1), RUNNER, self.node, "work-limited")
        best = json.loads((folder / "best.json").read_text())
        self.assertEqual(best["status"], "no_complete_candidate")
        self.assertIsNone(best["score"])
        self.assertEqual(best["evaluations"], 16)
        self.assertGreater(best["statuses"]["work_limit"], 0)
        p = subprocess.run([sys.executable, "check.py"], cwd=folder, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        checks = json.loads((folder/"check-output/checks.json").read_text())
        self.assertFalse(checks["passed"])

    def test_comparison_rejects_scientific_changes(self):
        compare({"passed":True,"score":1,"seconds":1},{"passed":True,"score":1,"seconds":9})
        with self.assertRaises(ValueError):
            compare({"passed":True,"score":1},{"passed":True,"score":2})
        with self.assertRaises(ValueError):
            compare({"passed":False},{"passed":False})

    def test_campaign_check_keeps_every_failed_row(self):
        folder = self.staged("failed-campaign-check")
        shutil.copyfile(SOURCES / "experiment-craft/examples/campaigns/domain-evaluators/check.py", folder / "campaign_check.py")
        expected = [dict(id=f"de-{seed}", seed=seed, optimizer="de", budget=16) for seed in [1,2]]
        support.write(folder / "expected.json", expected)
        (folder / "winners").mkdir()
        for arm in expected:
            support.write(folder / "winners" / (arm["id"] + ".json"), dict(arm, status="no_complete_candidate"))
        job = driver.command_spec(folder, ["campaign_check.py"], {"checks":"checks.json"})
        job["inputs"] += [dict(path="winners/" + arm["id"] + ".json", file="winners/" + arm["id"] + ".json",
                              bytes=(folder/"winners"/(arm["id"]+".json")).stat().st_size,
                              sha256=support.digest(folder/"winners"/(arm["id"]+".json"))) for arm in expected]
        with self.assertRaisesRegex(RuntimeError, "failed"):
            driver.execute(folder, job, RUNNER, self.node, "failed-check")
        result = json.loads((folder / "checks.json").read_text())
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(not row["passed"] for row in result["rows"]))

    def test_changed_input_cannot_reuse_key(self):
        folder = self.staged("changed-key")
        job = driver.command_spec(folder, ["wrap_cli.py"], {"result":"result.json","status":"status.json"})
        driver.execute(folder, job, RUNNER, self.node, "fixed-key")
        source = folder / "request.json"
        source.write_text(source.read_text() + "\n")
        for item in job["inputs"]:
            if item["path"] == "request.json":
                item.update(sha256=support.digest(source), bytes=source.stat().st_size)
        support.write(folder / "changed-job.json", job)
        with self.assertRaises(RuntimeError):
            driver.call([RUNNER, "--root", self.node, "run", "--spec", folder / "changed-job.json"])
        jobs = driver.call([RUNNER, "--root", self.node, "jobs", "list"])
        self.assertEqual(len(jobs), 1)

    def replay(self, folder, best):
        support.write(folder / "best.json", best)
        return subprocess.run([sys.executable, "check.py"], cwd=folder, capture_output=True, text=True)

    def test_replay_rejects_wrong_model_and_accounting(self):
        folder = self.staged("replay")
        driver.execute(folder, driver.search_spec(folder, 2, 16, "de", 1))
        best = json.loads((folder / "best.json").read_text())
        # The undamaged winner must pass, so each rejection below has one cause.
        p = self.replay(folder, best)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads((folder / "check-output/checks.json").read_text())["passed"])
        for field, value, reason in [("model_sha256", "0"*64, "model hash differs"),
                                     ("evaluations", 17, "invalid search accounting"),
                                     ("budget", 15, "invalid search accounting"),
                                     ("score", best["score"] + 1e-6, "replay or held-out check failed")]:
            p = self.replay(folder, dict(best, **{field: value}))
            self.assertNotEqual(p.returncode, 0, field)
            self.assertIn(reason, p.stderr, field)

    def test_replay_rejects_a_cli_that_evaluated_another_model(self):
        folder = self.staged("other-model")
        driver.execute(folder, driver.search_spec(folder, 2, 16, "de", 1))
        best = json.loads((folder / "best.json").read_text())
        (folder / "binary").rename(folder / "real-binary")
        # Same records, but the CLI reports the hash of a different model.
        (folder / "binary").write_text(
            "#!" + sys.executable + "\nimport json, subprocess, sys\nfrom pathlib import Path\n"
            "p = subprocess.run([str(Path(__file__).with_name('real-binary')), *sys.argv[1:]], capture_output=True, text=True)\n"
            "data = json.loads(p.stdout)\ndata['model_sha256'] = '0' * 64\nprint(json.dumps(data))\nsys.exit(p.returncode)\n")
        (folder / "binary").chmod(0o700)
        p = self.replay(folder, best)
        self.assertNotEqual(p.returncode, 0)
        checks = json.loads((folder / "check-output/checks.json").read_text())
        self.assertFalse(checks["passed"])
        self.assertFalse(checks["model_replayed"])
        self.assertEqual(checks["records"]["nominal"]["status"], "complete")

    def test_symlinked_sibling_checkouts_are_accepted(self):
        parent = self.root / "linked"
        parent.mkdir()
        for name in ["hydro-craft", "thermo-craft", "optimization-jobs"]:
            (parent / name).symlink_to(SOURCES / name, target_is_directory=True)
        repo, descriptor, desc = driver.load(parent, "hydro-craft")
        self.assertEqual(repo, (SOURCES / "hydro-craft").resolve())
        self.assertEqual(desc["name"], "hydro-craft")
        driver.stage(parent, "thermo-craft", self.root / "linked-stage")
        # A link inside a repository that leaves it is still rejected.
        (self.root / "outside.json").write_text("{}")
        inside = self.root / "repo"
        inside.mkdir()
        (inside / "leak.json").symlink_to(self.root / "outside.json")
        self.assertRaises(ValueError, driver.relative, inside, "leak.json")
        for name in ["", "hydro-craft", "../hydro-craft/x", "/hydro-craft/x", ".hidden/x"]:
            self.assertRaises(ValueError, driver.sibling, parent, name)

    def test_saved_hydro_case_is_the_generator_output(self):
        repo = SOURCES / "hydro-craft"
        spec = importlib.util.spec_from_file_location("synthetic", repo / "examples/python/synthetic.py")
        synthetic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(synthetic)
        case = json.loads((repo / "examples/jobs/case.json").read_text())
        self.assertEqual(case["model"], synthetic.observe(synthetic.catchment(synthetic.forcing())))
        self.assertEqual(case["parameters"], synthetic.TRUTH)
        self.assertEqual([b[0] for b in case["bounds"]], [b[0] for b in synthetic.BOUNDS])


if __name__ == "__main__":
    unittest.main()
