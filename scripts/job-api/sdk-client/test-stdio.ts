import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test, type TestContext } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { SkillsClient } from "@modelcontextprotocol/client/ext/skills";
import { McpUiToolMetaSchema, RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps";
import { createTaskSessionFromClient } from "@modelcontextprotocol/ext-tasks/client";

const here = dirname(fileURLToPath(import.meta.url));
const binaries = resolve(process.env.JOB_API_TARGET ?? join(here, "../../../target/release"));
const protocol = "2026-07-28";
const tasksExtension = "io.modelcontextprotocol/tasks";
const skills = ["choose-optimization-solver", "interpret-optimization-result", "run-optimization-job"];
const skillsBase = "skill://optimization-jobs/";
const dispatches = new WeakMap();
const clientInfo = { name: "optimization-jobs SDK regression", version: "1.0.0" };

const sha256 = (data) => createHash("sha256").update(data).digest("hex");

function envelope(key: string, payload: Record<string, unknown>, wallTime = 30) {
  return {
    schema_version: "optimization.job/0.1",
    request_key: key,
    worker: "fake",
    payload_schema: "test.fake/1",
    payload,
    inputs: [],
    resources: { cpu_slots: 1, outer_workers: 1, inner_threads: 1 },
    limits: { wall_time_seconds: wallTime, grace_seconds: 0.5 },
  };
}

async function setup(t: TestContext) {
  const root = await mkdtemp(join(tmpdir(), "optimization-mcp-sdk-"));
  const runner = join(binaries, "optimization-run");
  const command = join(binaries, "optimization-mcp");
  const args = ["--root", root];
  const run = (...argv) => execFileSync(runner, [...args, ...argv], { encoding: "utf8" });
  run("node", "init", "--capacity", "8");
  run("workers", "add", "--id", "fake", "--executable", join(here, "../fake_worker.py"));
  await mkdir(join(root, "jobs"), { recursive: true });
  const clients = [];
  t.after(async () => {
    await Promise.allSettled(clients.map((client) => client.close()));
    for (const id of await readdir(join(root, "jobs"))) {
      const job = JSON.parse(await readFile(join(root, "jobs", id, "job.json"), "utf8"));
      if (["submitted", "starting", "waiting", "running"].includes(job.state)) {
        run("jobs", "cancel", id, "--now");
      }
    }
    await rm(root, { recursive: true, force: true });
  });

  async function connect(capabilities = {}) {
    const client = new Client(
      clientInfo,
      { capabilities, versionNegotiation: { mode: { pin: protocol } } },
    );
    clients.push(client);
    const transport = new StdioClientTransport({ command, args, stderr: "pipe" });
    await client.connect(transport);
    dispatches.set(client, extensionDispatch(transport));
    assert.equal(client.getProtocolEra(), "modern");
    assert.equal(client.getNegotiatedProtocolVersion(), protocol);
    assert.equal(client.getDiscoverResult()._meta["io.modelcontextprotocol/serverInfo"].name,
      "optimization-mcp");
    return client;
  }

  return { root, command, args, connect };
}

// The base SDK rejects the Tasks result discriminator before decoding. The
// extension adapter expects a raw coordinator. Use the same SDK transport
// and keep extension request IDs separate from the base client's numeric IDs.
function extensionDispatch(transport: StdioClientTransport) {
  const baseReceiver = transport.onmessage;
  const pending = new Map();
  let nextId = 0;
  transport.onmessage = (message, extras) => {
    const receive = !("method" in message) && pending.get(message.id);
    if (receive) receive(message);
    else baseReceiver(message, extras);
  };
  return (request, options) => {
    const id = `tasks-${++nextId}`;
    return new Promise((resolve, reject) => {
      const signal = options?.signal;
      const clean = () => {
        clearTimeout(timer);
        pending.delete(id);
        signal?.removeEventListener("abort", abort);
      };
      const fail = (error) => {
        clean();
        reject(error);
      };
      const abort = () => fail(signal.reason);
      const timer = setTimeout(() => fail(new Error(`Timed out waiting for ${request.method}`)), 20_000);
      if (signal?.aborted) {
        abort();
        return;
      }
      pending.set(id, (response) => {
        clean();
        resolve({ ...response, id: request.id });
      });
      signal?.addEventListener("abort", abort, { once: true });
      transport.send({ ...request, id }).catch(fail);
    });
  };
}

function taskSession(client, endpointId) {
  return createTaskSessionFromClient(client, {
    endpointId,
    v2RequestFraming: { protocolVersion: protocol, clientInfo, clientCapabilities: {} },
    rawDispatch: dispatches.get(client),
  });
}

async function tool(client, name, args) {
  const result = await client.callTool({ name, arguments: args });
  assert.equal(result.isError, false, JSON.stringify(result.structuredContent));
  return result.structuredContent;
}

async function until(callback) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const result = await callback();
    if (result) return result;
    await delay(100);
  }
  assert.fail("observation did not arrive before the deadline");
}

