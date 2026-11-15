#!/usr/bin/env python3
"""Compare every summary field except elapsed time; no rounding or field pruning."""
import argparse
import json
from pathlib import Path


def stable(value):
    if isinstance(value, dict):
        return {k: stable(v) for k, v in value.items() if k != "seconds"}
    if isinstance(value, list):
        return [stable(v) for v in value]
    return value


def compare(left, right):
    if left.get("passed") is not True or right.get("passed") is not True:
        raise ValueError("cannot compare failed summaries as success")
    if stable(left) != stable(right):
        raise ValueError("numerical records differ (only seconds may differ)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("left", type=Path)
    p.add_argument("right", type=Path)
    args = p.parse_args()
    compare(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
    print("All non-timing fields match exactly.")
