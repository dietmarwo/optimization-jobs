"""Entry point staged as a hashed input of a trusted command job."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

source = json.loads(Path("source.json").read_text())
for filename, expected in source["files"].items():
    actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("source changed after admission: " + filename)
subprocess.run(
    [
        sys.executable,
        source["entry"],
        "--preset",
        source["preset"],
        "--output",
        "lesson-output",
    ],
    check=True,
)
