#!/usr/bin/env python3
"""Checks which optimization-job-api a worker workspace resolves (CI).

Reads `cargo metadata` on stdin. With `checkout`, the package must come from
the optimization-jobs checkout at CHECKOUT (a path dependency); with
`pinned`, from the Git repository at the revision the workspace pins.

    cargo metadata --format-version 1 | sdk_source.py pinned|checkout CHECKOUT NAME
"""
import json
import sys
from pathlib import Path

mode, checkout, name = sys.argv[1], Path(sys.argv[2]).resolve(), sys.argv[3]
packages = [p for p in json.load(sys.stdin)["packages"] if p["name"] == "optimization-job-api"]
if len(packages) != 1:
    sys.exit(f"{name}: expected one optimization-job-api, found {len(packages)}")
package = packages[0]
source = package["source"] or "path " + str(Path(package["manifest_path"]).parent)
print(f"{name}: optimization-job-api {package['version']} from {source}")
if mode == "checkout":
    if package["source"] is not None or not Path(package["manifest_path"]).resolve().is_relative_to(checkout):
        sys.exit(f"{name}: the patch to {checkout} was not applied")
elif not (package["source"] or "").startswith("git+https://github.com/dietmarwo/optimization-jobs"):
    sys.exit(f"{name}: optimization-job-api does not come from the pinned Git revision")
