"""Staged entry point for the existing trusted command-job interface."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def main():
    source = json.loads(Path("source.json").read_text())
    for filename, expected in source["files"].items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
            raise ValueError("source changed after admission: " + filename)
    for package, version in source["packages"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError("installed package changed: " + package)
    result = subprocess.run([sys.executable, *source["argv"]], check=False)
    summary = Path("lesson-output/summary.json")
    if summary.is_file():
        Path("summary.json").write_bytes(summary.read_bytes())
    # Seal all produced evidence, including numerical failures. The runtime owns
    # admission, timeout/cancellation, output collection and the native handle.
    with zipfile.ZipFile("evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write("source.json")
        for p in sorted(Path("lesson-output").rglob("*")):
            if p.is_file() and not p.is_symlink():
                archive.write(p)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