test("official Tasks client recovers a detached optimization job over modern stdio", async (t) => {
  const fixture = await setup(t);
  const first = await fixture.connect();
  assert.deepEqual(first.getServerCapabilities().extensions[tasksExtension], {});
  const endpointId = "optimization-jobs:" + fixture.root;
  const session = taskSession(first, endpointId);

  const job = envelope("resume", { mode: "complete", seconds: 4 });
  const job_id = sha256(job.request_key).slice(0, 32);
  const execution = await session.callTool("submit_job", { job });
  assert.equal(execution.kind, "task");
  await until(async () => (await tool(first, "get_job", { job_id })).state === "running");
  const refPath = join(fixture.root, "sdk-task.json");
  await execution.handoff((reference) => writeFile(refPath, JSON.stringify(reference), { mode: 0o600 }));
  // Tear down transport before disposing the old session. The pinned
  // adapter's close may send best-effort cancellation for live executions.
  await first.close();
  await session.close();

  const client = await fixture.connect();
  const recovered = taskSession(client, endpointId);
  t.after(() => recovered.close());
  const reference = JSON.parse(await readFile(refPath, "utf8"));
  assert.equal(reference.generation, "v2");
  assert.equal(reference.endpointId, endpointId);
  const resumed = await recovered.resumeTask(reference);
  assert.equal(resumed.handle.taskId, reference.taskId);
  const { outcome } = await resumed.settle();
  assert.equal(outcome.status, "completed", outcome.error?.stack);
  assert.equal(outcome.result.isError, false);
  assert.equal(outcome.result.structuredContent.job.job_id, job_id);
  const result = await tool(client, "get_result", { job_id });
  assert.deepEqual(outcome.result.structuredContent.result, result);
  assert.deepEqual(result.claims, { best_found: 1 });
  assert.equal(result.accounting_complete, true);
  assert.equal(result.tasks[0].evidence, null); // Legacy fixture worker.
  assert.equal(result.tasks[0].termination, "evaluation_limit");

  const again = await recovered.callTool("submit_job", { job });
  assert.equal(again.handle.taskId, reference.taskId);
  await again.settle();
  assert.deepEqual(await readdir(join(fixture.root, "jobs")), [job_id]);
});

test("official Tasks client observes cancellation, a timed-out run and a failed worker", async (t) => {
  const fixture = await setup(t);
  const client = await fixture.connect();
  const session = taskSession(client, fixture.root);
  t.after(() => session.close());

  let job = envelope("cancel", { mode: "sleep", seconds: 3 });
  const job_id = sha256(job.request_key).slice(0, 32);
  const running = await session.callTool("submit_job", { job });
  await until(async () => (await tool(client, "get_job", { job_id })).state === "running");
  await session.task(running.handle.taskId).cancel();
  const cancelled = await running.settle();
  assert.equal(cancelled.outcome.status, "cancelled");
  assert.equal((await tool(client, "get_result", { job_id })).state, "cancelled");

  for (const [state, payload, wall, isError] of [
    ["timed_out", { mode: "sleep", seconds: 8 }, 1, false],
    ["failed", { mode: "crash" }, 30, true],
  ]) {
    job = envelope(state, payload, wall);
    const execution = await session.callTool("submit_job", { job });
    const { outcome } = await execution.settle();
    assert.equal(outcome.status, "completed", outcome.error?.stack);
    assert.equal(outcome.result.isError, isError);
    const recorded = outcome.result.structuredContent;
    assert.equal(recorded.job.state, state);
    assert.deepEqual(recorded.result, await tool(client, "get_result", { job_id: recorded.job.job_id }));
  }
});

