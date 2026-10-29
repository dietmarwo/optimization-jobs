"""One workshop story, LP/MIP/SQP/black-box variants with separate references."""

import itertools
from pathlib import Path
import sys
import numpy as np


def run(preset):
    sources = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(sources / "LP-IP-craft/tutorials/_support"))
    sys.path.insert(0, str(sources / "SQP-craft/tutorials/_support"))
    from linear_model import LinearModel
    from numerics import Case, plain
    import fcmaes_rust as fc

    lp = LinearModel("maximize")
    a = lp.var("P", 40, upper=50)
    b = lp.var("Q", 30, upper=80)
    lp.row("machine", {a: 2, b: 1}, upper=100)
    lp.row("labor", {a: 1, b: 1}, upper=80)
    r, A = lp.run()
    assert abs(r.evaluation.objective - 2600) < 1e-6
    candidates = [
        (40 * 7 * p + 30 * 9 * q - 150 * (p > 0) - 150 * (q > 0), p, q)
        for p in range(8)
        for q in range(9)
        if 14 * p + 9 * q <= 100 and 7 * p + 9 * q <= 80
    ]
    reference = max(candidates)
    assert reference == (2160, 3, 6)
    mip = LinearModel("maximize")
    p = mip.var("P_batches", 280, upper=7, kind="integer")
    q = mip.var("Q_batches", 270, upper=8, kind="integer")
    yp = mip.var("P_setup", -150, kind="binary")
    yq = mip.var("Q_setup", -150, kind="binary")
    mip.row("machine", {p: 14, q: 9}, upper=100)
    mip.row("labor", {p: 7, q: 9}, upper=80)
    mip.row("P_link", {p: 1, yp: -7}, upper=0)
    mip.row("Q_link", {q: 1, yq: -8}, upper=0)
    r, B = mip.run()
    assert abs(r.evaluation.objective - 2160) < 1e-6

    def fun(x):
        return -((40 - 0.25 * x[0]) * x[0] + (30 - 0.2 * x[1]) * x[1]), np.array(
            [2 * x[0] + x[1], sum(x)]
        )

    def derivative(x):
        return np.array([0.5 * x[0] - 40, 0.4 * x[1] - 30]), np.array(
            [[2.0, 1], [1, 1]]
        )

    case = Case(
        [0, 0],
        [50, 80],
        [-np.inf, -np.inf],
        [100, 80],
        fun,
        derivative,
        [20, 40],
        linear_rows=[0, 1],
    )
    r, C = case.run()
    assert r.status == "converged" and abs(-r.evaluation.objective - 91000 / 49) < 1e-5
    sizes = np.array([7, 9, 3, 4, 5, 2])
    prices = np.array([40, 30, 22, 18, 25, 35])
    setup = np.array([150, 150, 20, 20, 20, 20])
    machine = np.array([2, 1, 3, 2, 1, 4])
    labor = np.array([1, 1, 2, 3, 2, 1])
    bounds = np.array([4, 4, 3, 3, 3, 3])

    def score(x):
        x = np.rint(x).astype(int)
        units = x * sizes
        profit = float(units @ prices - setup @ (x > 0))
        violation = max(0, float(units @ machine - 100)) + max(
            0, float(units @ labor - 80)
        )
        return -profit if violation == 0 else 1e10 + violation

    feasible = [
        (score(x), x)
        for x in itertools.product(*(range(v + 1) for v in bounds))
        if np.dot(np.array(x) * sizes, machine) <= 100
        and np.dot(np.array(x) * sizes, labor) <= 80
    ]
    exact = min(feasible, key=lambda z: z[0])
    budget = 4000 if preset == "study" else 1000
    six = LinearModel("maximize")
    q = [
        six.var(
            f"batches{j}", sizes[j] * prices[j], upper=int(bounds[j]), kind="integer"
        )
        for j in range(6)
    ]
    active = [six.var(f"setup{j}", -setup[j], kind="binary") for j in range(6)]
    six.row("machine", {q[j]: sizes[j] * machine[j] for j in range(6)}, upper=100)
    six.row("labor", {q[j]: sizes[j] * labor[j] for j in range(6)}, upper=80)
    for j in range(6):
        six.row(f"setup_link{j}", {q[j]: 1, active[j]: -int(bounds[j])}, upper=0)
    mip6, rec6 = six.run()
    assert mip6.status == "optimal" and abs(mip6.evaluation.objective + exact[0]) < 1e-6
    result = fc.optimize_bite(
        score,
        np.zeros(6),
        np.zeros(6),
        bounds.astype(float),
        seed=42,
        max_evaluations=budget,
    )
    x = np.rint(result[0]).astype(int)
    if score(x) > 0:
        x = np.zeros(6, int)
    value = min(0.0, score(x))
    return dict(
        LP=A,
        MIP=B,
        SQP=C,
        six_product_mip=rec6,
        black_box=dict(
            native=plain(result),
            rounded=x,
            best_found_profit=-value,
            enumerated_optimum=-exact[0],
            gap=value - exact[0],
            requested_evaluations=budget,
        ),
        note="Four formulations; descriptive comparison, no shared solver ranking.",
    )
