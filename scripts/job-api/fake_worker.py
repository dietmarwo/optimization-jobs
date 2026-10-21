#!/usr/bin/env python3
"""Protocol fixture for scripts/job-api/test_review.py: a worker whose
behaviour is chosen by payload["mode"]. It is not a solver. It speaks worker
protocol 0.1, so it also checks that the runner still accepts 0.1 workers.
Its describe output follows the discovery convention (payload_schemas,
input_schemas and runnable examples), so the harness's discovery checks run
without real workers."""
import fcntl
import hashlib
import json
import signal
import sys
import time
from pathlib import Path

DIALECT = "https://json-schema.org/draft/2020-12/schema"
ONE_SLOT = {"cpu_slots": 1, "outer_workers": 1, "inner_threads": 1}
LIMITS = {"wall_time_seconds": 30.0, "grace_seconds": 1.0}
DESCRIPTION = {
    "protocol": "optimization.worker/0.1",
    "profiles": ["test.fake/1"],
    "payload_schemas": {"test.fake/1": {
        "$schema": DIALECT, "$id": "urn:optimization-jobs:payload:test.fake/1",
        "$comment": "A protocol fixture, not a solver: unlike real workers it accepts unknown fields.",
        "type": "object",
        "properties": {
            "mode": {"enum": ["sleep", "complete", "garbage_journal", "crash", "artifacts"]},
            "seconds": {"type": "number", "minimum": 0},
            "validate_sleep": {"type": "number", "minimum": 0},
            "outcome": {"type": "object", "description": "The record of mode complete"},
            "declarations": {"type": "array", "items": {"type": "object"}},
        },
    }},
    "input_schemas": {"test.values/1": {
        "$schema": DIALECT, "$id": "urn:optimization-jobs:input:test.values/1",
        "type": "object", "required": ["values"], "additionalProperties": False,
        "properties": {"values": {"type": "array", "items": {"type": "number"}, "minItems": 1}},
    }},
    "examples": [
        {"profile": "test.fake/1", "description": "One task that completes at once",
         "resources": ONE_SLOT, "limits": LIMITS, "payload": {"mode": "complete"}, "inputs": []},
        {"profile": "test.fake/1", "description": "The same with a JSON input and a text input",
         "resources": ONE_SLOT, "limits": LIMITS, "payload": {"mode": "complete"},
         "inputs": [{"name": "values", "file": "values.json", "format": "test.values/1",
                     "content": {"values": [1.0, 2.5]}},
                    {"name": "notes", "file": "notes.csv", "content_text": "x,y\n1,2\n"}]},
    ],
}

command = sys.argv[1]
if command == "describe":
    print(json.dumps(DESCRIPTION))
    sys.exit(0)
if command == "validate":
    request = Path(sys.argv[2])
    spec = json.loads(request.read_text())
    time.sleep(spec["payload"].get("validate_sleep", 0))
    # Like a real worker, validation needs the staged input files.
    for declared in spec["inputs"]:
        if not (request.parent / declared["file"]).is_file():
            sys.exit(f"input {declared['name']} was not staged")
    spec["task_count"] = 1
    print(json.dumps({"resolved": spec}))
    sys.exit(0)

directory = Path(sys.argv[2])
lock = (directory / "worker.lock").open("w")
fcntl.flock(lock, fcntl.LOCK_EX)
payload = json.loads((directory / "resolved.json").read_text())["payload"]
mode = payload.get("mode", "sleep")
if mode == "sleep":
    time.sleep(payload.get("seconds", 120))
elif mode == "garbage_journal":
    # A faulty worker: one complete line that is no journal envelope.
    (directory / "results.jsonl").write_bytes(b"this is not an envelope\n")
    sys.exit(3)
elif mode == "crash":
    signal.raise_signal(signal.SIGSEGV)
elif mode == "artifacts":
    # Declares a log of checked records and a JSON snapshot the way the Rust
    # SDK's artifact::declare does, appends three records, waits until the
    # test creates `release` in the attempt directory, appends two more and
    # completes like "complete" below.
    def append_checked(path, value):
        text = json.dumps(value)
        line = {"schema_version": 1, "checksum": hashlib.sha256(text.encode()).hexdigest(),
                "payload_json": text}
        with open(path, "a") as f:
            f.write(json.dumps(line) + "\n")
    declarations = payload.get("declarations", [
        {"name": "log", "file": "log.jsonl", "format": "records", "task_id": 0,
         "description": "Evaluation log"},
        {"name": "snapshot", "file": "snapshot.json", "format": "json", "task_id": 0}])
    for d in declarations:
        append_checked(directory / "artifacts.jsonl", d)
    for i in range(3):
        append_checked(directory / "log.jsonl", {"id": i, "x": [float(i)]})
    (directory / "snapshot.json").write_text(json.dumps({"observations": 3}))
    deadline = time.monotonic() + 30
    while not (directory / "release").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    for i in range(3, 5):
        append_checked(directory / "log.jsonl", {"id": i, "x": [float(i)]})
    (directory / "snapshot.json").write_text(json.dumps({"observations": 5}))
    mode = "complete"
if mode == "complete":
    # After an optional delay, one 0.1 result record (no evidence), committed
    # like the Rust SDK does, then the worker manifest the runner
    # cross-checks against the journal.
    time.sleep(payload.get("seconds", 0))
    spec = json.loads((directory / "resolved.json").read_text())
    spec.pop("request_key")
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    outcome = payload.get("outcome", {"termination": "evaluation_limit", "claim": "best_found",
                                      "feasible": True, "objective": 1.0, "x": [1.0], "details": {}})
    record = {"task_id": 0, "spec_digest": digest, "elapsed_seconds": 0.0, "work": {"evaluations": 1},
              "outcome": outcome}
    payload = json.dumps(record)
    envelope = {"schema_version": 1, "checksum": hashlib.sha256(payload.encode()).hexdigest(),
                "payload_json": payload}
    (directory / "results.jsonl").write_text(json.dumps(envelope) + "\n")
    (directory / "run.json").write_text(json.dumps({
        "schema_version": "optimization.result/0.1", "status": "completed", "elapsed_seconds": 0.0,
        "results": [record], "work": {"evaluations": 1},
        "runner": {"spec_digest": digest, "accounting_complete": True}}))
sys.exit(0)
