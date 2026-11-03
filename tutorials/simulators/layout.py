"""One predeclared C1 CPU layout; orchestration is owned by the command runtime."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TASK_SECONDS = 300


def run_one(entry, preset, out, index, inner):
    started = time.perf_counter()
    path = out / f"seed-{index}"
    p = subprocess.run(
        [
            sys.executable,
            str(entry),
            "C1",
            "--preset",
            preset,
            "--output",
            str(path),
            "--threads",
            str(inner),
            "--seed-offset",
            str(index * 100),
        ],
        capture_output=True,
        text=True,
        timeout=TASK_SECONDS,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    path.with_suffix(".stdout.log").write_text(p.stdout)
    path.with_suffix(".stderr.log").write_text(p.stderr)
    summary = (
        json.loads((path / "summary.json").read_text())
        if (path / "summary.json").is_file()
        else None
    )
    return dict(
        index=index,
        seconds=time.perf_counter() - started,
        returncode=p.returncode,
        summary=summary,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--entry", type=Path, required=True)
    p.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--outer", type=int, required=True)
    p.add_argument("--inner", type=int, required=True)
    p.add_argument("--cpu-slots", type=int, required=True)
    p.add_argument("--tasks", type=int, required=True)
    args = p.parse_args()
    if not (
        1 <= args.cpu_slots <= 8
        and 1 <= args.tasks <= 32
        and args.outer >= 1
        and args.inner >= 1
        and args.outer * args.inner <= args.cpu_slots
    ):
        raise ValueError("layout exceeds the declared CPU or task budget")
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    rows = []
    with ThreadPoolExecutor(max_workers=args.outer) as pool:
        futures = [
            pool.submit(run_one, args.entry, args.preset, args.output, i, args.inner)
            for i in range(args.tasks)
        ]
        for i, future in enumerate(futures):
            try:
                rows.append(future.result())
            except Exception as error:
                rows.append(
                    dict(index=i, error=str(error), returncode=None, summary=None)
                )
    passed = all(
        r["returncode"] == 0 and r["summary"] and r["summary"].get("passed") is True
        for r in rows
    )
    report = dict(
        chapter="X1-layout",
        passed=passed,
        outer=args.outer,
        inner=args.inner,
        cpu_slots=args.cpu_slots,
        tasks=args.tasks,
        task_timeout_seconds=TASK_SECONDS,
        preset=args.preset,
        total_seconds=time.perf_counter() - start,
        runs=rows,
        scope="Warm installed binaries; subprocess import/start and final validation included. Cold build cost is not included.",
    )
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
