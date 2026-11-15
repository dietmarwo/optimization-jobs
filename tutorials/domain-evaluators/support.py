"""Shared deterministic ask/tell execution; domain knowledge lives in adapters."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def blas_identity(requested, libraries):
    """Record the BLAS kernels in use; reject one that differs from the request."""
    loaded = None if libraries is None else sorted(
        {str(lib.get("architecture")) for lib in libraries if lib.get("internal_api") == "openblas"})
    if requested and loaded and loaded != [requested]:
        raise ValueError(f"BLAS kernel {loaded} differs from the requested {requested}")
    return dict(requested_kernel=requested, loaded_kernels=loaded)


def installed_identity(expected):
    """Verify wheel-owned files, not just the installed distribution version."""
    module = importlib.import_module(expected["module"])
    package = Path(module.__file__).parent
    for name, sha in expected["package_files"].items():
        if digest(package / name) != sha:
            raise ValueError("installed package differs from verified wheel: " + name)
    version = importlib.metadata.version(expected["distribution"])
    if version != expected["version"]:
        raise ValueError("installed package version differs from verified wheel")
    return {
        **expected,
        "packages": {n: importlib.metadata.version(n) for n in ["fcmaes", "numpy", "scipy"]},
        "python": sys.version.split()[0],
        "scope": "Wheel bytes verified against SHA256SUMS; installed package files verified against wheel. Host libraries are not snapshotted.",
    }


def search(adapter):
    import numpy as np
    from scipy.optimize import Bounds
    from fcmaes import cmaes, de
    from loguru import logger
    logger.remove()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=Path("case.json"))
    parser.add_argument("--identity", type=Path, default=Path("wheel-identity.json"))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--evals", type=int, required=True)
    parser.add_argument("--optimizer", choices=["cmaes", "de"], default="cmaes")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.evals < 1 or not 1 <= args.workers <= 8 or args.seed < 0:
        raise ValueError("positive evaluation budget, nonnegative seed and 1..8 workers required")
    case = json.loads(args.case.read_text())
    identity = installed_identity(json.loads(args.identity.read_text()))
    try:
        from threadpoolctl import threadpool_info
        libraries = threadpool_info()
    except ImportError:
        libraries = None
    identity["blas"] = blas_identity(os.environ.get("OPENBLAS_CORETYPE"), libraries)
    module = importlib.import_module(identity["module"])
    prepared = module.Prepared(case["model"])
    lower, upper, x0 = adapter.configuration(case)
    bounds = Bounds(lower, upper)
    rng = np.random.default_rng(args.seed)
    popsize = 16
    opt = (cmaes.Cmaes(bounds=bounds, x0=x0, input_sigma=0.3, popsize=popsize,
                      max_evaluations=args.evals, rg=rng,
                      randn=lambda *shape: rng.standard_normal(shape))
           if args.optimizer == "cmaes" else
           de.DE(len(lower), bounds, popsize=popsize, rg=rng))
    counts, evaluations, work, best, history = Counter(), 0, 0, None, []
    stop = "evaluation_budget"
    while evaluations < args.evals:
        population = np.asarray(opt.ask())
        xs = population[:args.evals - evaluations]
        parameters = adapter.decode(xs)
        scores, statuses, steps = prepared.score_matrix(parameters, workers=args.workers, max_steps=case["max_steps"])
        ys = []
        for x, p, score, status, used in zip(xs, parameters, scores, statuses, steps, strict=True):
            evaluations += 1
            counts[status] += 1
            work += used
            if status == "complete":
                if not math.isfinite(score):
                    raise ValueError("complete row has nonfinite score")
                y = float(score)
                if best is None or y < best["score"]:
                    best = dict(score=y, parameters=list(map(float, p)))
            else:
                y = float(adapter.penalty(x))
                if not math.isfinite(y):
                    raise ValueError("nonfinite penalty")
            ys.append(y)
            history.append([evaluations, status, used, y, None if best is None else best["score"]])
        if len(xs) < len(population):
            break
        if opt.tell(ys) != 0:
            stop = "optimizer_stop"
            break
    args.output.mkdir(parents=True, exist_ok=True)
    model_sha256 = hashlib.sha256(canonical(case["model"]).encode()).hexdigest()
    result = dict(model_sha256=model_sha256, schema="domain-evaluator.search/0.1", evaluator=identity["distribution"],
                  seed=args.seed, optimizer=args.optimizer, budget=args.evals,
                  evaluations=evaluations, steps=work, statuses=dict(sorted(counts.items())),
                  termination=stop, status="complete" if best else "no_complete_candidate",
                  **(best or {"score": None, "parameters": None}))
    # Scientific data do not include workers: equal work must match across layouts.
    identity.update(model_sha256=hashlib.sha256(canonical(case["model"]).encode()).hexdigest(),
                    case_sha256=digest(args.case), adapter_sha256=digest(adapter.__file__),
                    support_sha256=digest(__file__), seed=args.seed,
                    workers=args.workers, evaluator_max_steps=case["max_steps"], evaluation_budget=args.evals, optimizer=args.optimizer,
                    optimizer_parallelism="serial ask/tell; native score_matrix population parallelism only")
    write(args.output / "best.json", result)
    write(args.output / "identity.json", identity)
    with (args.output / "history.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["evaluation", "status", "steps", "penalized_score", "best_complete_score"])
        writer.writerows(history)
    print(json.dumps(result, allow_nan=False))
