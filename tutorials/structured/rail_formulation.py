"""The existing rail model, reused with a direct native-LP/MIP entry point."""

import importlib.util
import json
from pathlib import Path
import numpy as np
from lp_ip_craft import Model, NativeOptions, Options, evaluate, solve
from sources import require


def run(preset):
    folder = Path(__file__).resolve().parents[1] / "agentic/rail-traffic"
    spec = importlib.util.spec_from_file_location("maintained_rail", folder / "rail.py")
    rail = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rail)
    data = json.loads((folder / "scenario.json").read_text())
    rail.validate_scenario(data)
    oracle = rail.enumerate_orders(data)
    records = []
    for relaxed in [True, False]:
        artifact, _ = rail.make_model(data, relaxed=relaxed)
        A = artifact["matrix"]
        model = Model(
            objective=artifact["objective"],
            objective_offset=artifact["objective_offset"],
            lower=artifact["variable_lower"],
            upper=artifact["variable_upper"],
            row_lower=[-np.inf if x is None else x for x in artifact["row_lower"]],
            row_upper=artifact["row_upper"],
            indptr=A["indptr"],
            indices=A["indices"],
            values=A["values"],
            kinds=artifact["kinds"],
        )
        options = dict(
            backend="native",
            options=Options(threads=1),
            backend_options=NativeOptions(component_threads=1, time_limit_seconds=30),
        )
        r = solve(model, **options)
        from dataclasses import asdict

        require(r.status == "optimal", (relaxed, r.status))
        # Independent evaluation of the returned point against the model rows.
        check = evaluate(model, r.candidate)
        require(check.feasible_candidate, check)
        rec = asdict(r)
        rec["relaxed"] = relaxed
        rec["independent"] = asdict(check)
        if not relaxed:
            # A first-come, first-served order as a MIP start: a candidate only,
            # not a resumed search; the optimum must not depend on it.
            fifo = sorted(
                range(len(data["trains"])),
                key=lambda i: (data["trains"][i]["planned"], data["trains"][i]["id"]),
            )
            start = rail.encode(data, rail.schedule_order(data, fifo))
            warm = solve(model, start=start, **options)
            require(warm.status == "optimal", warm.status)
            require(
                abs(warm.evaluation.objective - r.evaluation.objective) < 1e-6,
                (warm.evaluation.objective, r.evaluation.objective),
            )
            rec["fifo_start"] = dict(
                order=fifo,
                start_objective=asdict(evaluate(model, start))["objective"],
                warm_start_status=warm.backend.start_status,
                objective=warm.evaluation.objective,
                nodes=warm.nodes,
            )
        if not relaxed:
            check = rail.assess(data, r.candidate[: len(data["trains"])])
            require(check["feasible"])
            require(
                (
                    abs(
                        check["passenger_minutes"] - oracle["best"]["passenger_minutes"]
                    )
                    < 1e-6
                )
            )
            rec["domain_check"] = check
        records.append(rec)
    # The relaxation is a lower bound on the passenger-minute objective.
    require(
        records[0]["evaluation"]["objective"]
        <= records[1]["evaluation"]["objective"] + 1e-6,
        "the relaxation exceeds the MIP optimum",
    )
    return dict(
        scenario=data,
        enumeration=oracle,
        records=records,
        big_M_rule="upper_i + occupation_i - lower_j, clipped at zero",
    )
