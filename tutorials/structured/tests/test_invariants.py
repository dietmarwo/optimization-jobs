"""Adversarial checks of mathematical and orchestration boundaries."""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from sources import sibling, sources_root  # noqa: E402

SOURCES = sources_root()
sys.path.insert(0, str(sibling("LP-IP-craft", "tutorials", "_support")))
sys.path.insert(0, str(sibling("SQP-craft", "tutorials", "_support")))
from linear_model import LinearModel, exact_cover_bound  # noqa: E402
from numerics import Case  # noqa: E402


def repo(name):
    return sibling(name)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class MathematicalBoundaries(unittest.TestCase):
    def test_exact_certificate_refuses_infeasible_dual(self):
        from fractions import Fraction as F

        self.assertEqual(exact_cover_bound([[1, 1]], [3], [F(1)]), 3)
        with self.assertRaises(ValueError):
            exact_cover_bound([[1, 1]], [3], [F(3, 2)])
        with self.assertRaises(ValueError):
            exact_cover_bound([[1], [1]], [3, 4], [F(1)])

    def test_binary_domain_is_checked_beyond_linear_feasibility(self):
        m = LinearModel()
        m.var("x", kind="binary")
        self.assertTrue(m.check([0.5], relaxation=True)["feasible"])
        self.assertFalse(m.check([0.5])["feasible"])

    def test_duplicate_names_and_unknown_columns_are_rejected(self):
        m = LinearModel()
        m.var("x")
        with self.assertRaises(ValueError):
            m.var("x")
        with self.assertRaises(ValueError):
            m.row("bad", {1: 1})

    def test_wrong_gradient_fails_before_optimization(self):
        from sqp_craft import check_derivatives

        c = Case(
            [-2],
            [2],
            [],
            [],
            lambda x: (x[0] ** 2, []),
            lambda x: (np.array([-2 * x[0]]), np.zeros((0, 1))),
            [1],
        )
        self.assertFalse(check_derivatives(c.spec, c, [1]).passed)
        # The tutorial runner itself must refuse to optimize with it.
        with self.assertRaises(AssertionError):
            c.run()

    def test_wrong_multiplier_does_not_confirm_first_order(self):
        from types import SimpleNamespace

        c = Case(
            [-2],
            [2],
            [1],
            [1],
            lambda x: (x[0] ** 2, [x[0]]),
            lambda x: (2 * x, np.ones((1, 1))),
            [1],
        )
        self.assertTrue(
            c.check([1], SimpleNamespace(constraints=[2], variables=[0]))["first_order"]
        )
        self.assertFalse(
            c.check([1], SimpleNamespace(constraints=[-2], variables=[0]))[
                "first_order"
            ]
        )

    def test_numerical_first_order_need_not_be_a_minimum(self):
        m = load("sqp_models", repo("SQP-craft") / "tutorials/_support/structured.py")
        case = m.well(alpha=0)
        r, record = case.run(start=[0, 0])
        self.assertEqual(record["independent"]["objective"], 1)
        self.assertEqual(case.fun(np.array([1, 1]))[0], 0)

    def test_nonfinite_point_cannot_pass_primal_audit(self):
        c = Case(
            [-2],
            [2],
            [],
            [],
            lambda x: (x[0] ** 2, []),
            lambda x: (2 * x, np.zeros((0, 1))),
            [1],
        )
        with self.assertRaises(ValueError):
            c.check([float("nan")])

    def test_sphere_energy_is_not_ranked_at_an_infeasible_native_point(self):
        from types import SimpleNamespace

        m = load(
            "sphere_models",
            repo("fcmaes-rust") / "tutorials/structured-support/thomson.py",
        )

        def fun(x):
            return 1 / np.linalg.norm(x[:3] - x[3:]), np.sum(
                x.reshape(2, 3) ** 2, axis=1
            )

        case = Case(
            [-1.1] * 6,
            [1.1] * 6,
            [1, 1],
            [1, 1],
            fun,
            lambda x: (np.zeros(6), np.zeros((2, 6))),
            [1, 0, 0, -1, 0, 0],
        )
        native = SimpleNamespace(candidate=[2, 0, 0, -2, 0, 0], multipliers=None)
        raw, points, accepted, projected = m.reported_candidate(
            case, native, case.start
        )
        self.assertFalse(raw["feasible"])
        self.assertAlmostEqual(raw["objective"], 0.25)
        self.assertTrue(projected and accepted["feasible"])
        self.assertAlmostEqual(accepted["objective"], 0.5)
        self.assertFalse(accepted.get("first_order", False))

    def test_battery_counterexample_exposes_relaxation(self):
        m = load("lp_models", repo("LP-IP-craft") / "tutorials/_support/structured.py")
        lp, _ = m.battery_model([0], [0], [-1], 0.9, 1, 1, 0, False)
        ip, _ = m.battery_model([0], [0], [-1], 0.9, 1, 1, 0, True)
        a, _ = lp.run()
        b, _ = ip.run()
        self.assertAlmostEqual(a.evaluation.objective, -0.19)
        self.assertAlmostEqual(b.evaluation.objective, 0)

    def test_shidoku_counter_rejects_conflicting_clues(self):
        m = load("lp_models", repo("LP-IP-craft") / "tutorials/_support/structured.py")
        a = np.zeros((4, 4), int)
        a[0, :2] = 1
        self.assertEqual(m.count_sudoku(a), [])

    def test_equal_rate_limit_and_parameter_symmetry(self):
        m = load("sqp_models", repo("SQP-craft") / "tutorials/_support/structured.py")
        t = np.linspace(0, 4, 9)
        a = m.kinetics_states([1, 1, 1], t)[:, 1]
        np.testing.assert_allclose(a, t * np.exp(-t), atol=1e-7)
        np.testing.assert_allclose(
            m.kinetics_states([1, 0.5, 1.5], t)[:, 1],
            m.kinetics_states([1 / 3, 1.5, 0.5], t)[:, 1],
            atol=1e-10,
        )


