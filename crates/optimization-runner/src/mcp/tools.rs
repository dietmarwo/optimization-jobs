//! The tools of `optimization-mcp` and the `optimization-run` calls behind
//! them.
use super::{Ctx, Launch, Server, tasks};
use optimization_job_api::{Input, checked_input, process::bounded_command_until, storage::digest};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    io::ErrorKind,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant, SystemTime},
};

/// Job states after which nothing changes.
pub const TERMINAL: [&str; 5] = [
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
];
/// Deadlines of runner calls: reads, and calls that run worker validation.
const QUICK: Duration = Duration::from_secs(30);
const SLOW: Duration = Duration::from_secs(120);
/// Output cap of one runner call.
const OUTPUT_CAP: usize = 64 * 1024 * 1024;
/// Tasks listed by a result summary, and the size of `full` results.
const SUMMARY_TASKS: usize = 100;
const FULL_CAP: usize = 1024 * 1024;
const MAX_WAIT_SECONDS: f64 = 600.0;

pub struct ToolError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

impl ToolError {
    pub fn value(&self) -> Value {
        json!({"error":{"code":self.code,"message":self.message,"retryable":self.retryable}})
    }
}

pub enum Fail {
    Tool(ToolError),
    /// The request was cancelled or the server is shutting down.
    Cancelled,
}

pub enum Outcome {
    Done(Value),
    Failed(ToolError),
    /// A `CreateTaskResult` (Tasks extension).
    Task(Value),
    Cancelled,
}

fn fail(code: &str, message: impl Into<String>) -> Fail {
    Fail::Tool(ToolError {
        code: code.into(),
        message: message.into(),
        retryable: false,
    })
}

/// A `CallToolResult`: the value as structured content and, for clients that
/// read only text, as its JSON.
pub fn tool_result(value: Value, is_error: bool) -> Value {
    json!({
        "content": [{"type":"text","text":value.to_string()}],
        "structuredContent": value,
        "isError": is_error,
    })
}

pub fn terminal(state: &Value) -> bool {
    state.as_str().is_some_and(|s| TERMINAL.contains(&s))
}

/// Sleeps up to `duration`, returning early once the request is stopped.
pub fn pause(server: &Server, ctx: &Ctx, duration: Duration) {
    let start = Instant::now();
    while start.elapsed() < duration && !ctx.stopped(server) {
        thread::sleep(Duration::from_millis(50).min(duration));
    }
}

