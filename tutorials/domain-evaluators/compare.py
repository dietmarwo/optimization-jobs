#!/usr/bin/env python3
"""Compare every summary field except elapsed time; no rounding or field pruning.

A mismatch names the fields that differ, with both values.
"""
import argparse
import json
from pathlib import Path


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k != "seconds"}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            where = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                yield f"{where}: present on one side only"
            else:
                yield from differences(left[key], right[key], where)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right)):
            yield from differences(a, b, f"{path}[{index}]")
    elif left != right or type(left) is not type(right):
        yield f"{path}: {json.dumps(left)[:80]} != {json.dumps(right)[:80]}"


def compare(left, right):
    if left.get("passed") is not True or right.get("passed") is not True:
        raise ValueError("cannot compare failed summaries as success")
    found = list(differences(stable(left), stable(right)))
    if found:
        raise ValueError(f"{len(found)} field(s) differ (only seconds may differ):\n  "
                         + "\n  ".join(found[:20]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("left", type=Path)
    p.add_argument("right", type=Path)
    args = p.parse_args()
    compare(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    print("All non-timing fields match exactly.")
