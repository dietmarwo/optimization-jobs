#!/usr/bin/env python3
"""Render actual MODE and MAP-Elites jobs in the pinned Inspector Web host.

Requires the SDK test project, Playwright and a working Chromium installation.
Set MCP_APP_CHROMIUM to use a system Chromium. JOB_API_TARGET must contain both
runner binaries and fcmaes-job-worker.
"""
import argparse
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

from test_mcp import Client, MCP, REAL, RUN, TARGET, mcp_only

INSPECTOR = Path(__file__).parent / "sdk-client/node_modules/.bin/mcp-inspector"


def port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def run(root, *args):
    return subprocess.run([str(RUN), "--root", str(root), *map(str, args)],
                          check=True, capture_output=True, text=True, timeout=30)


def jobs(root):
    run(root, "node", "init", "--capacity", "2")
    run(root, "workers", "add", "--id", "fcmaes", "--executable", TARGET / REAL["fcmaes"][0])
    client = Client(root)
    try:
        examples = client.ok("describe_worker", {"worker": "fcmaes"})["examples"]
        output = []
        for profile in ("fcmaes.mode/1", "fcmaes.map-elites/1"):
            example = next(item for item in examples if item["profile"] == profile)
            args = mcp_only(client, "fcmaes", example, "inspector-" + profile.split("/")[0])
            if profile == "fcmaes.map-elites/1":
                payload = args["job"]["payload"]
                payload["archive"]["capacity"] = 400
                payload["generations"] = 100
                payload["optimizer"]["parameters"]["chunk_size"] = 50
            job_id = client.ok("submit_job", args)["job_id"]
            job = client.ok("wait_job", {"job_id": job_id, "timeout_seconds": 30})
            assert job["state"] == "completed", job["state"]
            result = client.ok("get_result", {"job_id": job_id, "tasks": [0]})
            output.append((profile, job_id, result["tasks"][0]["outcome"]["details"]))
        return output
    finally:
        client.close()


def wait_http(number):
    for _ in range(100):
        try:
            with closing(http.client.HTTPConnection("127.0.0.1", number, timeout=0.5)) as connection:
                connection.request("GET", "/")
                with connection.getresponse() as reply:
                    if reply.status == 200:
                        return
        except OSError:
            pass
        time.sleep(0.1)
    raise TimeoutError("MCP Inspector Web did not start")


def wait_for_view(page, expected):
    for _ in range(100):
        for frame in page.frames[1:]:
            title = frame.locator("h1#title")
            try:
                if title.count() and title.text_content() == expected:
                    return frame
            except Error:
                if not frame.is_detached():
                    raise
        page.wait_for_timeout(100)
    raise AssertionError(f"Inspector did not render {expected}. Visible text: {page.locator('main').inner_text()[-1000:]}")


def view(page, url, profile, job_id, details):
    page.goto(url)
    page.get_by_role("switch", name="Connect or disconnect").press("Space")
    page.get_by_text("MCP 2026-07-28", exact=True).wait_for()
    page.get_by_text("Apps", exact=True).click()
    page.get_by_role("button", name="View an optimization result").click()
    page.get_by_label(re.compile("^job_id")).fill(job_id)
    page.get_by_label(re.compile("^task_id")).fill("0")
    page.get_by_role("button", name="Open App").click()

    mode = profile == "fcmaes.mode/1"
    frame = wait_for_view(page, "MODE Pareto front" if mode else "MAP-Elites archive")
    assert frame.locator("#chart").is_visible()
    chart = frame.locator("#chart")
    assert chart.evaluate("""canvas => canvas.getContext('2d')
        .getImageData(0, 0, canvas.width, canvas.height).data.some(value => value !== 0)""")
    def formatted(value):
        return frame.evaluate(
            "(value) => new Intl.NumberFormat(undefined, {maximumSignificantDigits: 7}).format(value)",
            value,
        )
    metrics = frame.locator("#metrics").inner_text()
    shown = frame.locator("#counts").inner_text()
    if mode:
        assert "final_population" in metrics
        assert "Hypervolume " + formatted(details["hypervolume"]["value"]) in metrics
        assert f"of {len(details['front'])} front points" in shown
        assert "Reference point" in frame.locator("#note").inner_text()
    else:
        assert "Coverage " + formatted(100 * details["coverage"]) + "%" in metrics
        assert "QD score " + formatted(details["qd_score"]) in metrics
        assert f"of {details['occupied']} occupied cells" in shown
        frame.get_by_role("button", name="Next", exact=True).click()
        frame.get_by_text(re.compile(r"Showing 129–")).wait_for()
    page.set_viewport_size({"width": 390, "height": 760})
    chart.wait_for(state="visible")
    width = frame.evaluate("innerWidth")
    assert 120 <= width <= 400, f"Unexpected narrow viewer width: {width}"
    assert frame.evaluate("document.documentElement.scrollWidth <= innerWidth")
    print(f"Inspector 2.17.0, modern stdio: {profile}, {metrics}; "
          f"{frame.locator('#counts').inner_text()}; narrow view {width}px")
    page.set_viewport_size({"width": 1100, "height": 800})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default=os.environ.get("MCP_APP_CHROMIUM"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="optimization-mcp-apps-") as directory:
        scratch = Path(directory)
        root = scratch / "node"
        examples = jobs(root)
        main_port, sandbox_port = port(), port()
        token = secrets.token_hex(32)
        environment = {**os.environ, "CLIENT_PORT": str(main_port), "MCP_SANDBOX_PORT": str(sandbox_port),
                       "MCP_INSPECTOR_SECRET_STORE": "memory", "MCP_AUTO_OPEN_ENABLED": "false",
                       "MCP_INSPECTOR_API_TOKEN": token}
        with (scratch / "inspector.log").open("wb") as log:
            inspector = subprocess.Popen([str(INSPECTOR), "--web", "--protocol-era", "modern",
                                         str(MCP), "--root", str(root)], env=environment, stdout=log, stderr=log)
            try:
                wait_http(main_port)
                url = f"http://127.0.0.1:{main_port}?MCP_INSPECTOR_API_TOKEN={token}"
                with sync_playwright() as playwright:
                    with playwright.chromium.launch(executable_path=args.chromium) as browser:
                        page = browser.new_page(viewport={"width": 1100, "height": 800})
                        for example in examples:
                            view(page, url, *example)
                            page.get_by_role("button", name="Disconnect from server").click()
                        print(f"Chromium {browser.version}")
            finally:
                inspector.terminate()
                try:
                    inspector.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    inspector.kill()
                    inspector.wait()


if __name__ == "__main__":
    main()
