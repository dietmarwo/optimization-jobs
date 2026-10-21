#!/usr/bin/env python3
"""Tests of optimization-mcp, the MCP server over one optimization-run node
(docs/job-api.md#agents-and-mcp).

The server and the runner come from JOB_API_TARGET (a directory, by default
this repository's target/release). Every test gets a fresh node with the
protocol fixture `fake_worker.py` registered, plus the first real worker
(fcmaes, LP-IP or SQP) found in JOB_API_TARGET, for a result with evidence:

    cargo build --release --locked -p optimization-runner
    python3 scripts/job-api/test_mcp.py

Both protocol eras are covered: 2026-07-28, stateless with per-request
`_meta` and the Tasks extension, and 2025-11-25 and earlier after an
`initialize` handshake. JOB_API_REQUIRE_WORKER=1 makes the real-worker test
fail instead of skipping when no real worker is found.
"""
import base64
import hashlib
import json
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review import LP_MODEL, REAL, proc_entry, processes  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TARGET = Path(os.environ.get("JOB_API_TARGET", REPO / "target/release"))
RUN = TARGET / "optimization-run"
MCP = TARGET / "optimization-mcp"
FAKE = Path(__file__).resolve().parent / "fake_worker.py"
GUIDE = REPO / "crates/optimization-runner/guide/ai-context.md"
TASKS = "io.modelcontextprotocol/tasks"
VERSION = "2026-07-28"
TERMINAL = {"completed", "failed", "cancelled", "timed_out", "interrupted"}
WORKER = next((name for name, (binary, _, _) in REAL.items() if (TARGET / binary).exists()), None)
TOOLS = ["get_guide", "describe_node", "describe_worker", "put_input", "validate_job", "submit_job", "get_job",
         "wait_job", "get_result", "get_events", "get_artifact", "list_jobs", "cancel_job", "kill_job",
         "repair_job"]


def job_id(key):
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def fake(key, payload, slots=1, wall=60.0):
    return {
        "schema_version": "optimization.job/0.1", "request_key": key, "worker": "fake",
        "payload_schema": "test.fake/1", "payload": payload,
        "resources": {"cpu_slots": slots, "outer_workers": 1, "inner_threads": 1},
        "limits": {"wall_time_seconds": wall, "grace_seconds": 0.5}, "inputs": [],
    }


def guide_headings(text):
    """(line number, level, text) of the Markdown headings outside fenced
    code blocks, whose shell comments start with # too."""
    found, fenced = [], False
    for number, line in enumerate(text.splitlines()):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#{1,6})[ \t]+(.+?)[ \t]*$", line)):
            found.append((number, len(match.group(1)), match.group(2)))
    return found


def guide_section(text, query):
    """The first section whose heading contains query, case-insensitively,
    through to the next heading of the same or a higher level."""
    lines = text.splitlines(keepends=True)
    headings = guide_headings(text)
    for k, (number, level, title) in enumerate(headings):
        if query.lower() in title.lower():
            end = next((n for n, other, _ in headings[k + 1:] if other <= level), len(lines))
            return title, "".join(lines[number:end]).rstrip() + "\n"
    return None


def launcher(root):
    """PID, in this process's PID namespace, of the optimization-run launcher
    of a job on this node."""
    for pid, argv in processes():
        if str(root).encode() in argv and b"run" in argv:
            return pid
    raise AssertionError("no launcher found")


def meta(tasks=False):
    capabilities = {"extensions": {TASKS: {}}} if tasks else {}
    return {"io.modelcontextprotocol/protocolVersion": VERSION,
            "io.modelcontextprotocol/clientCapabilities": capabilities,
            "io.modelcontextprotocol/clientInfo": {"name": "test_mcp", "version": "1"}}


