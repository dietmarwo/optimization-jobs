#!/usr/bin/env python3
"""Files wire acceptance with a separately implemented loopback endpoint."""

import base64
import concurrent.futures
from contextlib import closing
import hashlib
import http.client
import io
import json
import os
import time
import unittest
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from mcp_upload_fixture import UploadServer
from test_mcp import LP_MODEL, REAL, TARGET, Server, fake

MAX_BYTES = 64 * 1024 * 1024
EXTENSION = "io.modelcontextprotocol/files"
OPT_IN = {"io.modelcontextprotocol/clientCapabilities": {"extensions": {EXTENSION: {"upload": {}}}}}


def metadata(data, file_id="lp-model", *, size=None):
    return {"id": file_id, "name": "model.json", "mimeType": "application/json",
            "size": len(data) if size is None else size,
            "digest": {"algorithm": "sha-256", "value": base64.urlsafe_b64encode(
                hashlib.sha256(data).digest()).decode().rstrip("=")}}


class Files(Server):
    def setUp(self):
        super().setUp()
        self.staging = self.root / "mcp/uploads"
        self.endpoint = UploadServer(self.staging)
        self.addCleanup(self.endpoint.server_close)
        thread = Thread(target=self.endpoint.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.endpoint.shutdown)
        self.upload = self.connect("--files-endpoint", self.endpoint.origin)

    def call_upload(self, file, state=None, *, client=None, opt_in=True):
        params = {"name": "upload_input", "arguments": {"file": file}}
        if state is not None:
            params["requestState"] = state
        return (client or self.upload).request("tools/call", params, extra_meta=OPT_IN if opt_in else None)

    def begin(self, file, client=None):
        grant = self.call_upload(file, client=client)["result"]
        self.assertEqual(grant["resultType"], "upload_required")
        self.assertNotIn("structuredContent", grant)
        self.assertNotIn("content", grant)
        self.assertEqual(grant["uploads"][0]["fileId"], file["id"])
        return grant

    def transport(self, grant, body, length, *, partial=False):
        upload, = grant["uploads"]
        target = urlsplit(upload["url"])
        # Explicit operator allowlist for this test endpoint. http.client
        # connects to the exact origin and never follows a redirect.
        self.assertEqual(f"{target.scheme}://{target.netloc}", self.endpoint.origin)
        self.assertEqual(upload["credentials"], "omit")
        self.assertEqual(upload["method"], "PUT")
        with closing(http.client.HTTPConnection(target.hostname, target.port, timeout=15)) as connection:
            if partial:
                connection.putrequest("PUT", target.path)
                connection.putheader("Content-Length", str(length))
                connection.endheaders(body)
                return None
            connection.request("PUT", target.path, body, headers={"Content-Length": str(length)})
            with connection.getresponse() as response:
                response.read()
                return response.status

    def complete(self, file, grant, client=None):
        ack = self.call_upload(file, grant["requestState"], client=client)["result"]
        self.assertEqual(ack["resultType"], "complete")
        return ack

    def assert_error(self, response, code):
        result = response.get("result", response)
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], code)

    def test_discovery_and_unaware_clients(self):
        def names(response):
            return [tool["name"] for tool in response["result"]["tools"]]

        self.assertNotIn(EXTENSION, self.client.request("server/discover")["result"]["capabilities"]["extensions"])
        self.assertNotIn("upload_input", names(self.client.request("tools/list", extra_meta=OPT_IN)))
        self.assertIn(EXTENSION, self.upload.request("server/discover")["result"]["capabilities"]["extensions"])
        general = self.upload.request("tools/list")
        self.assertNotIn("upload_input", names(general))
        self.assertEqual(general["result"]["cacheScope"], "public")
        self.assertGreater(general["result"]["ttlMs"], 0)
        result = self.upload.request("tools/list", extra_meta=OPT_IN)
        self.assertIn("upload_input", names(result))
        self.assertEqual(result["result"]["cacheScope"], "private")
        self.assertEqual(result["result"]["ttlMs"], 0)
        tool = next(tool for tool in result["result"]["tools"] if tool["name"] == "upload_input")
        self.assertEqual(tool["inputSchema"]["properties"]["file"]["x-mcp-file"]["maxSize"], MAX_BYTES)
        error = self.call_upload(metadata(b"model"), opt_in=False)["error"]
        self.assertEqual(error["code"], -32021)
        self.assertIn("upload", error["data"]["requiredCapabilities"]["extensions"][EXTENSION])
        self.assert_error(self.call_upload(metadata(b"", size=MAX_BYTES + 1)), "invalid_arguments")
        empty = self.call_upload(metadata(b""))["result"]
        self.assertEqual(empty["resultType"], "complete")
        self.assertEqual(empty["structuredContent"]["bytes"], 0)
        self.assertFalse(list(self.staging.glob("*.json")))

    def test_restart_argument_equality_and_repeated_confirmation(self):
        body = b"LP input bytes"
        file = metadata(body)
        grant = self.begin(file)
        self.assertEqual(self.transport(grant, body, len(body)), 204)
        self.upload.close()
        next_server = self.connect("--files-endpoint", self.endpoint.origin)
        key = self.root / "mcp/files.key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        # Reorder the metadata and use a numerically equivalent size.
        equivalent = dict(reversed(list(file.items())))
        equivalent["size"] = float(equivalent["size"])
        answer = self.complete(equivalent, grant, next_server)
        expected = hashlib.sha256(body).hexdigest()
        self.assertEqual(answer["structuredContent"]["sha256"], expected)
        self.assertEqual(answer, self.complete(file, grant, next_server))
        self.assertEqual((self.root / "mcp/inputs" / expected).read_bytes(), body)
        modified = {**file, "name": "other.json"}
        self.assertEqual(self.call_upload(modified, grant["requestState"], client=next_server)["error"]["code"],
                         -32602)
        state = grant["requestState"]
        at = state.rfind(".") + 1
        tampered = state[:at] + ("A" if state[at] != "A" else "B") + state[at + 1:]
        self.assertEqual(self.call_upload(file, tampered, client=next_server)["error"]["code"], -32602)
        self.assertEqual(next_server.request("tools/call", {"name": "put_input", "arguments": {"content": "x"},
                                                           "requestState": state})["error"]["code"], -32602)
        self.assertFalse(list((self.root / "jobs").glob("*")))

    def test_partial_wrong_bytes_and_expired_grant(self):
        body = b"expected"
        file = metadata(body)
        grant = self.begin(file)
        self.transport(grant, b"ex", len(body), partial=True)
        self.assert_error(self.complete(file, grant), "upload_not_received")
        self.assertEqual(self.transport(grant, b"wrongsha", len(body)), 204)
        self.assert_error(self.complete(file, grant), "upload_invalid")
        self.assertFalse(list((self.root / "mcp/inputs").glob("*")))

        expired = self.begin(file)
        token = urlsplit(expired["uploads"][0]["url"]).path.rsplit("/", 1)[-1]
        ticket_path = self.staging / (token + ".json")
        ticket = json.loads(ticket_path.read_text())
        ticket["target_expires_at"] = int(time.time()) - 1
        ticket["expires_at"] = int(time.time()) - 1
        ticket_path.write_text(json.dumps(ticket))
        self.assertEqual(self.transport(expired, body, len(body)), 410)
        restarted = self.connect("--files-endpoint", self.endpoint.origin)
        restarted.request("server/discover")
        self.assertFalse(ticket_path.exists())
        self.assertFalse(list((self.root / "mcp/inputs").glob("*")))

    def test_quota_and_concurrent_deduplication(self):
        body = b"shared"
        file = metadata(body)
        client = self.connect("--files-endpoint", self.endpoint.origin, "--input-store-bytes", str(len(body)))
        self.assert_error(self.call_upload(metadata(b"x" * (len(body) + 1)), client=client), "input_store_full")
        other = self.connect("--files-endpoint", self.endpoint.origin, "--input-store-bytes", str(len(body)))
        grants = [self.begin(file, c) for c in (client, other)]
        for grant in grants:
            self.assertEqual(self.transport(grant, body, len(body)), 204)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first, second = pool.map(lambda pair: self.complete(file, pair[0], pair[1]), zip(grants, (client, other)))
        self.assertEqual(first["structuredContent"], second["structuredContent"])
        self.assertEqual(len(list((self.root / "mcp/inputs").iterdir())), 1)

    def test_maximum_file_round_trip_to_lp_worker(self):
        binary = TARGET / REAL["lp-ip"][0]
        if not binary.is_file():
            if os.environ.get("JOB_API_REQUIRE_WORKER") == "1":
                self.fail("lp-ip-job-worker is required for the 64 MiB Files acceptance")
            self.skipTest("lp-ip-job-worker is required for the 64 MiB Files acceptance")
        if not any(worker["worker"] == "lp-ip" for worker in self.client.ok("describe_node")["workers"]):
            self.call("workers", "add", "--id", "lp-ip", "--executable", str(binary))

        def measured_upload(data):
            count_before = self.upload.sent_bytes + self.upload.received_bytes
            file = metadata(data)
            grant = self.begin(file)
            self.assertEqual(self.transport(grant, io.BytesIO(data), len(data)), 204)
            done = self.complete(file, grant)
            self.assertFalse(done["isError"])
            reference = done["structuredContent"]
            self.assertEqual(reference["bytes"], len(data))
            self.assertEqual(reference["sha256"], hashlib.sha256(data).hexdigest())
            control_bytes = self.upload.sent_bytes + self.upload.received_bytes - count_before
            self.assertLess(control_bytes, 8192)
            status = Path(f"/proc/{self.upload.process.pid}/status")
            rss = next((line.split()[1] for line in status.read_text().splitlines()
                        if line.startswith("VmHWM:")), "unavailable") if status.is_file() else "unavailable"
            print(f"Files input {len(data)} bytes, JSON-RPC {control_bytes} bytes, server VmHWM {rss} KiB")
            return reference

        # Include the control framing in the comparison. Even an unescaped
        # text payload of exactly MAX_BYTES exceeds the line limit.
        padded = LP_MODEL + b" " * (MAX_BYTES - len(LP_MODEL))
        results = []
        for name, data in (("plain", LP_MODEL), ("padded", padded)):
            reference = measured_upload(data)
            job = {**fake(name, REAL["lp-ip"][2]), "worker": "lp-ip", "payload_schema": REAL["lp-ip"][1]}
            job["inputs"] = [{"name": "model", "file": reference["file"], "sha256": reference["sha256"]}]
            args = {"job": job, "input_dir": reference["input_dir"]}
            self.assertGreater(self.upload.ok("validate_job", args)["resolved"]["task_count"], 0)
            handle = self.upload.ok("submit_job", args)
            self.assertEqual(self.wait(handle["job_id"])["state"], "completed")
            results.append(self.client.ok("get_result", {"job_id": handle["job_id"]})["tasks"][0])
        for key in ("objective", "claim", "evidence", "termination"):
            self.assertEqual(results[0][key], results[1][key])
        self.assertIsInstance(results[0]["objective"], (float, int))


if __name__ == "__main__":
    unittest.main()
