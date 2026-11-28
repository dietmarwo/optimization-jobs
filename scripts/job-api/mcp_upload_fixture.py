"""Loopback-only data endpoint for the Files draft tests.

The MCP server issues a short-lived grant in NODE/mcp/uploads.
This endpoint stages the exact declared length and leaves confirmation and
publication to optimization-mcp. It is a test fixture for a single owner.
"""

import json
import os
import re
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class UploadServer(ThreadingHTTPServer):
    def __init__(self, staging):
        self.staging = staging
        super().__init__(("127.0.0.1", 0), UploadRequest)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class UploadRequest(BaseHTTPRequestHandler):
    def log_message(self, *_):
        # The request target is a bearer grant.
        pass

    def do_PUT(self):
        match = re.fullmatch(r"/uploads/([0-9a-f]{32})", self.path)
        if not match:
            self.send_error(404)
            return
        file = self.server.staging / match[1]
        try:
            grant = json.loads(file.with_suffix(".json").read_text())
        except (OSError, ValueError):
            self.send_error(404)
            return
        if time.time() >= grant["target_expires_at"]:
            self.send_error(410)
            return
        if (self.headers.get("Transfer-Encoding") or
                self.headers.get_all("Content-Length") != [str(grant["size"])]):
            self.send_error(400)
            return
        if self.headers.get("Authorization") or self.headers.get("Cookie"):
            self.send_error(400)
            return

        self.connection.settimeout(10)
        try:
            with tempfile.NamedTemporaryFile(dir=self.server.staging, prefix=".incoming-") as upload:
                remaining = grant["size"]
                while remaining:
                    chunk = self.rfile.read(min(64 * 1024, remaining))
                    if not chunk:
                        return
                    upload.write(chunk)
                    remaining -= len(chunk)
                if time.time() >= grant["expires_at"]:
                    self.send_error(410)
                    return
                upload.flush()
                os.fsync(upload.fileno())
                try:
                    os.link(upload.name, file.with_suffix(".upload"))
                except FileExistsError:
                    # The first complete body for this grant is immutable.
                    self.send_error(409)
                    return
        except (ConnectionError, TimeoutError):
            return
        self.send_response(204)
        self.end_headers()