class Client:
    """An MCP client over the server's stdio; notifications are kept."""

    def __init__(self, root, *arguments):
        self.process = subprocess.Popen(
            [str(MCP), "--root", str(root), *arguments], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.messages = queue.Queue()
        self.notifications = []
        self.responses = {}
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.messages.put(json.loads(line))
        self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def start(self, method, params=None, modern=True, tasks=False, extra_meta=None):
        self.next_id += 1
        params = dict(params or {})
        if modern:
            params["_meta"] = {**meta(tasks), **(extra_meta or {})}
        elif extra_meta:
            params["_meta"] = extra_meta
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        return self.next_id

    def pump(self, timeout):
        try:
            message = self.messages.get(timeout=timeout)
        except queue.Empty:
            return False
        if message is None:
            raise EOFError("the server closed its output")
        if "id" in message and "method" not in message:
            self.responses[message["id"]] = message
        else:
            self.notifications.append(message)
        return True

    def response(self, ident, timeout=60):
        deadline = time.time() + timeout
        while ident not in self.responses:
            if not self.pump(max(0.0, deadline - time.time())) and time.time() >= deadline:
                raise TimeoutError(f"no response to request {ident}")
        return self.responses.pop(ident)

    def request(self, method, params=None, **kw):
        return self.response(self.start(method, params, **kw))

    def tool(self, name, arguments=None, **kw):
        reply = self.request("tools/call", {"name": name, "arguments": arguments or {}}, **kw)
        if "error" in reply:
            raise AssertionError(f"{name}: protocol error {reply['error']}")
        return reply["result"]

    def ok(self, name, arguments=None, **kw):
        result = self.tool(name, arguments, **kw)
        if result.get("isError"):
            raise AssertionError(f"{name}: {result['structuredContent']}")
        self.check_text(result)
        return result["structuredContent"]

    def error(self, name, arguments=None, **kw):
        result = self.tool(name, arguments, **kw)
        if not result.get("isError"):
            raise AssertionError(f"{name} succeeded: {result['structuredContent']}")
        self.check_text(result)
        return result["structuredContent"]["error"]

    @staticmethod
    def check_text(result):
        # Clients that read only text get the same JSON.
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()


class Server(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "node"
        self.call("node", "init", "--capacity", "8")
        self.call("workers", "add", "--id", "fake", "--executable", str(FAKE))
        if WORKER:
            self.call("workers", "add", "--id", WORKER, "--executable", str(TARGET / REAL[WORKER][0]))
        self.addCleanup(self.stop_jobs)
        self.client = self.connect()

    def connect(self, *arguments):
        client = Client(self.root, *arguments)
        self.addCleanup(client.close)
        return client

    def call(self, *arguments):
        process = subprocess.run([str(RUN), "--root", str(self.root), *arguments],
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def stop_jobs(self):
        # Jobs outlive the server by design; kill the ones a test left running.
        for directory in (self.root / "jobs").glob("*"):
            state = json.loads((directory / "job.json").read_text())["state"]
            if state not in TERMINAL:
                subprocess.run([str(RUN), "--root", str(self.root), "jobs", "cancel",
                                directory.name, "--now"], capture_output=True)
        deadline = time.time() + 15
        for directory in (self.root / "jobs").glob("*"):
            while time.time() < deadline:
                if json.loads((directory / "job.json").read_text())["state"] in TERMINAL:
                    break
                time.sleep(0.1)

    def wait(self, ident, timeout=30.0):
        deadline = time.time() + timeout
        while True:
            job = self.client.ok("wait_job", {"job_id": ident, "timeout_seconds": 5})
            if job["state"] in TERMINAL or time.time() > deadline:
                return job

    def running(self, ident, client=None):
        client = client or self.client
        deadline = time.time() + 20
        while time.time() < deadline:
            if client.ok("get_job", {"job_id": ident})["state"] == "running":
                return
            time.sleep(0.1)
        self.fail(f"job {ident} never ran")

    def poll_task(self, task, timeout=30.0, client=None):
        client = client or self.client
        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = client.request("tasks/get", {"taskId": task}, tasks=True)
            self.assertEqual(reply["result"]["resultType"], "complete")
            if reply["result"]["status"] in {"completed", "failed", "cancelled"}:
                return reply["result"]
            time.sleep(0.2)
        self.fail(f"task {task} did not end")


class Protocol(Server):
    def test_discovery_and_protocol_versions(self):
        result = self.client.request("server/discover")["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["supportedVersions"][0], VERSION)
        self.assertIn("2025-11-25", result["supportedVersions"])
        self.assertEqual(result["capabilities"]["extensions"], {TASKS: {}})
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "optimization-mcp")
        self.assertIn("submit_job", result["instructions"])
        self.assertIn("call get_guide first", result["instructions"])
        # An unsupported version is a modern error naming the supported ones.
        ident = self.client.start("server/discover", modern=False, extra_meta={
            "io.modelcontextprotocol/protocolVersion": "1900-01-01",
            "io.modelcontextprotocol/clientCapabilities": {}})
        error = self.client.response(ident)["error"]
        self.assertEqual(error["code"], -32022)
        self.assertEqual(error["data"]["requested"], "1900-01-01")
        self.assertIn(VERSION, error["data"]["supported"])
        # A modern request without client capabilities is malformed.
        ident = self.client.start("tools/list", modern=False,
                                  extra_meta={"io.modelcontextprotocol/protocolVersion": VERSION})
        self.assertEqual(self.client.response(ident)["error"]["code"], -32602)
        # Without _meta and before initialize, the era is unknown.
        error = self.client.request("tools/list", modern=False)["error"]
        self.assertEqual(error["code"], -32602)
        self.assertIn("initialize", error["message"])
        # ping and logging/setLevel are gone in 2026-07-28.
        self.assertEqual(self.client.request("ping")["error"]["code"], -32601)
        self.assertEqual(self.client.request("tasks/result", {"taskId": "x"}, tasks=True)["error"]["code"], -32601)
        self.client.send({"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {"_meta": meta()}})
        self.client.process.stdin.write("{not json\n")
        self.client.process.stdin.flush()
        self.assertEqual(self.client.response(99)["result"]["resultType"], "complete")
        self.client.pump(5)
        while not any(m.get("error", {}).get("code") == -32700 for m in self.client.responses.values()):
            self.assertTrue(self.client.pump(5), "no parse error reported")
        parse = next(m for m in self.client.responses.values() if m.get("error", {}).get("code") == -32700)
        self.assertIsNone(parse["id"])

    def test_legacy_handshake(self):
        result = self.client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "legacy", "version": "1"}}, modern=False)["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"]["name"], "optimization-mcp")
        self.assertNotIn("resultType", result)
        self.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(self.client.request("ping", modern=False)["result"], {})
        tools = self.client.request("tools/list", modern=False)["result"]
        self.assertEqual([t["name"] for t in tools["tools"]], TOOLS)
        self.assertNotIn("resultType", tools)
        node = self.client.ok("describe_node", modern=False)
        self.assertEqual(node["capacity"], 8)
        # The host as node doctor reports it, with its warnings.
        doctor = self.call("node", "doctor")
        self.assertEqual((node["host"], node["warnings"]), (doctor["host"] | {
            "memory_available_bytes": node["host"]["memory_available_bytes"],
            "usable_memory_bytes": node["host"]["usable_memory_bytes"]}, doctor["warnings"]))
        self.assertGreaterEqual(node["host"]["usable_cpus"], 1)
        self.assertEqual(bool(node["warnings"]), node["host"]["usable_cpus"] < 8)
        # Legacy clients have no tasks: submit_job returns the handle.
        handle = self.client.ok("submit_job", {"job": fake("legacy", {"mode": "complete"})}, modern=False)
        self.assertEqual(handle["job_id"], job_id("legacy"))
        self.assertEqual(self.client.request("tasks/get", {"taskId": "x"}, modern=False)["error"]["code"], -32601)
        # A modern request is still served statelessly on the same process.
        self.assertEqual(self.client.request("tools/list")["result"]["resultType"], "complete")
        # An unknown legacy version gets the newest legacy one.
        other = self.connect()
        result = other.request("initialize", {"protocolVersion": "2099-01-01", "capabilities": {},
                                              "clientInfo": {"name": "x", "version": "1"}},
                               modern=False)["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")

    def test_tool_definitions(self):
        result = self.client.request("tools/list")["result"]
        self.assertEqual(result["cacheScope"], "public")
        self.assertGreater(result["ttlMs"], 0)
        tools = {t["name"]: t for t in result["tools"]}
        self.assertEqual(list(tools), TOOLS)
        self.assertEqual(result, self.client.request("tools/list")["result"])
        for tool in tools.values():
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertIn("readOnlyHint", tool["annotations"])
            self.assertTrue(tool["description"])
        envelope = tools["submit_job"]["inputSchema"]["properties"]["job"]
        self.assertEqual(envelope["properties"]["schema_version"]["const"], "optimization.job/0.1")
        self.assertNotIn("$schema", envelope)
        self.assertTrue(tools["kill_job"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["get_result"]["annotations"]["readOnlyHint"])
        error = self.client.request("tools/call", {"name": "nope", "arguments": {}})["error"]
        self.assertEqual((error["code"], error["message"]), (-32602, "Unknown tool: nope"))
        error = self.client.request("tools/call", {"name": "get_job", "arguments": [1]})["error"]
        self.assertEqual(error["code"], -32602)


class Jobs(Server):
    def test_submit_wait_result_and_idempotency(self):
        job = fake("complete", {"mode": "complete"})
        valid = self.client.ok("validate_job", {"job": job})
        self.assertTrue(valid["valid"])
        self.assertEqual(valid["resolved"]["task_count"], 1)
        handle = self.client.ok("submit_job", {"job": job})
        ident = handle["job_id"]
        self.assertEqual(ident, job_id("complete"))
        self.assertTrue(Path(handle["directory"]).is_dir())
        self.assertEqual(self.wait(ident)["state"], "completed")
        summary = self.client.ok("get_result", {"job_id": ident})
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["claims"], {"best_found": 1})
        self.assertEqual(summary["tasks"][0]["objective"], 1.0)
        self.assertNotIn("x", summary["tasks"][0])
        records = self.client.ok("get_result", {"job_id": ident, "tasks": [0]})["tasks"]
        self.assertEqual(records[0]["outcome"]["x"], [1.0])
        full = self.client.ok("get_result", {"job_id": ident, "full": True})
        self.assertEqual(full["status"], "completed")
        events = self.client.ok("get_events", {"job_id": ident, "limit": 2})
        self.assertEqual(len(events["events"]), min(2, events["total"]))
        # The same key and content returns the job; other content is a conflict.
        self.assertEqual(self.client.ok("submit_job", {"job": job})["job_id"], ident)
        error = self.client.error("submit_job", {"job": fake("complete", {"mode": "complete", "x": 1})})
        self.assertEqual(error["code"], "request_key_conflict")
        listed = self.client.ok("list_jobs")
        self.assertEqual(listed["jobs"][0]["job_id"], ident)
        self.assertEqual(self.client.ok("list_jobs", {"active_only": True})["jobs"], [])
        # Only this submission's files remain: the staged copy is gone.
        self.assertEqual(list((self.root / "mcp" / "staging").iterdir()), [])
        error = self.client.error("cancel_job", {"job_id": ident})
        self.assertEqual(error["code"], "already_terminal")

    def test_errors_are_tool_errors_with_codes(self):
        cases = [
            ("get_job", {"job_id": "nothex"}, "invalid_arguments"),
            ("get_job", {"job_id": "0" * 32}, "unknown_job"),
            ("submit_job", {}, "invalid_arguments"),
            ("submit_job", {"job": fake("x", {}), "spec_path": "/x"}, "invalid_arguments"),
            ("submit_job", {"job": fake("big", {"mode": "complete"}, slots=16)}, "capacity_exceeded"),
            ("submit_job", {"job": {**fake("bad", {}), "schema_version": "nope"}}, "invalid_job"),
            ("validate_job", {"job": {**fake("w", {}), "worker": "absent"}}, None),
            ("wait_job", {"job_id": "0" * 32, "timeout_seconds": 0}, "invalid_arguments"),
            ("describe_worker", {}, "invalid_arguments"),
        ]
        for name, arguments, code in cases:
            with self.subTest(name=name, arguments=arguments):
                error = self.client.error(name, arguments)
                self.assertTrue(error["code"])
                if code:
                    self.assertEqual(error["code"], code, error["message"])
                self.assertIn("retryable", error)
        ident = self.client.ok("submit_job", {"job": fake("sleeper", {"mode": "sleep", "seconds": 30})})["job_id"]
        self.running(ident)
        self.assertEqual(self.client.error("get_result", {"job_id": ident})["code"], "not_finished")
        self.assertEqual(self.client.error("repair_job", {"job_id": ident})["code"], "attempt_active")

    def test_cancel_kill_and_events(self):
        graceful = self.client.ok("submit_job", {"job": fake("graceful", {"mode": "sleep", "seconds": 2})})["job_id"]
        killed = self.client.ok("submit_job", {"job": fake("killed", {"mode": "sleep", "seconds": 60})})["job_id"]
        self.running(graceful)
        self.running(killed)
        self.assertTrue(self.client.ok("cancel_job", {"job_id": graceful})["cancel_requested"])
        start = time.time()
        self.client.ok("kill_job", {"job_id": killed})
        self.assertEqual(self.wait(killed)["state"], "cancelled")
        self.assertLess(time.time() - start, 15)
        self.assertEqual(self.wait(graceful)["state"], "cancelled")
        summary = self.client.ok("get_result", {"job_id": graceful})
        self.assertEqual(summary["state"], "cancelled")
        kinds = [e.get("event") or e.get("kind") or e.get("type") for e in
                 self.client.ok("get_events", {"job_id": graceful, "limit": 1000})["events"]]
        self.assertTrue(kinds)

    def test_artifacts_while_running_in_pages_and_as_inputs_of_the_next_job(self):
        ident = self.client.ok("submit_job", {"job": fake("artifacts", {"mode": "artifacts"})})["job_id"]
        directory = self.root / "jobs" / ident
        deadline = time.time() + 20
        while not (directory / "snapshot.json").exists() and time.time() < deadline:
            time.sleep(0.05)
        index = self.client.ok("get_job", {"job_id": ident})["artifact_index"]
        self.assertEqual(index["log"]["format"], "records")
        page = self.client.ok("get_artifact", {"job_id": ident, "name": "log", "offset": 2, "limit": 5})
        self.assertEqual((page["records"], page["next_offset"], page["available"], page["final"]),
                         ([{"id": 2, "x": [2.0]}], 3, 3, False))
        self.assertEqual(self.client.error("get_artifact", {"job_id": ident, "name": "log", "limit": 0})["code"],
                         "invalid_arguments")
        self.assertEqual(self.client.error("get_artifact", {"job_id": ident, "name": "none"})["code"],
                         "unknown_artifact")
        (directory / "release").touch()
        self.assertEqual(self.wait(ident)["state"], "completed")
        summary = self.client.ok("get_result", {"job_id": ident})
        snapshot = summary["artifact_index"]["snapshot"]
        self.assertEqual(summary["artifacts"]["snapshot"], "snapshot.json")
        content = self.client.ok("get_artifact", {"job_id": ident, "name": "snapshot"})["content"]
        self.assertEqual(json.loads(content), {"observations": 5})
        # The documented reuse: the next job names the file in the old job's
        # directory with the SHA-256 the index recorded.
        job = fake("next", {"mode": "complete"})
        job["inputs"] = [{"name": "previous", "file": snapshot["file"], "sha256": snapshot["sha256"]}]
        follow = self.client.ok("submit_job", {"job": job, "input_dir": summary["directory"]})["job_id"]
        self.assertEqual(self.wait(follow)["state"], "completed")
        self.assertEqual((self.root / "jobs" / follow / "inputs" / "previous").read_text(), content)

    def test_inputs_spec_path_and_input_dir(self):
        data = self.base / "data"
        data.mkdir()
        (data / "model.txt").write_bytes(b"model")
        digest = hashlib.sha256(b"model").hexdigest()
        job = fake("input", {"mode": "complete"})
        job["inputs"] = [{"name": "model", "file": "model.txt", "sha256": digest}]
        ident = self.client.ok("submit_job", {"job": job, "input_dir": str(data)})["job_id"]
        self.assertEqual(self.wait(ident)["state"], "completed")
        staged = self.root / "jobs" / ident / "inputs" / "model"
        self.assertEqual(staged.read_bytes(), b"model")
        wrong = fake("wrong", {"mode": "complete"})
        wrong["inputs"] = [{"name": "model", "file": "model.txt", "sha256": "0" * 64}]
        self.assertEqual(self.client.error("submit_job", {"job": wrong, "input_dir": str(data)})["code"], "invalid_job")
        # Relative inputs of inline jobs come from the server's --input-dir.
        other = self.connect("--input-dir", str(data))
        job["request_key"] = "input-dir"
        self.assertEqual(other.ok("validate_job", {"job": job})["valid"], True)
        escape = fake("escape", {"mode": "complete"})
        escape["inputs"] = [{"name": "model", "file": "../data/model.txt", "sha256": digest}]
        self.assertEqual(other.error("submit_job", {"job": escape})["code"], "invalid_job")
        # A job file on disk reads its inputs next to itself.
        job["request_key"] = "spec-path"
        (data / "job.json").write_text(json.dumps(job))
        ident = self.client.ok("submit_job", {"spec_path": str(data / "job.json")})["job_id"]
        self.assertEqual(ident, job_id("spec-path"))
        self.assertEqual(self.wait(ident)["state"], "completed")

    def test_a_real_worker_reports_claims_and_evidence(self):
        if not WORKER:
            if os.environ.get("JOB_API_REQUIRE_WORKER") == "1":
                self.fail("no fcmaes, LP-IP or SQP worker in JOB_API_TARGET (JOB_API_REQUIRE_WORKER=1)")
            self.skipTest("no fcmaes, LP-IP or SQP worker in JOB_API_TARGET")
        binary, profile, payload = REAL[WORKER]
        job = {**fake("real", payload), "worker": WORKER, "payload_schema": profile}
        arguments = {"job": job}
        if WORKER == "lp-ip":
            (self.base / "model.json").write_bytes(LP_MODEL)
            job["inputs"] = [{"name": "model", "file": "model.json",
                              "sha256": hashlib.sha256(LP_MODEL).hexdigest()}]
            arguments["input_dir"] = str(self.base)
        description = self.client.ok("describe_worker", {"worker": WORKER})
        self.assertIn(profile, description["profiles"])
        ident = self.client.ok("submit_job", arguments)["job_id"]
        self.assertEqual(self.wait(ident)["state"], "completed")
        summary = self.client.ok("get_result", {"job_id": ident})
        self.assertEqual(summary["schema_version"], "optimization.result/0.2")
        self.assertTrue(summary["accounting_complete"])
        task = summary["tasks"][0]
        self.assertIn(task["evidence"], {"claimed", "rechecked", "certified"})
        self.assertNotEqual(task["claim"], "none")


class Guide(Server):
    def test_the_guide_whole_and_by_section(self):
        text = GUIDE.read_text()
        whole = self.client.ok("get_guide")
        self.assertEqual((whole["guide"], whole["content"]), ("ai-context.md", text))
        self.assertTrue(whole["base_url"].startswith("https://github.com/dietmarwo/optimization-jobs/"))
        headings = guide_headings(text)
        for level in (2, 3):
            title = next(t for _, other, t in headings if other == level)
            expected = guide_section(text, title)
            part = self.client.ok("get_guide", {"section": title.upper()})
            self.assertEqual((part["section"], part["content"]), expected)
            self.assertTrue(part["content"].startswith("#" * level + " "))
        # A heading of a later level-2 section, by a word of it in lower case.
        title = [t for _, other, t in headings if other == 2][-1]
        word = max(title.split(), key=len).lower()
        part = self.client.ok("get_guide", {"section": word})
        self.assertEqual((part["section"], part["content"]), guide_section(text, word))
        error = self.client.error("get_guide", {"section": "no heading has this text"})
        self.assertEqual(error["code"], "invalid_arguments")
        for _, level, title in headings:
            self.assertIn("#" * level + " " + title, error["message"])
        self.assertEqual(self.client.error("get_guide", {"section": ""})["code"], "invalid_arguments")
        self.assertEqual(self.client.error("get_guide", {"section": 2})["code"], "invalid_arguments")


class Inputs(Server):
    """put_input: the node's content-addressed input store (review F02)."""

    def store(self):
        return self.root / "mcp" / "inputs"

    def test_stored_inputs_are_named_by_their_sha256_and_used_by_jobs(self):
        text = json.dumps({"values": [1.0, 2.0]})
        digest = hashlib.sha256(text.encode()).hexdigest()
        stored = self.client.ok("put_input", {"content": text})
        self.assertEqual(stored, {"file": digest, "sha256": digest, "bytes": len(text),
                                  "input_dir": str(self.store())})
        self.assertEqual((self.store() / digest).read_text(), text)
        # Bytes, here not UTF-8, and text that is not ASCII.
        blob = bytes(range(256))
        other = self.client.ok("put_input", {"content_base64": base64.b64encode(blob).decode()})
        self.assertEqual((other["sha256"], other["bytes"], other["input_dir"]),
                         (hashlib.sha256(blob).hexdigest(), 256, stored["input_dir"]))
        accents = self.client.ok("put_input", {"content": "Größe\n"})
        self.assertEqual((self.store() / accents["file"]).read_bytes(), "Größe\n".encode())
        self.assertEqual(accents["bytes"], 8)
        # Storing again is the same answer and makes the file fresh again.
        old = time.time() - 3 * 86400
        os.utime(self.store() / digest, (old, old))
        self.assertEqual(self.client.ok("put_input", {"content": text}), stored)
        self.assertGreater((self.store() / digest).stat().st_mtime, time.time() - 60)
        # A damaged file is replaced.
        (self.store() / digest).write_text("damaged")
        self.assertEqual(self.client.ok("put_input", {"content": text}), stored)
        self.assertEqual((self.store() / digest).read_text(), text)
        self.assertEqual(sorted(p.name for p in self.store().iterdir()),
                         sorted([digest, other["file"], accents["file"]]))
        # One job reads several stored inputs: they share the input_dir.
        job = fake("stored", {"mode": "complete"})
        job["inputs"] = [{"name": "data", "file": stored["file"], "sha256": stored["sha256"]},
                         {"name": "blob", "file": other["file"], "sha256": other["sha256"]}]
        arguments = {"job": job, "input_dir": stored["input_dir"]}
        self.assertTrue(self.client.ok("validate_job", arguments)["valid"])
        ident = self.client.ok("submit_job", arguments)["job_id"]
        self.assertEqual(self.wait(ident)["state"], "completed")
        staged = self.root / "jobs" / ident / "inputs"
        self.assertEqual(((staged / "data").read_text(), (staged / "blob").read_bytes()), (text, blob))

    def test_arguments_limits_and_errors(self):
        unknown = {"job_id": "0" * 32, "name": "results"}
        for arguments in [{}, {"content": "a", "content_base64": "YQ=="}, {"content": 1},
                          {"content_base64": "YQ="}, {"content_base64": "not base64!"},
                          {"from_artifact": "results"}, {"from_artifact": {"job_id": "0" * 32}},
                          {"from_artifact": {**unknown, "extra": 1}},
                          {"from_artifact": {**unknown, "job_id": "nothex"}}]:
            with self.subTest(arguments=arguments):
                error = self.client.error("put_input", arguments)
                self.assertEqual((error["code"], error["retryable"]), ("invalid_arguments", False))
        self.assertEqual(self.client.error("put_input", {"from_artifact": unknown})["code"], "unknown_job")
        self.assertFalse(any(self.store().iterdir()) if self.store().exists() else False)
        # The store's total size limit; content already stored needs no room.
        small = self.connect("--input-store-bytes", "100")
        first = small.ok("put_input", {"content": "x" * 60})
        error = small.error("put_input", {"content": "y" * 60})
        self.assertEqual((error["code"], error["retryable"]), ("input_store_full", False))
        self.assertIn("holds 60 bytes; 60 more would exceed its limit of 100 bytes", error["message"])
        self.assertEqual(small.ok("put_input", {"content": "x" * 60}), first)
        self.assertEqual([p.name for p in self.store().iterdir()], [first["file"]])

    def test_artifacts_become_inputs_of_later_jobs(self):
        ident = self.client.ok("submit_job", {"job": fake("artifacts", {"mode": "artifacts"})})["job_id"]
        directory = self.root / "jobs" / ident
        deadline = time.time() + 20
        while not (directory / "snapshot.json").exists() and time.time() < deadline:
            time.sleep(0.05)
        # While the job runs, a records artifact is copied up to its last
        # complete record, as a whole read of get_artifact returns it.
        log_file = directory / "log.jsonl"
        complete = log_file.read_bytes()
        with open(log_file, "a") as f:
            f.write('{"schema_version":1,"chec')
        log = self.client.ok("put_input", {"from_artifact": {"job_id": ident, "name": "log"}})
        whole = self.client.ok("get_artifact", {"job_id": ident, "name": "log"})
        self.assertEqual((log["sha256"], log["bytes"]), (whole["sha256"], whole["bytes"]))
        self.assertEqual((self.store() / log["file"]).read_bytes(), complete)
        log_file.write_bytes(complete)
        self.assertEqual(self.client.error("put_input", {"from_artifact": {"job_id": ident, "name": "none"}})["code"],
                         "unknown_artifact")
        # An artifact over the 64 MiB input limit (sparse: it takes no disk).
        snapshot = directory / "snapshot.json"
        content = snapshot.read_bytes()
        os.truncate(snapshot, 64 * 1024 * 1024 + 1)
        error = self.client.error("put_input", {"from_artifact": {"job_id": ident, "name": "snapshot"}})
        self.assertEqual(error["code"], "invalid_arguments")
        self.assertIn("64 MiB", error["message"])
        snapshot.write_bytes(content)
        (directory / "release").touch()
        self.assertEqual(self.wait(ident)["state"], "completed")
        # After the end: the file the manifest lists, checked against its SHA-256.
        index = self.client.ok("get_result", {"job_id": ident})["artifact_index"]
        copied = self.client.ok("put_input", {"from_artifact": {"job_id": ident, "name": "snapshot"}})
        self.assertEqual((copied["sha256"], copied["bytes"]),
                         (index["snapshot"]["sha256"], index["snapshot"]["bytes"]))
        # The copy and a new input in one later job.
        extra = self.client.ok("put_input", {"content": "settings"})
        job = fake("continued", {"mode": "complete"})
        job["inputs"] = [{"name": "previous", "file": copied["file"], "sha256": copied["sha256"]},
                         {"name": "settings", "file": extra["file"], "sha256": extra["sha256"]}]
        follow = self.client.ok("submit_job", {"job": job, "input_dir": copied["input_dir"]})["job_id"]
        self.assertEqual(self.wait(follow)["state"], "completed")
        self.assertEqual((self.root / "jobs" / follow / "inputs" / "previous").read_bytes(),
                         snapshot.read_bytes())
        snapshot.write_text("{}")
        error = self.client.error("put_input", {"from_artifact": {"job_id": ident, "name": "snapshot"}})
        self.assertIn("changed after the job ended", error["message"])

    def test_a_starting_server_removes_inputs_unused_for_a_week(self):
        kept = self.client.ok("put_input", {"content": "kept"})
        old = self.client.ok("put_input", {"content": "old"})
        week = time.time() - 7 * 86400 - 600
        os.utime(self.store() / old["file"], (week, week))
        leftover = self.store() / f".{old['file']}.1.tmp"
        leftover.write_text("partial")
        os.utime(leftover, (week, week))
        fresh = self.connect()
        self.assertEqual(fresh.request("tools/list")["result"]["resultType"], "complete")
        self.assertEqual([p.name for p in self.store().iterdir()], [kept["file"]])


class Tasks(Server):
    def test_task_lifecycle(self):
        job = fake("task", {"mode": "complete"})
        created = self.client.tool("submit_job", {"job": job}, tasks=True)
        self.assertEqual(created["resultType"], "task")
        self.assertTrue(created["taskId"].startswith("task-"))
        self.assertIn(created["status"], {"working", "completed"})
        self.assertNotIn("result", created)
        for key in ["createdAt", "lastUpdatedAt", "pollIntervalMs"]:
            self.assertIn(key, created)
        self.assertIsNone(created["ttlMs"])
        task = self.poll_task(created["taskId"])
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["result"]["isError"])
        result = task["result"]["structuredContent"]
        self.assertEqual(result["job"]["state"], "completed")
        self.assertEqual(result["result"]["claims"], {"best_found": 1})
        # Resubmitting the same job returns the same task.
        again = self.client.tool("submit_job", {"job": job}, tasks=True)
        self.assertEqual(again["taskId"], created["taskId"])
        self.assertEqual(again["status"], "completed")
        self.assertEqual(self.client.request("tasks/update", {"taskId": created["taskId"], "inputResponses": {}},
                                             tasks=True)["result"]["resultType"], "complete")
        # A failed submission is a tool error, not a task.
        error = self.client.tool("submit_job", {"job": fake("t2", {}, slots=16)}, tasks=True)
        self.assertTrue(error["isError"])
        self.assertNotIn("taskId", error)

    def test_cancel_through_the_task_and_failed_jobs(self):
        created = self.client.tool("submit_job", {"job": fake("cancel-task", {"mode": "sleep", "seconds": 2})},
                                   tasks=True)
        self.running(job_id("cancel-task"))
        ack = self.client.request("tasks/cancel", {"taskId": created["taskId"]}, tasks=True)["result"]
        self.assertEqual(ack["resultType"], "complete")
        task = self.poll_task(created["taskId"])
        self.assertEqual(task["status"], "cancelled")
        self.assertIn("get_result", task["statusMessage"])
        self.assertNotIn("result", task)
        # Cancelling an ended task is still acknowledged.
        self.assertIn("result", self.client.request("tasks/cancel", {"taskId": created["taskId"]}, tasks=True))
        # A job that fails is a completed task with a tool error.
        created = self.client.tool("submit_job", {"job": fake("fails", {"mode": "sleep", "seconds": 0})}, tasks=True)
        task = self.poll_task(created["taskId"])
        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["result"]["isError"])
        self.assertEqual(task["result"]["structuredContent"]["job"]["state"], "failed")

    def test_task_errors(self):
        created = self.client.tool("submit_job", {"job": fake("errors", {"mode": "complete"})}, tasks=True)
        self.poll_task(created["taskId"])
        error = self.client.request("tasks/get", {"taskId": created["taskId"]})["error"]
        self.assertEqual(error["code"], -32021)
        self.assertEqual(error["data"]["requiredCapabilities"], {"extensions": {TASKS: {}}})
        for method in ["tasks/get", "tasks/cancel", "tasks/update"]:
            error = self.client.request(method, {"taskId": "task-unknown"}, tasks=True)["error"]
            self.assertEqual(error["code"], -32602, method)
        error = self.client.request("tasks/get", {"taskId": 1}, tasks=True)["error"]
        self.assertEqual(error["code"], -32602)
        # A task whose job was removed from the node is unknown too.
        requests = self.root / "requests.json"
        requests.write_text(json.dumps({}))
        error = self.client.request("tasks/get", {"taskId": created["taskId"]}, tasks=True)["error"]
        self.assertEqual(error["code"], -32602)
        self.assertIn("no longer exists", error["message"])

    def test_systemd_launch(self):
        client = self.connect("--launch", "systemd")
        node = client.ok("describe_node")
        self.assertEqual(node["launch"], "systemd")
        job = fake("unit", {"mode": "complete"})
        if not node["systemd_user_manager"]:
            self.assertEqual(client.error("submit_job", {"job": job})["code"], "systemd_unavailable")
            return
        ident = client.ok("submit_job", {"job": job})["job_id"]
        self.assertEqual(self.wait(ident)["state"], "completed")

    def test_task_notifications(self):
        created = self.client.tool("submit_job", {"job": fake("notify", {"mode": "sleep", "seconds": 2})},
                                   tasks=True)
        ident = self.client.start("subscriptions/listen", {
            "notifications": {"taskIds": [created["taskId"], "task-unknown"], "toolsListChanged": True}},
            tasks=True)
        deadline = time.time() + 30
        statuses = []
        while time.time() < deadline and "cancelled" not in statuses and "completed" not in statuses:
            self.client.pump(1)
            statuses = [m["params"]["status"] for m in self.client.notifications
                        if m["method"] == "notifications/tasks"]
        ack = next(m for m in self.client.notifications
                   if m["method"] == "notifications/subscriptions/acknowledged")
        self.assertEqual(ack["params"]["notifications"], {"taskIds": [created["taskId"]]})
        self.assertEqual(ack["params"]["_meta"]["io.modelcontextprotocol/subscriptionId"], ident)
        self.assertLess(self.client.notifications.index(ack),
                        next(i for i, m in enumerate(self.client.notifications) if m["method"] == "notifications/tasks"))
        last = [m for m in self.client.notifications if m["method"] == "notifications/tasks"][-1]["params"]
        self.assertEqual(last["status"], "completed")
        self.assertTrue(last["result"]["isError"])  # a sleeping fake worker writes no result
        self.assertEqual(last["_meta"]["io.modelcontextprotocol/subscriptionId"], ident)
        self.assertNotIn("resultType", last)
        # The client ends the stream; it gets no response.
        self.client.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": ident}})
        time.sleep(3)
        while self.client.pump(0.1):
            pass
        self.assertNotIn(ident, self.client.responses)
        error = self.client.request("subscriptions/listen", {"notifications": {"taskIds": []}})["error"]
        self.assertEqual(error["code"], -32021)

    def test_tasks_and_jobs_survive_a_server_restart(self):
        created = self.client.tool("submit_job", {"job": fake("durable", {"mode": "complete", "seconds": 3})},
                                   tasks=True)
        self.running(job_id("durable"))
        self.client.process.send_signal(signal.SIGKILL)
        self.client.process.wait()
        fresh = self.connect()
        self.assertEqual(fresh.ok("get_job", {"job_id": job_id("durable")})["state"], "running")
        task = self.poll_task(created["taskId"], client=fresh)
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["result"]["isError"])
        self.assertEqual(task["result"]["structuredContent"]["result"]["claims"], {"best_found": 1})

    def test_a_lost_launcher_keeps_the_task_working_until_the_worker_ends(self):
        created = self.client.tool("submit_job", {"job": fake("orphan", {"mode": "complete", "seconds": 3})},
                                   tasks=True)
        ident = job_id("orphan")
        self.running(ident)
        os.kill(launcher(self.root), signal.SIGKILL)
        deadline = time.time() + 10
        while self.client.ok("get_job", {"job_id": ident}).get("observed_state") != "launcher_lost":
            self.assertLess(time.time(), deadline, "the lost launcher was not observed")
            time.sleep(0.1)
        task = self.client.request("tasks/get", {"taskId": created["taskId"]}, tasks=True)["result"]
        self.assertEqual(task["status"], "working")
        self.assertIn("launcher_lost", task["statusMessage"])
        # The orphaned worker finishes; the server finalizes the attempt with
        # the worker's exact result.
        task = self.poll_task(created["taskId"])
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["result"]["isError"])
        self.assertEqual(task["result"]["structuredContent"]["job"]["state"], "completed")
        self.assertEqual(task["result"]["structuredContent"]["result"]["claims"], {"best_found": 1})

    def test_a_corrupt_task_store_is_an_error_not_a_hang(self):
        (self.root / "mcp").mkdir(exist_ok=True)
        (self.root / "mcp" / "tasks.json").write_text("[]")
        error = self.client.request("tasks/get", {"taskId": "task-x"}, tasks=True)["error"]
        self.assertEqual(error["code"], -32603)
        # The job still starts; the client gets its handle instead of a task.
        result = self.client.tool("submit_job", {"job": fake("store", {"mode": "complete"})}, tasks=True)
        self.assertEqual(result["structuredContent"]["job_id"], job_id("store"))
        self.assertNotIn("taskId", result)


