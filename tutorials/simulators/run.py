#!/usr/bin/env python3
"""Run simulator-owned lessons directly or through existing command jobs."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())
ORDER = [c for c in CATALOG if c != "X1"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def call(argv, timeout=3600):
    p = subprocess.run(
        list(map(str, argv)), capture_output=True, text=True, timeout=timeout
    )
    if p.returncode:
        raise RuntimeError(p.stderr[-2000:] + p.stdout[-1000:])
    return json.loads(p.stdout)


def packages():
    return {
        name: importlib.metadata.version(name)
        for name in [
            "crn-craft",
            "fcmaes-rust",
            "lp-ip-craft",
            "sqp-craft",
            "numpy",
            "scipy",
        ]
    }


def source_identity(sources):
    rows = {}
    for repo in [
        "CRN-craft",
        "CFD-craft",
        "optimization-jobs",
        "experiment-craft",
        "fcmaes-rust",
        "LP-IP-craft",
        "SQP-craft",
        "fast-cma-es",
    ]:
        p = subprocess.run(
            ["git", "-C", str(sources / repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        rows[repo] = dict(commit=p.stdout.strip() if p.returncode == 0 else None)
    return rows


def binary_options(args, sources):
    defaults = {
        "crn_binary": sources / "CRN-craft/target/release/crn-craft",
        "ode_binary": sources
        / "CRN-craft/integrations/diffsol/target/release/crn-diffsol",
        "reference_binary": sources
        / "fcmaes-rust/tutorials/oscillator-topology-search/target/release/examples/crn_reference",
        "cfd_binary": sources / "CFD-craft/target/release/cfd-craft",
        "cfd_worker": sources
        / "CFD-craft/integrations/fcmaes-cfd-worker/target/release/fcmaes-cfd-worker",
        "runner": sources / "optimization-jobs/target/release/optimization-run",
    }
    return {
        key: Path(getattr(args, key, None) or value).resolve()
        for key, value in defaults.items()
    }


def entry_argv(sources, chapter, preset, output, bins, threads=1):
    entry = sources / CATALOG[chapter]["repository"] / "tutorials/optimization/run.py"
    argv = [
        str(entry),
        chapter,
        "--preset",
        preset,
        "--output",
        str(output),
        "--threads",
        str(threads),
    ]
    if chapter[0] == "F":
        argv += ["--binary", str(bins["cfd_binary"])]
        if chapter == "F1":
            argv += [
                "--worker",
                str(bins["cfd_worker"]),
                "--runner",
                str(bins["runner"]),
            ]
    if chapter == "C4":
        argv += ["--binary", str(bins["crn_binary"])]
    if chapter == "C2":
        argv += ["--ode-binary", str(bins["ode_binary"])]
    if chapter == "C3":
        argv += ["--reference-binary", str(bins["reference_binary"])]
    return argv


def command_spec(sources, chapter, preset, folder, bins, threads=1, layout=None):
    files = []
    for repo, relatives in {
        "CRN-craft": ["tutorials/optimization", "models/examples", "models/rules"],
        "CFD-craft": [
            "tutorials/optimization",
            "tutorials/common.py",
            "validation/check_fields.py",
            "cases/verification",
        ],
        "optimization-jobs": ["tutorials/simulators"],
    }.items():
        for rel in relatives:
            p = sources / repo / rel
            files.extend(
                [p]
                if p.is_file()
                else [
                    q
                    for q in p.rglob("*")
                    if q.is_file() and q.suffix in {".py", ".json"}
                ]
            )
    argv = entry_argv(sources, chapter, preset, "lesson-output", bins, threads)
    for flag in [
        "--binary",
        "--worker",
        "--runner",
        "--ode-binary",
        "--reference-binary",
    ]:
        if flag in argv:
            files.append(Path(argv[argv.index(flag) + 1]))
    slots = threads
    if layout:
        outer, inner, tasks, slots = layout
        argv = [
            str(HERE / "layout.py"),
            "--entry",
            str(sources / "CRN-craft/tutorials/optimization/run.py"),
            "--preset",
            preset,
            "--output",
            "lesson-output",
            "--outer",
            str(outer),
            "--inner",
            str(inner),
            "--tasks",
            str(tasks),
            "--cpu-slots",
            str(slots),
        ]
    identity = dict(
        argv=argv,
        files={str(p): digest(p) for p in sorted(set(files))},
        packages=packages(),
        repositories=source_identity(sources),
        scope="Trusted sibling checkouts hashed at launch; installed packages version-checked. Keep them fixed during execution; this is not a hermetic filesystem snapshot.",
    )
    (folder / "source.json").write_text(json.dumps(identity, indent=2) + "\n")
    (folder / "execute.py").write_bytes((HERE / "execute.py").read_bytes())
    return dict(
        schema_version="execution.command/0.1",
        argv=[sys.executable, "execute.py"],
        env=dict(
            PYTHONPATH=os.environ.get("PYTHONPATH", ""),
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            MPLBACKEND="Agg",
        ),
        resources=dict(cpu_slots=slots),
        limits=dict(wall_seconds=1800, grace_seconds=2),
        replay="never",
        inputs=[
            dict(
                path=name,
                file=name,
                bytes=(folder / name).stat().st_size,
                sha256=digest(folder / name),
            )
            for name in ["source.json", "execute.py"]
        ],
        outputs=[
            dict(
                name="summary",
                path="summary.json",
                required=True,
                max_bytes=33554432,
            ),
            dict(
                name="evidence", path="evidence.zip", required=True, max_bytes=67108864
            ),
        ],
    )


def add_binary_arguments(parser):
    for option in [
        "crn-binary",
        "ode-binary",
        "reference-binary",
        "cfd-binary",
        "cfd-worker",
        "runner",
    ]:
        parser.add_argument("--" + option, type=Path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chapter", choices=ORDER + ["all"], default="all")
    p.add_argument("--sources", type=Path, default=HERE.parents[2])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    p.add_argument("--command-jobs", action="store_true")
    p.add_argument("--threads", type=int, default=1)
    add_binary_arguments(p)
    args = p.parse_args()
    if not 1 <= args.threads <= 8:
        raise ValueError("threads must be in 1..8")
    sources = args.sources.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bins = binary_options(args, sources)
    node = out / "node"
    if args.command_jobs:
        call(
            [
                bins["runner"],
                "--root",
                node,
                "node",
                "init",
                "--capacity",
                args.threads,
                "--allow-commands",
            ]
        )
    rows = []
    for chapter in ORDER if args.chapter == "all" else [args.chapter]:
        folder = out / chapter
        start = time.perf_counter()
        row = dict(chapter=chapter, passed=False)
        try:
            if args.command_jobs:
                folder.mkdir()
                spec = command_spec(
                    sources, chapter, args.preset, folder, bins, args.threads
                )
                spec["request_key"] = "simulator-tutorial-" + chapter
                (folder / "job.json").write_text(json.dumps(spec, indent=2) + "\n")
                native = call(
                    [
                        bins["runner"],
                        "--root",
                        node,
                        "run",
                        "--spec",
                        folder / "job.json",
                    ]
                )
                row["native_handle"] = native
                if native["state"] != "completed":
                    raise RuntimeError("native command " + native["state"])
                for output, filename in [
                    ("summary", "summary.json"),
                    ("evidence", "evidence.zip"),
                ]:
                    call(
                        [
                            bins["runner"],
                            "--root",
                            node,
                            "jobs",
                            "collect",
                            native["id"],
                            output,
                            "--destination",
                            folder / filename,
                        ]
                    )
            else:
                p = subprocess.run(
                    [
                        sys.executable,
                        *entry_argv(
                            sources, chapter, args.preset, folder, bins, args.threads
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                (out / (chapter + ".stdout.log")).write_text(p.stdout)
                (out / (chapter + ".stderr.log")).write_text(p.stderr)
                if p.returncode:
                    raise RuntimeError("tutorial exit " + str(p.returncode))
            summary = json.loads((folder / "summary.json").read_text())
            if summary.get("chapter") != chapter or summary.get("passed") is not True:
                raise ValueError("tutorial summary failed its checks")
            row["passed"] = True
        except Exception as error:
            row["error"] = str(error)
        row["seconds"] = time.perf_counter() - start
        rows.append(row)
        (out / "summary.json").write_text(
            json.dumps(
                dict(passed=all(r["passed"] for r in rows), chapters=rows), indent=2
            )
            + "\n"
        )
    print(json.dumps(rows, indent=2))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
