#!/usr/bin/env python3
"""Execute descriptor-owned evaluators directly or as trusted command jobs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
from support import digest, write, canonical

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())


def call(argv, timeout=180):
    p = subprocess.run(list(map(str, argv)), text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stdout[-2000:] + p.stderr[-2000:])
    return json.loads(p.stdout)


def relative(root, name):
    p = Path(name)
    if p.is_absolute() or not p.parts or any(x.startswith(".") for x in p.parts):
        raise ValueError("unsafe descriptor path: " + name)
    resolved = (root / p).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("descriptor path escapes root")
    return resolved


def sibling(sources, name):
    """Resolve "repository/path": the checkout may be a link, the path stays inside it."""
    repository, _, rest = name.partition("/")
    if not repository or repository.startswith(".") or not rest:
        raise ValueError("unsafe catalog path: " + name)
    repo = (sources / repository).resolve()
    return repo, relative(repo, rest)


def load(sources, evaluator):
    repo, path = sibling(sources, CATALOG["evaluators"][evaluator])
    desc = json.loads(path.read_text())
    if desc.get("schema") != "domain-evaluator.tutorial/0.1" or desc.get("name") != evaluator:
        raise ValueError("unsupported or mismatched evaluator descriptor")
    return repo, path, desc


def wheel_identity(repo, desc):
    wheel = relative(repo, desc["wheel"])
    sums = {}
    for line in (repo / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split(maxsplit=1)
        sums[name.lstrip("*")] = sha
    sha = digest(wheel)
    if sums.get(desc["wheel"]) != sha:
        raise ValueError("wheel differs from SHA256SUMS")
    with zipfile.ZipFile(wheel) as archive:
        prefix = desc["module"] + "/"
        files = {n[len(prefix):]: hashlib.sha256(archive.read(n)).hexdigest()
                 for n in archive.namelist() if n.startswith(prefix) and not n.endswith("/")}
        metadata = archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode()
        version = next(line[9:] for line in metadata.splitlines() if line.startswith('Version: '))
    if not files:
        raise ValueError("wheel contains no package files")
    return dict(distribution=desc["name"], module=desc["module"], version=version,
                wheel=wheel.name, wheel_sha256=sha, package_files=files)


def stage(sources, evaluator, folder, binary=None):
    repo, descriptor_path, desc = load(sources, evaluator)
    folder.mkdir(parents=True, exist_ok=False)
    helpers = sibling(sources, CATALOG["helpers"])[1]
    paths = {"support.py": HERE / "support.py", "optimize.py": relative(repo, desc["optimize"]),
             "case.json": relative(repo, desc["case"]), "evaluator.json": descriptor_path,
             "wrap_cli.py": helpers / "wrap_cli.py", "check.py": helpers / "check.py",
             "binary": Path(binary or repo / "target/release" / desc["cli"]["binary"]),
             "request.json": relative(repo, desc["cli"]["request"])}
    for name, source in paths.items():
        shutil.copyfile(source, folder / name)
    (folder / "binary").chmod(0o700)
    write(folder / "wheel-identity.json", wheel_identity(repo, desc))
    return desc


def command_spec(folder, argv, outputs, workers=1, wall=120):
    inputs = [dict(path=p.name, file=p.name, bytes=p.stat().st_size, sha256=digest(p),
                   executable=p.name == "binary")
              for p in sorted(folder.iterdir()) if p.is_file() and p.name not in {'job.json'}]
    return dict(schema_version="execution.command/0.1", argv=[sys.executable, *argv],
                env={"PYTHONDONTWRITEBYTECODE": "1"}, resources={"cpu_slots": workers},
                limits={"wall_seconds": wall, "grace_seconds": 2}, replay="never", inputs=inputs,
                outputs=[dict(name=name, path=path, required=True, max_bytes=8*1024*1024)
                         for name, path in outputs.items()])


def execute(folder, spec, runner=None, node=None, key=None):
    """Collect sealed outputs before deciding whether execution succeeded."""
    if runner:
        spec["request_key"] = key
        write(folder / "job.json", spec)
        call([runner, "--root", node, "validate", "--spec", folder / "job.json"])
        native = call([runner, "--root", node, "run", "--spec", folder / "job.json"],
                      spec["limits"]["wall_seconds"] + 30)
        write(folder / "native.json", native)
        write(folder / "execution.json", call([runner, "--root", node, "jobs", "execution", native["id"]]))
        write(folder / "command-result.json", call([runner, "--root", node, "result", native["directory"]]))
        errors = []
        for output in spec["outputs"]:
            destination = folder / output["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                call([runner, "--root", node, "jobs", "collect", native["id"], output["name"], "--destination", destination])
            except RuntimeError as error:
                errors.append(str(error))
        repeated = call([runner, "--root", node, "run", "--spec", folder / "job.json"])
        if repeated["id"] != native["id"]:
            raise ValueError("same key returned a different attempt")
        if native["state"] != "completed" or errors:
            raise RuntimeError("command state " + native["state"] + ": " + "; ".join(errors))
        return dict(state=native["state"], same_attempt=True)
    env = {"PATH": "/usr/bin:/bin", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", **spec["env"]}
    p = subprocess.run(spec["argv"], cwd=folder, env=env, capture_output=True, text=True,
                       timeout=spec["limits"]["wall_seconds"])
    (folder / "stdout.log").write_text(p.stdout)
    (folder / "stderr.log").write_text(p.stderr)
    if p.returncode:
        raise RuntimeError("direct exit " + str(p.returncode) + ": " + p.stderr[-2000:])
    for output in spec["outputs"]:
        path = folder / output["path"]
        if not path.is_file() or path.stat().st_size > output["max_bytes"]:
            raise ValueError("missing or oversized output: " + output["name"])
    return dict(state="completed")


def search_argv(seed, evals, optimizer, workers):
    return ["optimize.py", "--seed", str(seed), "--evals", str(evals),
            "--optimizer", optimizer, "--workers", str(workers)]


def search_spec(folder, seed, evals, optimizer, workers):
    return command_spec(folder, search_argv(seed, evals, optimizer, workers),
                        {"best": "best.json", "history": "history.csv", "identity": "identity.json"}, workers)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sources", type=Path, default=HERE.parents[2])
    p.add_argument("--evaluator", choices=list(CATALOG["evaluators"]), default="hydro-craft")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--command-jobs", action="store_true")
    p.add_argument("--runner", type=Path)
    p.add_argument("--binary", type=Path)
    args = p.parse_args()
    if not 1 <= args.workers <= 8:
        raise ValueError("workers must be 1..8")
    sources, out = args.sources.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runner = (args.runner or sources / "optimization-jobs/target/release/optimization-run").resolve() if args.command_jobs else None
    node = out / "node"
    if runner:
        call([runner, "--root", node, "node", "init", "--capacity", args.workers, "--allow-commands"])
    desc = load(sources, args.evaluator)[2]
    preset = desc["presets"][args.preset]
    summary = dict(evaluator=args.evaluator, preset=args.preset, passed=False, evaluation=None, runs=[])
    started = time.perf_counter()
    try:
        folder = out / "evaluation"
        stage(sources, args.evaluator, folder, args.binary)
        spec = command_spec(folder, ["wrap_cli.py"], {"result": "result.json", "status": "status.json"}, args.workers)
        execute(folder, spec, runner, node, "evaluation")
        summary["evaluation"] = json.loads((folder / "status.json").read_text())
        for optimizer in desc["optimizers"]:
            for seed in preset["seeds"]:
                name = f"{optimizer}-{seed}"
                folder = out / name
                row = dict(id=name, passed=False)
                try:
                    stage(sources, args.evaluator, folder, args.binary)
                    execute(folder, search_spec(folder, seed, preset["evals"], optimizer, args.workers), runner, node, name)
                    # A separately sealed replay job consumes the collected winner.
                    check_folder = out / (name + "-check")
                    stage(sources, args.evaluator, check_folder, args.binary)
                    shutil.copyfile(folder / "best.json", check_folder / "best.json")
                    check_spec = command_spec(check_folder, ["check.py"], {"checks": "check-output/checks.json"}, 1)
                    execute(check_folder, check_spec, runner, node, name + "-check")
                    row.update(passed=True, best=json.loads((folder / "best.json").read_text()),
                               checks=json.loads((check_folder / "check-output/checks.json").read_text()))
                except Exception as error:
                    row["error"] = str(error)
                summary["runs"].append(row)
        summary["passed"] = all(row["passed"] for row in summary["runs"]) and bool(summary["runs"])
    except Exception as error:
        summary["error"] = str(error)
    summary["seconds"] = time.perf_counter() - started
    write(out / "summary.json", summary)
    print(json.dumps(dict(passed=summary["passed"], runs=len(summary["runs"]), seconds=summary["seconds"])))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