class Review(Server):
    """Defects found by the review of the first version, kept fixed."""

    def test_a_cancelled_submission_still_creates_its_job(self):
        job = fake("cancelled-submit", {"mode": "complete", "validate_sleep": 2})
        ident = self.client.start("tools/call", {"name": "submit_job", "arguments": {"job": job}})
        time.sleep(1)
        self.client.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": ident}})
        deadline = time.time() + 20
        while True:
            reply = self.client.tool("get_job", {"job_id": job_id("cancelled-submit")})
            if not reply.get("isError") and reply["structuredContent"]["state"] in TERMINAL:
                break
            self.assertLess(time.time(), deadline, f"the job was not created: {reply}")
            time.sleep(0.2)
        self.assertNotIn(ident, self.client.responses)
        # The key stays usable: the same job comes back.
        self.assertEqual(self.client.ok("submit_job", {"job": job})["job_id"], job_id("cancelled-submit"))

    def test_identity_includes_the_worker(self):
        job = fake("identity", {"mode": "complete"})
        self.wait(self.client.ok("submit_job", {"job": job})["job_id"])
        changed = self.base / "fake_worker_changed.py"
        changed.write_text(FAKE.read_text() + "\n# another build\n")
        changed.chmod(0o755)
        self.call("workers", "add", "--id", "fake", "--executable", str(changed))
        self.assertEqual(self.client.error("submit_job", {"job": job})["code"], "request_key_conflict")
        self.assertTrue(self.client.tool("submit_job", {"job": job}, tasks=True)["isError"])

    def test_spec_path_must_be_a_bounded_regular_file(self):
        fifo = self.base / "fifo"
        os.mkfifo(fifo)
        for path in ["/dev/zero", str(fifo), str(self.base)]:
            with self.subTest(path=path):
                start = time.time()
                error = self.client.error("validate_job", {"spec_path": path})
                self.assertEqual(error["code"], "invalid_arguments")
                self.assertLess(time.time() - start, 5)

    def test_large_result_manifests(self):
        ident = self.client.ok("submit_job", {"job": fake("large", {"mode": "complete"})})["job_id"]
        self.wait(ident)
        created = self.client.tool("submit_job", {"job": fake("large", {"mode": "complete"})}, tasks=True)
        manifest_path = self.root / "jobs" / ident / "run.json"
        manifest = json.loads(manifest_path.read_text())
        record = manifest["results"][0]
        manifest["results"] = [{**record, "task_id": i} for i in range(250_000)]
        manifest_path.write_text(json.dumps(manifest, indent=2))
        self.assertGreater(manifest_path.stat().st_size, 64 * 1024 * 1024)
        summary = self.client.ok("get_result", {"job_id": ident})
        self.assertEqual(summary["claims"], {"best_found": 250_000})
        self.assertEqual((len(summary["tasks"]), summary["tasks_omitted"]), (100, 249_900))
        self.assertEqual(len(self.client.ok("get_result", {"job_id": ident, "tasks": [7, 249_999]})["tasks"]), 2)
        self.assertEqual(self.client.error("get_result", {"job_id": ident, "full": True})["code"], "result_too_large")
        task = self.poll_task(created["taskId"])
        self.assertFalse(task["result"]["isError"])
        # The summary does not hold the manifest as a JSON tree, which would
        # take several times the file's size.
        status = (proc_entry(self.client.process.pid) / "status").read_text().splitlines()
        peak = int(next(line for line in status if line.startswith("VmHWM:")).split()[1]) * 1024
        self.assertLess(peak, 4 * manifest_path.stat().st_size)

    def test_an_input_named_like_the_staged_job(self):
        data = self.base / "inputs"
        data.mkdir()
        (data / "job.json").write_text("{}")
        job = fake("named", {"mode": "complete"})
        job["inputs"] = [{"name": "model", "file": "job.json",
                          "sha256": hashlib.sha256(b"{}").hexdigest()}]
        ident = self.client.ok("submit_job", {"job": job, "input_dir": str(data)})["job_id"]
        self.assertEqual(self.wait(ident)["state"], "completed")

    def test_batches_bytes_duplicates_and_version_messages(self):
        self.client.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                           "clientInfo": {"name": "batch", "version": "1"}}, modern=False)
        self.client.send([{"jsonrpc": "2.0", "id": "a", "method": "tools/list"},
                          {"jsonrpc": "2.0", "method": "notifications/initialized"},
                          {"jsonrpc": "2.0", "id": "b", "method": "ping"}])
        message = self.client.messages.get(timeout=30)
        self.assertIsInstance(message, list)
        self.assertEqual(sorted(m["id"] for m in message), ["a", "b"])
        self.client.send([])
        self.assertEqual(self.client.messages.get(timeout=30)["error"]["code"], -32600)
        # Batches belong to 2025-03-26 only.
        other = self.connect()
        other.send([{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta()}}])
        error = other.messages.get(timeout=30)
        self.assertEqual(error["error"]["code"], -32600)
        self.assertIn("2025-03-26", error["error"]["message"])
        # A line that is not UTF-8 is a parse error, and the server goes on.
        self.client.process.stdin.flush()
        self.client.process.stdin.buffer.write(b"\xff\xfe\n")
        self.client.process.stdin.buffer.flush()
        self.assertEqual(self.client.messages.get(timeout=30)["error"]["code"], -32700)
        self.assertEqual(self.client.request("tools/list")["result"]["resultType"], "complete")
        # A request ID in use is rejected without answering under that ID.
        ident = self.client.ok("submit_job", {"job": fake("dup", {"mode": "sleep", "seconds": 60})})["job_id"]
        self.client.send({"jsonrpc": "2.0", "id": "dup", "method": "tools/call", "params": {
            "_meta": meta(), "name": "wait_job", "arguments": {"job_id": ident, "timeout_seconds": 3}}})
        self.client.send({"jsonrpc": "2.0", "id": "dup", "method": "tools/list", "params": {"_meta": meta()}})
        rejected = self.client.messages.get(timeout=30)
        self.assertEqual((rejected["id"], rejected["error"]["code"]), (None, -32600))
        self.assertIn("result", self.client.response("dup"))
        while self.client.pump(1):
            pass
        self.assertNotIn("dup", self.client.responses)
        # A legacy version in _meta is pointed to initialize.
        ident = self.client.start("tools/list", modern=False, extra_meta={
            "io.modelcontextprotocol/protocolVersion": "2025-11-25",
            "io.modelcontextprotocol/clientCapabilities": {}})
        error = self.client.response(ident)["error"]
        self.assertEqual(error["code"], -32022)
        self.assertIn("initialize", error["message"])


