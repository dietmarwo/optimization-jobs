"""Run the X1 tutorial using the shared model and retain every result."""

import argparse
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "structured"))
from solver_choice import run
from sources import sibling


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preset", choices=["smoke", "study"], default="smoke")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() and (
        not args.output.is_dir() or any(args.output.iterdir())
    ):
        raise FileExistsError("use a new output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        start = time.time()
        result = run(args.preset)
        sys.path.insert(0, str(sibling("SQP-craft", "tutorials", "_support")))
        from numerics import write

        write(
            args.output / "summary.json",
            dict(
                chapter="X1",
                preset=args.preset,
                seconds=time.time() - start,
                result=result,
            ),
        )
        print('{"chapter":"X1","status":"passed"}')
    except Exception as e:
        (args.output / "failure.txt").write_text(
            repr(e) + "\n\n" + traceback.format_exc()
        )
        raise


if __name__ == "__main__":
    main()