class ExecutionBoundaries(unittest.TestCase):
    def test_source_drift_refused_before_entry_runs(self):
        execute = repo("optimization-jobs") / "tutorials/structured/execute.py"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            entry = path / "entry.py"
            entry.write_text("from pathlib import Path\nPath('LAUNCHED').touch()\n")
            (path / "source.json").write_text(
                json.dumps(
                    dict(entry=str(entry), preset="smoke", files={str(entry): "0" * 64})
                )
            )
            r = subprocess.run(
                [sys.executable, str(execute)], cwd=path, capture_output=True, text=True
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("source changed after admission", r.stderr)
            self.assertFalse((path / "LAUNCHED").exists())
            # Positive control: the matching hash launches the entry.
            (path / "source.json").write_text(
                json.dumps(
                    dict(
                        entry=str(entry),
                        preset="smoke",
                        files={
                            str(entry): hashlib.sha256(entry.read_bytes()).hexdigest()
                        },
                    )
                )
            )
            r = subprocess.run(
                [sys.executable, str(execute)], cwd=path, capture_output=True, text=True
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((path / "LAUNCHED").exists())

    def test_occupied_output_is_not_overwritten(self):
        entries = [
            repo("LP-IP-craft") / "tutorials/resource-allocation/run.py",
            repo("SQP-craft") / "tutorials/hanging-chain/run.py",
            repo("fcmaes-rust") / "tutorials/thomson-refinement/run.py",
            repo("optimization-jobs") / "tutorials/solver-choice/run.py",
            repo("optimization-jobs") / "tutorials/rail-formulation/run.py",
            repo("optimization-jobs") / "tutorials/structured/run.py",
        ]
        for entry in entries:
            with (
                self.subTest(entry=entry.parent.name),
                tempfile.TemporaryDirectory() as d,
            ):
                path = Path(d)
                sentinel = path / "keep"
                sentinel.write_text("original")
                r = subprocess.run(
                    [sys.executable, str(entry), "--output", str(path)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("FileExistsError", r.stderr)
                self.assertEqual(sentinel.read_text(), "original")
                self.assertEqual(sorted(p.name for p in path.iterdir()), ["keep"])

    def test_entries_import_siblings_from_structured_sources(self):
        # A sibling tree whose LP support module is broken: the X1 entry must
        # use it, because the command-job manifest hashes that tree.
        with tempfile.TemporaryDirectory() as d:
            farm = Path(d)
            support = farm / "LP-IP-craft/tutorials/_support"
            support.mkdir(parents=True)
            (support / "linear_model.py").write_text(
                "raise ImportError('broken sibling used')\n"
            )
            for name in ["SQP-craft", "fcmaes-rust", "optimization-jobs"]:
                (farm / name).symlink_to(repo(name))
            r = subprocess.run(
                [
                    sys.executable,
                    str(repo("optimization-jobs") / "tutorials/solver-choice/run.py"),
                    "--output",
                    str(farm / "out"),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "STRUCTURED_SOURCES": str(farm)},
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("broken sibling used", r.stderr)

    def test_checks_survive_python_optimize(self):
        # Tutorial checks are explicit raises; -O must not remove them.
        code = (
            "import sys; sys.path[:0] = sys.argv[1:3]\n"
            "from linear_model import require as lp\n"
            "from numerics import require as sqp, Case\n"
            "import numpy as np\n"
            "for check in (lp, sqp):\n"
            "    try:\n"
            "        check(False, 'x')\n"
            "    except AssertionError:\n"
            "        pass\n"
            "    else:\n"
            "        raise SystemExit('check removed')\n"
            "c = Case([-2], [2], [], [], lambda x: (x[0] ** 2, []),\n"
            "         lambda x: (np.array([-2 * x[0]]), np.zeros((0, 1))), [1])\n"
            "try:\n"
            "    c.run()\n"
            "except AssertionError:\n"
            "    print('refused')\n"
        )
        r = subprocess.run(
            [
                sys.executable,
                "-O",
                "-c",
                code,
                str(repo("LP-IP-craft") / "tutorials/_support"),
                str(repo("SQP-craft") / "tutorials/_support"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "refused")


class DriverContract(unittest.TestCase):
    def test_catalog_matches_order_and_entries_exist(self):
        driver = load("driver", HERE / "run.py")
        self.assertEqual(sorted(driver.CHAPTERS), sorted(driver.ORDER))
        self.assertEqual(len(driver.ORDER), 20)
        for chapter, (owner, slug) in driver.CHAPTERS.items():
            with self.subTest(chapter=chapter):
                entry = repo(owner) / "tutorials" / slug / "run.py"
                self.assertTrue(entry.is_file(), entry)
                self.assertTrue((entry.parent / "README.md").is_file())

    def test_command_spec_hashes_the_entry_and_passes_the_sources(self):
        driver = load("driver", HERE / "run.py")
        with tempfile.TemporaryDirectory() as d:
            spec = driver.command_spec(SOURCES, "X1", "smoke", Path(d))
            manifest = json.loads((Path(d) / "source.json").read_text())
        entry = repo("optimization-jobs") / "tutorials/solver-choice/run.py"
        self.assertEqual(Path(manifest["entry"]), entry)
        for module in [
            entry,
            HERE / "solver_choice.py",
            HERE / "sources.py",
            repo("LP-IP-craft") / "tutorials/_support/linear_model.py",
            repo("SQP-craft") / "tutorials/_support/numerics.py",
        ]:
            self.assertIn(str(module), manifest["files"])
        self.assertEqual(spec["env"]["STRUCTURED_SOURCES"], str(SOURCES))


if __name__ == "__main__":
    unittest.main()