class Limits(Server):
    """Bounds on what one client can make the server hold (review OJ-03)."""

    def test_an_overlong_message_is_skipped_and_the_server_goes_on(self):
        self.client.process.stdin.flush()
        chunk = b"x" * (1 << 20)
        for _ in range(65):
            self.client.process.stdin.buffer.write(chunk)
        self.client.process.stdin.buffer.write(b"\n")
        self.client.process.stdin.buffer.flush()
        error = self.client.messages.get(timeout=60)
        self.assertEqual((error["id"], error["error"]["code"]), (None, -32600))
        self.assertIn("longer than", error["error"]["message"])
        self.assertEqual(self.client.request("tools/list")["result"]["resultType"], "complete")
        # The rest of the overlong line was consumed, not kept: the server
        # holds about one message, not the 65 MiB line.
        status = proc_entry(self.client.process.pid) / "status"
        peak = int(next(line for line in status.read_text().splitlines()
                        if line.startswith("VmHWM:")).split()[1]) * 1024
        self.assertLess(peak, 200 * 1024 * 1024)

    def test_waiting_requests_leave_room_for_short_ones(self):
        ident = self.client.ok("submit_job", {"job": fake("waits", {"mode": "sleep", "seconds": 60})})["job_id"]
        waits = [self.client.start("tools/call", {"name": "wait_job",
                                                  "arguments": {"job_id": ident, "timeout_seconds": 60}})
                 for _ in range(32)]
        time.sleep(0.5)
        refused = self.client.request("tools/call", {"name": "wait_job",
                                                     "arguments": {"job_id": ident, "timeout_seconds": 1}})
        self.assertEqual(refused["error"]["code"], -32000)
        self.assertTrue(refused["error"]["data"]["retryable"])
        # Status and cancellation still get through.
        self.assertEqual(self.client.ok("get_job", {"job_id": ident})["state"], "running")
        self.assertIn(self.client.ok("cancel_job", {"job_id": ident})["state"], {"running", "cancelled"})
        for ident in waits:
            self.client.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                              "params": {"requestId": ident}})
        # Ended waits give their places back.
        deadline = time.time() + 20
        while True:
            reply = self.client.request("tools/call", {"name": "wait_job", "arguments": {
                "job_id": job_id("waits"), "timeout_seconds": 1}})
            if "result" in reply or time.time() > deadline:
                break
            time.sleep(0.2)
        self.assertIn("result", reply)

    def test_inputs_of_an_invalid_envelope_are_not_copied(self):
        # Seventeen inputs that do not exist: the envelope is rejected for
        # its input count before any of them is looked at.
        job = fake("inputs", {"mode": "complete"})
        job["inputs"] = [{"name": f"i{k}", "file": f"missing-{k}.json", "sha256": "0" * 64}
                         for k in range(17)]
        error = self.client.error("validate_job", {"job": job})
        self.assertEqual(error["code"], "invalid_job")
        self.assertIn("input count", error["message"])
        self.assertNotIn("missing-", error["message"])


