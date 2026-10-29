"""The existing rail model, reused with a direct native-LP/MIP entry point."""

import importlib.util
import json
from pathlib import Path
import numpy as np
from lp_ip_craft import Model, NativeOptions, Options, solve


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
        r = solve(
            model,
            backend="native",
            options=Options(threads=1),
            backend_options=NativeOptions(component_threads=1, time_limit_seconds=30),
        )
        from dataclasses import asdict

        rec = asdict(r)
        rec["relaxed"] = relaxed
        if not relaxed:
            check = rail.assess(data, r.candidate[: len(data["trains"])])
            assert check["feasible"]
            assert (
                abs(check["passenger_minutes"] - oracle["best"]["passenger_minutes"])
                < 1e-6
            )
            rec["domain_check"] = check
        records.append(rec)
    return dict(
        scenario=data,
        enumeration=oracle,
        records=records,
        big_M_rule="upper_i + occupation_i - lower_j, clipped at zero",
    )