fn random_hex() -> String {
    use std::io::Read;
    let mut bytes = [0u8; 16];
    if fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .is_err()
    {
        // Unpredictable enough for file names; task IDs need urandom.
        let nanos = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or_default();
        return digest(format!("{nanos}-{}", std::process::id()).as_bytes())[..32].to_owned();
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub fn task_token() -> std::io::Result<String> {
    use std::io::Read;
    let mut bytes = [0u8; 16];
    fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn object(properties: Value, required: &[&str]) -> Value {
    json!({"type":"object","properties":properties,"required":required,"additionalProperties":false})
}

fn job_id_property() -> Value {
    json!({"type":"string","pattern":"^[0-9a-f]{32}$","description":"Job ID, as returned by submit_job or list_jobs."})
}

/// The job envelope schema, embedded in the tools that take a job.
fn envelope_schema() -> Value {
    let mut schema: Value = serde_json::from_str(include_str!(
        "../../../../docs/job-api/schemas/optimization.job-0.1.schema.json"
    ))
    .expect("the job schema is valid JSON");
    let object = schema.as_object_mut().expect("the job schema is an object");
    object.remove("$schema");
    object.remove("$id");
    object.insert(
        "description".into(),
        json!("An optimization.job/0.1 envelope (fcmaes.job/0.1 legacy specifications are accepted too). The payload follows the worker profile named by payload_schema; describe_worker lists them."),
    );
    schema
}

fn job_properties() -> Value {
    json!({
        "job": envelope_schema(),
        "spec_path": {"type":"string","description":"Path of a job file on this machine, instead of job. Its relative input files are read from the file's directory."},
        "input_dir": {"type":"string","description":"Directory the relative input files of job are read from; by default the server's input directory. Each file must match its SHA-256."},
    })
}

/// Tool name, title, annotations, description and input schema.
pub fn definitions() -> Vec<Value> {
    let read = json!({"readOnlyHint":true,"openWorldHint":false});
    let job_id = job_id_property();
    let tools = [
        (
            "describe_node",
            "Describe the node",
            read.clone(),
            "The node's CPU capacity (slots), how jobs are launched, and its registered workers with their profiles and builds. Start here.",
            object(json!({}), &[]),
        ),
        (
            "describe_worker",
            "Describe a worker",
            read.clone(),
            "Everything a registered worker declares: its profiles (payload_schema values), problems, optimizers or backends and their options, claims, cancellation and resource rules. Read it before writing a payload.",
            object(
                json!({"worker":{"type":"string","description":"ID of a registered worker, from describe_node."}}),
                &["worker"],
            ),
        ),
        (
            "validate_job",
            "Validate a job",
            read.clone(),
            "Checks a job without starting it: the envelope, the input files and the worker's own validation of the payload. Returns the resolved job with its task_count, or an invalid_job error explaining the problem. Pass exactly one of job or spec_path.",
            object(job_properties(), &[]),
        ),
        (
            "submit_job",
            "Submit a job",
            json!({"readOnlyHint":false,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false}),
            "Starts a job and returns its handle (job_id, state, directory) once the job exists durably. Submission is idempotent: the same request_key with the same content returns the existing job; other content under a used key fails with request_key_conflict. A job that needs more CPU slots than are free waits; one that needs more than the node has fails with capacity_exceeded. The job runs detached from this server and survives its restart. Clients with the MCP Tasks extension get a task that completes with the job's result. Pass exactly one of job or spec_path.",
            object(job_properties(), &[]),
        ),
        (
            "get_job",
            "Get a job's state",
            read.clone(),
            "The job's state (submitted, starting, waiting, running, completed, failed, cancelled, timed_out or interrupted), its progress (completed and requested tasks, known work) and its directory. observed_state reports a launcher lost or an attempt interrupted by a reboot; repair_job finalizes those.",
            object(json!({"job_id":job_id}), &["job_id"]),
        ),
        (
            "wait_job",
            "Wait for a job",
            read.clone(),
            "Waits until the job ends, is observed interrupted, or timeout_seconds pass, and returns get_job's answer. Call again to keep waiting. Reports progress (completed tasks) when the client asks for it.",
            object(
                json!({"job_id":job_id,"timeout_seconds":{"type":"number","exclusiveMinimum":0,"maximum":MAX_WAIT_SECONDS,"default":30,"description":"At most 600."}}),
                &["job_id"],
            ),
        ),
        (
            "get_result",
            "Get a job's result",
            read.clone(),
            "The result of an ended job. By default a summary: status, accounting, counts of claims and terminations, and per task its claim, termination, feasibility, objective and evidence (the first 100 tasks; no points). tasks returns the complete records (points, details) of the given task IDs; full returns the whole result manifest if it is under 1 MiB. A job that has not ended returns not_finished.",
            object(
                json!({
                    "job_id": job_id,
                    "tasks": {"type":"array","items":{"type":"integer","minimum":0},"maxItems":100,"description":"Task IDs whose complete records to return."},
                    "full": {"type":"boolean","default":false,"description":"Return the whole result manifest."},
                }),
                &["job_id"],
            ),
        ),
        (
            "get_events",
            "Get a job's events",
            read.clone(),
            "The job's lifecycle journal (admission, start, cancellation, deadline, finish), newest last.",
            object(
                json!({"job_id":job_id,"limit":{"type":"integer","minimum":1,"maximum":1000,"default":50,"description":"Return the last limit events."}}),
                &["job_id"],
            ),
        ),
        (
            "get_artifact",
            "Read a job artifact",
            read.clone(),
            "The content of an artifact named in the job's result manifest (artifacts), up to 1 MiB.",
            object(
                json!({"job_id":job_id,"name":{"type":"string","description":"Artifact name from the result's artifacts."}}),
                &["job_id", "name"],
            ),
        ),
        (
            "list_jobs",
            "List jobs",
            read,
            "The jobs on this node, newest first: ID, state, progress and timestamps.",
            object(
                json!({
                    "active_only": {"type":"boolean","default":false,"description":"Only jobs that have not ended."},
                    "limit": {"type":"integer","minimum":1,"maximum":1000,"default":50},
                }),
                &[],
            ),
        ),
        (
            "cancel_job",
            "Cancel a job",
            json!({"readOnlyHint":false,"destructiveHint":true,"idempotentHint":true,"openWorldHint":false}),
            "Stops a job gracefully: running tasks finish their current unit of work (a retry, a generation, a solve) and every completed task stays in the result; the job ends cancelled. A job that has already ended returns already_terminal.",
            object(json!({"job_id":job_id}), &["job_id"]),
        ),
        (
            "kill_job",
            "Kill a job",
            json!({"readOnlyHint":false,"destructiveHint":true,"idempotentHint":true,"openWorldHint":false}),
            "Stops a job immediately: the worker is killed after one second and the work in progress is lost; committed task results stay. Prefer cancel_job.",
            object(json!({"job_id":job_id}), &["job_id"]),
        ),
        (
            "repair_job",
            "Repair an interrupted job",
            json!({"readOnlyHint":false,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false}),
            "Finalizes a job whose launcher was lost or that a reboot interrupted (get_job shows observed_state), keeping every committed task result and the exact accounting where it is known. Refuses (attempt_active, liveness_unknown) while a process may still own the job.",
            object(json!({"job_id":job_id}), &["job_id"]),
        ),
    ];
    tools
        .into_iter()
        .map(|(name, title, annotations, description, schema)| {
            let mut annotations = annotations;
            annotations["title"] = json!(title);
            json!({"name":name,"title":title,"description":description,"inputSchema":schema,"annotations":annotations})
        })
        .collect()
}

pub fn exists(name: &str) -> bool {
    definitions().iter().any(|t| t["name"] == name)
}

pub fn call(server: &Server, name: &str, args: &Value, ctx: &Ctx) -> Outcome {
    let result = match name {
        "describe_node" => describe_node(server, ctx),
        "describe_worker" => string(args, "worker")
            .and_then(|worker| server.cli(&["problems", "describe", &worker], QUICK, ctx)),
        "validate_job" => stage(server, args)
            .and_then(|staged| server.cli(&["validate", "--spec", &path(&staged.spec)], SLOW, ctx)),
        "submit_job" => return submit_job(server, args, ctx),
        "get_job" => job_id(args).and_then(|id| server.get(&id, ctx)),
        "wait_job" => wait_job(server, args, ctx),
        "get_result" => get_result(server, args, ctx),
        "get_events" => get_events(server, args, ctx),
        "get_artifact" => job_id(args).and_then(|id| {
            let name = string(args, "name")?;
            server.cli(&["jobs", "artifact", &id, &name], QUICK, ctx)
        }),
        "list_jobs" => list_jobs(server, args, ctx),
        "cancel_job" => job_id(args).and_then(|id| cancel(server, &id, false, ctx)),
        "kill_job" => job_id(args).and_then(|id| cancel(server, &id, true, ctx)),
        "repair_job" => job_id(args).and_then(|id| server.cli(&["jobs", "repair", &id], SLOW, ctx)),
        _ => Err(fail("invalid_arguments", format!("unknown tool {name}"))),
    };
    match result {
        Ok(value) => Outcome::Done(value),
        Err(Fail::Tool(error)) => Outcome::Failed(error),
        Err(Fail::Cancelled) => Outcome::Cancelled,
    }
}

fn path(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

fn string(args: &Value, key: &str) -> Result<String, Fail> {
    args[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| {
            fail(
                "invalid_arguments",
                format!("{key} must be a non-empty string"),
            )
        })
}

fn job_id(args: &Value) -> Result<String, Fail> {
    let id = string(args, "job_id")?;
    if id.len() != 32 || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(fail(
            "invalid_arguments",
            format!("job_id {id:?} is not a 32-digit hexadecimal job ID"),
        ));
    }
    Ok(id)
}

fn limit(args: &Value, default: usize) -> Result<usize, Fail> {
    match &args["limit"] {
        Value::Null => Ok(default),
        v => v
            .as_u64()
            .filter(|n| (1..=1000).contains(n))
            .map(|n| n as usize)
            .ok_or_else(|| {
                fail(
                    "invalid_arguments",
                    "limit must be an integer from 1 to 1000",
                )
            }),
    }
}

/// Reads the runner's coded error, the last JSON line of its stderr.
fn runner_error(stderr: &[u8]) -> ToolError {
    let text = String::from_utf8_lossy(stderr);
    for line in text.lines().rev() {
        if let Ok(v) = serde_json::from_str::<Value>(line)
            && let Some(code) = v["error"]["code"].as_str()
        {
            return ToolError {
                code: code.into(),
                message: v["error"]["message"].as_str().unwrap_or_default().into(),
                retryable: v["error"]["retryable"].as_bool().unwrap_or(false),
            };
        }
    }
    ToolError {
        code: "runner_error".into(),
        message: format!("optimization-run failed: {}", text.trim()),
        retryable: false,
    }
}

impl Server {
    /// Runs `optimization-run --root ROOT ARGS` and returns its JSON output,
    /// or its coded error.
    pub fn cli(&self, args: &[&str], timeout: Duration, ctx: &Ctx) -> Result<Value, Fail> {
        let mut argv = vec![path(&self.runner), "--root".into(), path(&self.root)];
        argv.extend(args.iter().map(|a| a.to_string()));
        let abort = || ctx.stopped(self);
        match bounded_command_until(&argv, vec![], timeout, OUTPUT_CAP, &abort) {
            Ok((status, out, _)) if status.success() => serde_json::from_slice(&out)
                .map_err(|e| fail("runner_error", format!("unreadable runner output: {e}"))),
            Ok((_, _, err)) => Err(Fail::Tool(runner_error(&err))),
            Err(e) if e.kind() == ErrorKind::Interrupted => Err(Fail::Cancelled),
            Err(e) if e.kind() == ErrorKind::TimedOut => Err(Fail::Tool(ToolError {
                code: "mcp_timeout".into(),
                message: format!(
                    "optimization-run {} did not answer within {} s",
                    args.first().copied().unwrap_or_default(),
                    timeout.as_secs()
                ),
                retryable: true,
            })),
            Err(e) => Err(fail(
                "runner_error",
                format!("cannot run {}: {e}", self.runner.display()),
            )),
        }
    }

    /// `jobs get`, with the job ID also under `job_id`.
    pub fn get(&self, id: &str, ctx: &Ctx) -> Result<Value, Fail> {
        let mut job = self.cli(&["jobs", "get", id], QUICK, ctx)?;
        job["job_id"] = json!(id);
        Ok(job)
    }
}

fn describe_node(server: &Server, ctx: &Ctx) -> Result<Value, Fail> {
    let doctor = server.cli(&["node", "doctor"], QUICK, ctx)?;
    let registry = server.cli(&["workers", "list"], QUICK, ctx)?;
    let workers: Vec<Value> = registry
        .as_object()
        .map(|workers| {
            workers
                .iter()
                .map(|(id, w)| {
                    let d = &w["description"];
                    json!({"worker":id,"protocol":d["protocol"],"profiles":d["profiles"],"engine":d["engine"],"build":d["build"]})
                })
                .collect()
        })
        .unwrap_or_default();
    let mut node = json!({
        "root": path(&server.root),
        "capacity": doctor["capacity"],
        "launch": server.launch.name(),
        "systemd_user_manager": doctor["systemd_user_manager"],
        "workers": workers,
    });
    if doctor["capacity"].is_null() {
        node["note"] = json!(format!(
            "the node is not initialized; its owner runs: optimization-run --root {} node init --capacity N",
            server.root.display()
        ));
    } else if node["workers"].as_array().is_some_and(Vec::is_empty) {
        node["note"] = json!(format!(
            "no worker is registered; its owner runs: optimization-run --root {} workers add --id ID --executable PATH",
            server.root.display()
        ));
    }
    Ok(node)
}

/// A job ready for `--spec`: the file, its content and, for inline jobs, the
/// staging directory holding it and its input files (removed on drop).
struct Staged {
    spec: PathBuf,
    job: Value,
    request_key: String,
    _dir: Option<tempfile::TempDir>,
}

fn staging(root: &Path) -> PathBuf {
    root.join("mcp").join("staging")
}

/// Removes staging directories that a killed server left behind.
pub fn clean_staging(root: &Path) {
    let Ok(entries) = fs::read_dir(staging(root)) else {
        return;
    };
    for entry in entries.flatten() {
        let old = entry
            .metadata()
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.elapsed().ok())
            .is_some_and(|age| age > Duration::from_secs(86_400));
        if old {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
}

fn stage(server: &Server, args: &Value) -> Result<Staged, Fail> {
    let staged = match (&args["job"], &args["spec_path"]) {
        (Value::Object(_), Value::Null) => stage_inline(server, args)?,
        (Value::Null, Value::String(file)) => {
            let spec = fs::canonicalize(file)
                .map_err(|e| fail("invalid_arguments", format!("spec_path {file}: {e}")))?;
            let bytes = fs::read(&spec)
                .map_err(|e| fail("invalid_arguments", format!("spec_path {file}: {e}")))?;
            let job: Value = serde_json::from_slice(&bytes)
                .map_err(|e| fail("invalid_job", format!("spec_path {file}: {e}")))?;
            Staged {
                request_key: String::new(),
                spec,
                job,
                _dir: None,
            }
        }
        _ => {
            return Err(fail(
                "invalid_arguments",
                "pass exactly one of job (an object) or spec_path (a string)",
            ));
        }
    };
    let request_key = staged.job["request_key"]
        .as_str()
        .filter(|k| !k.is_empty())
        .ok_or_else(|| {
            fail(
                "invalid_job",
                "the job needs a non-empty string request_key",
            )
        })?
        .to_owned();
    Ok(Staged {
        request_key,
        ..staged
    })
}

/// Writes an inline job to a staging directory with copies of its input
/// files, each checked against its SHA-256 first.
fn stage_inline(server: &Server, args: &Value) -> Result<Staged, Fail> {
    let job = args["job"].clone();
    let base = match &args["input_dir"] {
        Value::Null => server.input_dir.clone(),
        Value::String(dir) => fs::canonicalize(dir)
            .map_err(|e| fail("invalid_arguments", format!("input_dir {dir}: {e}")))?,
        _ => return Err(fail("invalid_arguments", "input_dir must be a string")),
    };
    let parent = staging(&server.root);
    fs::create_dir_all(&parent)
        .map_err(|e| fail("runner_error", format!("{}: {e}", parent.display())))?;
    let dir = tempfile::Builder::new()
        .prefix("job-")
        .tempdir_in(&parent)
        .map_err(|e| fail("runner_error", format!("{}: {e}", parent.display())))?;
    if let Some(inputs) = job["inputs"].as_array() {
        for value in inputs {
            // Malformed declarations are left to the runner's own message.
            let Ok(input) = serde_json::from_value::<Input>(value.clone()) else {
                continue;
            };
            let relative = Path::new(&input.file);
            if relative
                .components()
                .any(|c| !matches!(c, Component::Normal(_) | Component::CurDir))
            {
                continue;
            }
            let bytes = checked_input(&base, &input).map_err(|e| {
                fail(
                    "invalid_job",
                    format!(
                        "input {} ({}): {e}",
                        input.name,
                        base.join(relative).display()
                    ),
                )
            })?;
            let target = dir.path().join(relative);
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent)
                    .map_err(|e| fail("runner_error", format!("{}: {e}", parent.display())))?;
            }
            fs::write(&target, bytes)
                .map_err(|e| fail("runner_error", format!("{}: {e}", target.display())))?;
        }
    }
    let spec = dir.path().join("job.json");
    fs::write(&spec, job.to_string())
        .map_err(|e| fail("runner_error", format!("{}: {e}", spec.display())))?;
    Ok(Staged {
        spec,
        job,
        request_key: String::new(),
        _dir: Some(dir),
    })
}

fn submit_job(server: &Server, args: &Value, ctx: &Ctx) -> Outcome {
    let submitted = stage(server, args).and_then(|staged| match server.launch {
        Launch::Systemd => {
            let job = server.cli(&["submit", "--spec", &path(&staged.spec)], SLOW, ctx)?;
            let id = job["id"].as_str().unwrap_or_default().to_owned();
            server.get(&id, ctx)
        }
        Launch::Process => launch_process(server, &staged, ctx),
    });
    let job = match submitted {
        Ok(job) => job,
        Err(Fail::Tool(error)) => return Outcome::Failed(error),
        Err(Fail::Cancelled) => return Outcome::Cancelled,
    };
    if !ctx.tasks {
        return Outcome::Done(job);
    }
    let job_id = job["job_id"].as_str().unwrap_or_default();
    match tasks::create(server, job_id, &job, ctx) {
        Ok(task) => Outcome::Task(task),
        // The job exists; without a task the client still gets its handle.
        Err(_) => Outcome::Done(job),
    }
}

/// Starts `optimization-run run` in a session of its own, so the job
/// outlives this server, and returns once the job exists: when `jobs get`
/// finds it with this submission's content, or when the launcher has exited.
fn launch_process(server: &Server, staged: &Staged, ctx: &Ctx) -> Result<Value, Fail> {
    let id = digest(staged.request_key.as_bytes())[..32].to_owned();
    let logs = server.root.join("mcp").join("launch");
    fs::create_dir_all(&logs)
        .map_err(|e| fail("runner_error", format!("{}: {e}", logs.display())))?;
    let log = logs.join(format!("{id}-{}.log", &random_hex()[..8]));
    let stderr = fs::File::create(&log)
        .map_err(|e| fail("runner_error", format!("{}: {e}", log.display())))?;
    let mut command = Command::new(&server.runner);
    command
        .arg("--root")
        .arg(&server.root)
        .arg("run")
        .arg("--spec")
        .arg(&staged.spec)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(stderr);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // SAFETY: setsid is async-signal-safe and touches no memory of the
        // parent process.
        unsafe {
            command.pre_exec(|| {
                libc::setsid();
                Ok(())
            });
        }
    }
    let mut child = command.spawn().map_err(|e| {
        fail(
            "runner_error",
            format!("cannot start {}: {e}", server.runner.display()),
        )
    })?;
    // The launcher must be reaped whatever this request does next; a log of
    // a launcher that failed after creating its job stays for diagnosis.
    let reap = move |mut child: std::process::Child, log: PathBuf| {
        thread::spawn(move || {
            if child.wait().is_ok_and(|s| s.success()) {
                let _ = fs::remove_file(log);
            }
        });
    };
    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let text = fs::read(&log).unwrap_or_default();
                let _ = fs::remove_file(&log);
                if !status.success() {
                    return Err(Fail::Tool(runner_error(&text)));
                }
                // An existing identical job, or one that already finished.
                return server.get(&id, ctx);
            }
            Ok(None) => {}
            Err(e) => return Err(fail("runner_error", format!("launcher: {e}"))),
        }
        if let Ok(job) = server.get(&id, ctx)
            && job["directory"]
                .as_str()
                .and_then(|dir| fs::read(Path::new(dir).join("submitted.json")).ok())
                .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                .is_some_and(|submitted| submitted == staged.job)
        {
            reap(child, log);
            return Ok(job);
        }
        if ctx.stopped(server) {
            reap(child, log);
            return Err(Fail::Cancelled);
        }
        if start.elapsed() > SLOW {
            reap(child, log);
            return Err(Fail::Tool(ToolError {
                code: "mcp_timeout".into(),
                message: format!(
                    "the job was not confirmed within {} s; its launcher keeps running, so check get_job {id} before submitting again",
                    SLOW.as_secs()
                ),
                retryable: true,
            }));
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn wait_job(server: &Server, args: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let id = job_id(args)?;
    let timeout = match &args["timeout_seconds"] {
        Value::Null => 30.0,
        v => v
            .as_f64()
            .filter(|t| t.is_finite() && *t > 0.0 && *t <= MAX_WAIT_SECONDS)
            .ok_or_else(|| {
                fail(
                    "invalid_arguments",
                    format!("timeout_seconds must be in (0, {MAX_WAIT_SECONDS}]"),
                )
            })?,
    };
    let start = Instant::now();
    let mut reported: Option<u64> = None;
    loop {
        let job = server.get(&id, ctx)?;
        if let Some(done) = job["completed_tasks"].as_u64()
            && reported.is_none_or(|r| done > r)
        {
            let state = job["state"].as_str().unwrap_or_default();
            server.progress(ctx, done, job["requested_tasks"].as_u64(), state);
            reported = Some(done);
        }
        if terminal(&job["state"])
            || !job["observed_state"].is_null()
            || start.elapsed().as_secs_f64() >= timeout
        {
            return Ok(job);
        }
        pause(server, ctx, Duration::from_millis(500));
        if ctx.stopped(server) {
            return Err(Fail::Cancelled);
        }
    }
}

/// The result manifest of an ended job.
pub fn manifest(server: &Server, job: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let id = job["job_id"].as_str().unwrap_or_default();
    if !terminal(&job["state"]) {
        let mut message = format!(
            "job {id} is {}; wait_job until it ends",
            job["state"].as_str().unwrap_or("unknown")
        );
        if let Some(observed) = job["observed_state"].as_str() {
            message = format!("job {id} was observed {observed}; repair_job finalizes it");
        }
        return Err(fail("not_finished", message));
    }
    let dir = job["directory"].as_str().unwrap_or_default();
    server.cli(&["result", dir], QUICK, ctx)
}

/// The compact view of a result: accounting and one line per task, without
/// points or details.
pub fn summary(job: &Value, manifest: &Value) -> Value {
    let results = manifest["results"].as_array().cloned().unwrap_or_default();
    let mut claims = BTreeMap::<String, u64>::new();
    let mut terminations = BTreeMap::<String, u64>::new();
    for r in &results {
        let o = &r["outcome"];
        *claims
            .entry(o["claim"].as_str().unwrap_or("unknown").into())
            .or_default() += 1;
        *terminations
            .entry(o["termination"].as_str().unwrap_or("unknown").into())
            .or_default() += 1;
    }
    let tasks: Vec<Value> = results
        .iter()
        .take(SUMMARY_TASKS)
        .map(|r| {
            let o = &r["outcome"];
            let mut task = json!({
                "task_id": r["task_id"],
                "claim": o["claim"],
                "termination": o["termination"],
                "feasible": o["feasible"],
                "objective": o["objective"],
                "evidence": o["evidence"]["level"],
            });
            for key in ["objective_bounds", "imprecise"] {
                if !o[key].is_null() {
                    task[key] = o[key].clone();
                }
            }
            if !o["evidence"]["refuted"].is_null() {
                task["refuted"] = o["evidence"]["refuted"].clone();
            }
            task
        })
        .collect();
    json!({
        "job_id": job["job_id"],
        "state": job["state"],
        "status": manifest["status"],
        "schema_version": manifest["schema_version"],
        "worker": manifest["worker"],
        "payload_schema": manifest["payload_schema"],
        "completed_tasks": manifest["completed_tasks"],
        "requested_tasks": manifest["requested_tasks"],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "work": manifest["work"],
        "accounting_complete": manifest["runner"]["accounting_complete"],
        "claims": claims,
        "terminations": terminations,
        "tasks": tasks,
        "tasks_omitted": results.len().saturating_sub(SUMMARY_TASKS),
        "artifacts": manifest["artifacts"],
        "directory": job["directory"],
    })
}

fn get_result(server: &Server, args: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let id = job_id(args)?;
    let job = server.get(&id, ctx)?;
    let manifest = manifest(server, &job, ctx)?;
    if args["full"].as_bool() == Some(true) {
        let size = manifest.to_string().len();
        if size > FULL_CAP {
            return Err(fail(
                "result_too_large",
                format!(
                    "the result manifest has {size} bytes, over the 1 MiB inline cap; read {}/run.json, or pass tasks",
                    job["directory"].as_str().unwrap_or_default()
                ),
            ));
        }
        return Ok(manifest);
    }
    match &args["tasks"] {
        Value::Null => Ok(summary(&job, &manifest)),
        Value::Array(ids) => {
            let wanted: Vec<u64> = ids.iter().filter_map(Value::as_u64).collect();
            if wanted.len() != ids.len() || wanted.len() > 100 {
                return Err(fail(
                    "invalid_arguments",
                    "tasks must be at most 100 non-negative integer task IDs",
                ));
            }
            let records: Vec<Value> = manifest["results"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|r| r["task_id"].as_u64().is_some_and(|t| wanted.contains(&t)))
                .cloned()
                .collect();
            Ok(json!({"job_id":id,"state":job["state"],"tasks":records}))
        }
        _ => Err(fail("invalid_arguments", "tasks must be an array")),
    }
}

fn get_events(server: &Server, args: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let id = job_id(args)?;
    let limit = limit(args, 50)?;
    let events = server.cli(&["jobs", "events", &id], QUICK, ctx)?;
    let events = events.as_array().cloned().unwrap_or_default();
    let skip = events.len().saturating_sub(limit);
    Ok(json!({"job_id":id,"total":events.len(),"events":events[skip..]}))
}

fn list_jobs(server: &Server, args: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let limit = limit(args, 50)?;
    let active_only = args["active_only"].as_bool() == Some(true);
    let jobs = server.cli(&["jobs", "list"], SLOW, ctx)?;
    let mut jobs: Vec<Value> = jobs
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|j| !active_only || !terminal(&j["state"]))
        .map(|j| {
            let mut job = json!({"job_id":j["id"],"state":j["state"]});
            for key in [
                "observed_state",
                "error",
                "completed_tasks",
                "requested_tasks",
                "submitted_at",
                "finished_at",
                "cancel_requested",
            ] {
                if !j[key].is_null() {
                    job[key] = j[key].clone();
                }
            }
            job
        })
        .collect();
    jobs.sort_by(|a, b| {
        let t = |j: &Value| j["submitted_at"].as_f64().unwrap_or(0.0);
        t(b).total_cmp(&t(a))
    });
    let total = jobs.len();
    jobs.truncate(limit);
    Ok(json!({"total":total,"jobs":jobs}))
}

pub fn cancel(server: &Server, id: &str, now: bool, ctx: &Ctx) -> Result<Value, Fail> {
    let mut args = vec!["jobs", "cancel", id];
    if now {
        args.push("--now");
    }
    let mut job = server.cli(&args, QUICK, ctx)?;
    job["job_id"] = json!(id);
    Ok(job)
}
