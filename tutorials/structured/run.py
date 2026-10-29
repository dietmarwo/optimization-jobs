#!/usr/bin/env python3
"""Run the twenty structured lessons directly or through trusted command jobs."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sources import require  # noqa: E402

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())
CHAPTERS = {
    key: (repo, slug) for repo, items in CATALOG.items() for key, slug in items.items()
}
ORDER = (
    [f"LP{i}" for i in range(1, 11)]
    + [f"SQP{i}" for i in range(1, 7)]
    + [f"X{i}" for i in range(1, 5)]
)


def checkout(sources, repo):
    """The sibling checkout of ``repo``, matched case-insensitively."""
    path = sources / repo
    if not path.exists() and sources.is_dir():
        matches = [p for p in sources.iterdir() if p.name.casefold() == repo.casefold()]
        if len(matches) == 1:
            return matches[0]
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def call(argv):
    r = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:] + r.stdout[-500:])
    return json.loads(r.stdout)


def environment(sources):
    versions = {}
    for package in [
        "lp-ip-craft",
        "sqp-craft",
        "fcmaes-rust",
        "pykep-rust",
        "numpy",
        "scipy",
        "matplotlib",
    ]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    revisions = {}
    for repo in CATALOG:
        p = checkout(sources, repo)
        head = subprocess.run(
            ["git", "-C", str(p), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
        )
        diff = subprocess.run(
            ["git", "-C", str(p), "diff", "HEAD", "--"], capture_output=True
        )
        status = subprocess.run(
            ["git", "-C", str(p), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
        )
        if head.returncode or diff.returncode or status.returncode:
            # Not a usable git checkout: record that instead of an empty hash.
            revisions[repo] = dict(
                commit=None, error=(head.stderr or "git failed")[-300:]
            )
            continue
        revisions[repo] = dict(
            commit=head.stdout.strip(),
            tracked_diff_sha256=hashlib.sha256(diff.stdout).hexdigest(),
            clean=not status.stdout,
            status_sha256=hashlib.sha256(status.stdout).hexdigest(),
        )
    return dict(
        python=sys.version,
        executable=sys.executable,
        packages=versions,
        repositories=revisions,
        reference_binaries={
            "truss_replay": dict(
                path=os.environ["TRUSS_REPLAY_BIN"],
                sha256=digest(os.environ["TRUSS_REPLAY_BIN"]),
            )
        }
        if os.environ.get("TRUSS_REPLAY_BIN")
        else {},
    )


def command_spec(sources, chapter, preset, folder):
    repo, slug = CHAPTERS[chapter]
    entry = checkout(sources, repo) / "tutorials" / slug / "run.py"
    # Frozen identity of scripts/data that may be read outside the command workdir.
    watched = [entry]
    for owner in ["LP-IP-craft", "SQP-craft", "fcmaes-rust", "optimization-jobs"]:
        for rel in [
            "tutorials/_support",
            "tutorials/structured-support",
            "tutorials/structured",
        ]:
            base = checkout(sources, owner) / rel
            if base.exists():
                watched.extend(
                    p
                    for p in base.rglob("*")
                    if p.is_file() and p.suffix in [".py", ".json"]
                )
    for rel in [
        "SQP-craft/tutorials/job-api/decay.csv",
        "SQP-craft/examples/orbit_transfer.py",
        "optimization-jobs/tutorials/agentic/rail-traffic/rail.py",
        "optimization-jobs/tutorials/agentic/rail-traffic/scenario.json",
        "LP-IP-craft/benchmarks/spoc4_matching.py",
        "LP-IP-craft/benchmarks/spoc4-025/data/matching-i.txt",
        "LP-IP-craft/benchmarks/spoc4-025/data/matching-ii.txt",
        "fcmaes-rust/tutorials/truss-sizing/results/publication/sections.csv",
        "fcmaes-rust/tutorials/truss-sizing/results/publication/so/best_members.csv",
    ]:
        owner, _, path = rel.partition("/")
        watched.append(checkout(sources, owner) / path)
    if os.environ.get("TRUSS_REPLAY_BIN"):
        watched.append(Path(os.environ["TRUSS_REPLAY_BIN"]).resolve())
    manifest = dict(
        entry=str(entry),
        preset=preset,
        files={str(p): digest(p) for p in watched},
        scope="Trusted checkout identity at launch; installed libraries and undeclared reads are not a filesystem sandbox.",
    )
    (folder / "source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    script = HERE / "execute.py"
    (folder / "execute.py").write_bytes(script.read_bytes())
    inputs = [
        dict(
            path=name,
            file=name,
            bytes=(folder / name).stat().st_size,
            sha256=digest(folder / name),
        )
        for name in ["execute.py", "source.json"]
    ]
    env = {
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MPLBACKEND": "Agg",
        # The entries import siblings from here: the tree the manifest hashed.
        "STRUCTURED_SOURCES": str(sources),
    }
    if os.environ.get("TRUSS_REPLAY_BIN"):
        env["TRUSS_REPLAY_BIN"] = os.environ["TRUSS_REPLAY_BIN"]
    return dict(
        schema_version="execution.command/0.1",
        request_key="tutorial." + chapter,
        argv=[sys.executable, "execute.py"],
        env=env,
        resources=dict(cpu_slots=1),
        limits=dict(wall_seconds=600, grace_seconds=2),
        replay="never",
        inputs=inputs,
        outputs=[
            dict(
                name="summary",
                path="lesson-output/summary.json",
                required=True,
                max_bytes=33554432,
            )
        ],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chapter", choices=ORDER + ["all"], default="all")
    p.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    p.add_argument("--sources", type=Path, default=HERE.parents[2])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--runner", type=Path)
    p.add_argument(
        "--timeout",
        type=float,
        default=1800,
        help="seconds per chapter in direct mode (command jobs have their own limit)",
    )
    args = p.parse_args()
    out = args.output.resolve()
    sources = args.sources.resolve()
    if out.exists():
        raise FileExistsError("choose a new output directory")
    out.mkdir(parents=True)
    (out / "environment.json").write_text(
        json.dumps(environment(sources), indent=2) + "\n"
    )
    selected = ORDER if args.chapter == "all" else [args.chapter]
    results = []
    runner = args.runner.resolve() if args.runner else None
    node = out / "node"
    if runner:
        call([runner, "--root", node, "node", "init", "--capacity", "2"])
        call([runner, "--root", node, "node", "commands", "--enable"])
    for chapter in selected:
        started = time.time()
        folder = out / chapter
        record = dict(chapter=chapter, preset=args.preset)
        try:
            repo, slug = CHAPTERS[chapter]
            entry = checkout(sources, repo) / "tutorials" / slug / "run.py"
            if runner:
                folder.mkdir()
                spec = command_spec(sources, chapter, args.preset, folder)
                (folder / "job.json").write_text(json.dumps(spec, indent=2) + "\n")
                native = call(
                    [runner, "--root", node, "run", "--spec", folder / "job.json"]
                )
                record["native_handle"] = native
                if native["state"] != "completed":
                    # Keep the execution record (exit status, signal) of a failure.
                    try:
                        execution = call(
                            [runner, "--root", node, "jobs", "execution", native["id"]]
                        )
                        (folder / "execution.json").write_text(
                            json.dumps(execution, indent=2) + "\n"
                        )
                    except RuntimeError as e:
                        record["execution_record_error"] = str(e)
                    raise RuntimeError("native command " + native["state"])
                call(
                    [
                        runner,
                        "--root",
                        node,
                        "jobs",
                        "collect",
                        native["id"],
                        "summary",
                        "--destination",
                        folder / "summary.json",
                    ]
                )
                (folder / "execution.json").write_text(
                    json.dumps(
                        call(
                            [runner, "--root", node, "jobs", "execution", native["id"]]
                        ),
                        indent=2,
                    )
                    + "\n"
                )
            else:
                child = subprocess.run(
                    [
                        sys.executable,
                        str(entry),
                        "--preset",
                        args.preset,
                        "--output",
                        str(folder),
                    ],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "STRUCTURED_SOURCES": str(sources)},
                    timeout=args.timeout,
                )
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "stdout.log").write_text(child.stdout)
                (folder / "stderr.log").write_text(child.stderr)
                if child.returncode:
                    raise RuntimeError(child.stderr[-1800:])
            summary = json.loads((folder / "summary.json").read_text())
            require(summary["chapter"] == chapter)
            from figures import render

            render(chapter, summary["result"], folder / "figure.png")
            record.update(
                status="passed",
                summary_sha256=digest(folder / "summary.json"),
                figure="figure.png",
            )
        except Exception as e:
            record.update(status="failed", error=str(e))
        record["seconds"] = time.time() - started
        results.append(record)
        (out / "report.json").write_text(json.dumps(results, indent=2) + "\n")
        print(chapter, record["status"], flush=True)
    if any(r["status"] != "passed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