class Requests(Server):
    def test_a_cancelled_request_gets_no_response(self):
        ident = self.client.ok("submit_job", {"job": fake("long", {"mode": "sleep", "seconds": 60})})["job_id"]
        waiting = self.client.start("tools/call", {"name": "wait_job",
                                                   "arguments": {"job_id": ident, "timeout_seconds": 60}})
        time.sleep(1)
        self.client.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                          "params": {"requestId": waiting, "reason": "test"}})
        self.assertEqual(self.client.ok("get_job", {"job_id": ident})["state"], "running")
        time.sleep(2)
        while self.client.pump(0.1):
            pass
        self.assertNotIn(waiting, self.client.responses)

    def test_progress_notifications(self):
        ident = self.client.ok("submit_job", {"job": fake("progress", {"mode": "complete"})})["job_id"]
        self.wait(ident)
        result = self.client.tool("wait_job", {"job_id": ident}, extra_meta={"progressToken": "p1"})
        self.assertFalse(result["isError"])
        progress = [m["params"] for m in self.client.notifications if m["method"] == "notifications/progress"]
        self.assertEqual(progress[0]["progressToken"], "p1")
        self.assertEqual((progress[0]["progress"], progress[0]["total"]), (1, 1))

    def test_concurrent_requests_and_end_of_input(self):
        ident = self.client.ok("submit_job", {"job": fake("eof", {"mode": "sleep", "seconds": 60})})["job_id"]
        slow = self.client.start("tools/call", {"name": "wait_job", "arguments": {"job_id": ident, "timeout_seconds": 3}})
        quick = self.client.start("tools/call", {"name": "describe_node", "arguments": {}})
        first = None
        while first is None:
            self.client.pump(10)
            first = next(iter(self.client.responses), None)
        self.assertEqual(first, quick)
        self.client.response(slow)
        self.client.process.stdin.close()
        self.assertEqual(self.client.process.wait(timeout=10), 0)
        # The job outlives the server.
        self.assertEqual(self.call("jobs", "get", ident)["state"], "running")


if __name__ == "__main__":
    unittest.main()