test("SDK validates existing success and coded-error structured outputs", async (t) => {
  const fixture = await setup(t);
  // The base client here declares no Tasks capability and receives job IDs.
  const client = await fixture.connect();
  const { tools } = await client.listTools();
  const schema = (name) => tools.find((t) => t.name === name).outputSchema;
  assert.equal(schema("put_input").type, "object");
  assert.deepEqual(schema("get_job"), schema("wait_job"));

  const content = "model input µ";
  const input = await tool(client, "put_input", { content });
  assert.equal(input.file, sha256(content));
  assert.equal(input.bytes, Buffer.byteLength(content));
  const { job_id } = await tool(client, "submit_job", { job: envelope("schema", { mode: "complete" }) });
  assert.equal((await tool(client, "get_job", { job_id })).job_id, job_id);
  assert.equal((await tool(client, "wait_job", { job_id })).state, "completed");
  const badInput = await client.callTool({ name: "put_input", arguments: {} });
  assert.equal(badInput.isError, true);
  assert.equal(badInput.structuredContent.error.code, "invalid_arguments");
  const missingJob = await client.callTool({ name: "get_job", arguments: { job_id: "f".repeat(32) } });
  assert.equal(missingJob.isError, true);
  assert.equal(typeof missingJob.structuredContent.error.code, "string");
});

test("official Skills client discovers the workflows and verifies each file on demand", async (t) => {
  const fixture = await setup(t);
  const client = await fixture.connect();
  const catalog = new SkillsClient(client);
  assert.equal(catalog.supported, true);
  assert.equal(catalog.directoryRead, false);
  const listing = await catalog.list();
  assert.deepEqual(listing.skills.map((entry) => entry.frontmatter.name), skills);
  const entry = listing.skills[0];
  const { skill } = await catalog.get(skillsBase + skills[0] + "/SKILL.md");
  assert.deepEqual(skill, entry);
  const main = await catalog.read(skill);
  const reference = await catalog.read(skill, "references/problem-card.md");
  assert.match(main.text, /describe_worker/);
  assert.match(reference.text, /Write a short problem card/);
  for (const file of [main, reference]) {
    const resource = skill.resources.find((entry) => entry.uri === file.uri);
    assert.equal(file.bytes.byteLength, resource.size);
    assert.equal("sha256:" + sha256(file.bytes), resource.digest);
    const modified = Buffer.from(file.bytes);
    modified[modified.length - 1] ^= 1;
    assert.notEqual("sha256:" + sha256(modified), resource.digest);
  }
});

test("Inspector CLI independently verifies the whole Skills catalog", async (t) => {
  const fixture = await setup(t);
  const inspector = resolve(here, "node_modules/.bin/mcp-inspector");
  const result = execFileSync(inspector, [
    "--cli", fixture.command, ...fixture.args, "--protocol-era", "modern",
    "--method", "skills/list", "--verify", "--require-digests",
  ], { encoding: "utf8", timeout: 30_000 });
  for (const name of skills) {
    assert.match(result, new RegExp(name));
  }
  t.diagnostic("MCP Inspector 2.17.0 verified all listed skill files over modern stdio");
});

test("pinned Apps SDK parses view metadata and the resource is served over modern stdio", async (t) => {
  const fixture = await setup(t);
  const client = await fixture.connect({
    extensions: { "io.modelcontextprotocol/ui": { mimeTypes: [RESOURCE_MIME_TYPE] } },
  });
  const { tools } = await client.listTools();
  const view = tools.find((entry) => entry.name === "view_result");
  const pager = tools.find((entry) => entry.name === "view_result_page");
  const { resourceUri } = McpUiToolMetaSchema.parse(view._meta.ui);
  assert.deepEqual(McpUiToolMetaSchema.parse(pager._meta.ui).visibility, ["app"]);
  const { contents: [resource] } = await client.readResource({ uri: resourceUri });
  assert.equal(resource.mimeType, RESOURCE_MIME_TYPE);
  assert.match(resource.text, /ui\/notifications\/tool-result/);
});
