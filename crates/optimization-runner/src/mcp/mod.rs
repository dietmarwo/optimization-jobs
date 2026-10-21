//! `optimization-mcp`: a Model Context Protocol server over one node root.
//!
//! The server speaks MCP over stdio, one JSON-RPC message per line. It is
//! dual-era: requests that carry `io.modelcontextprotocol/protocolVersion`
//! in `_meta` are served statelessly under revision 2026-07-28, with the
//! Tasks extension (`io.modelcontextprotocol/tasks`); an `initialize`
//! request selects a legacy revision (2025-11-25 and earlier) for the
//! process. Every tool drives the `optimization-run` command line, the
//! runner's documented interface, so the runner's validation, idempotency,
//! admission and recovery rules apply unchanged. The server registers no
//! workers and initializes no node: that stays with the person who owns the
//! node.
//!
//! See `docs/job-api.md#agents-and-mcp` for the tools and their mapping onto
//! the runner.
mod inputs;
mod tasks;
mod tools;

use clap::{Parser, ValueEnum};
use serde_json::{Map, Value, json};
use std::{
    collections::HashMap,
    io::{self, BufRead, Read, Write},
    path::PathBuf,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread,
    time::Duration,
};

/// Protocol revisions served statelessly, with per-request `_meta`.
const MODERN: [&str; 1] = ["2026-07-28"];
/// Protocol revisions served after an `initialize` handshake, newest first.
const LEGACY: [&str; 4] = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const PROTOCOL_VERSION: &str = "io.modelcontextprotocol/protocolVersion";
const CLIENT_CAPABILITIES: &str = "io.modelcontextprotocol/clientCapabilities";
const SERVER_INFO: &str = "io.modelcontextprotocol/serverInfo";
const SUBSCRIPTION: &str = "io.modelcontextprotocol/subscriptionId";
/// The Tasks extension (SEP-2663).
const TASKS: &str = "io.modelcontextprotocol/tasks";
/// MCP error codes of revision 2026-07-28.
const MISSING_CAPABILITY: i64 = -32021;
const UNSUPPORTED_VERSION: i64 = -32022;
const INVALID_PARAMS: i64 = -32602;
const METHOD_NOT_FOUND: i64 = -32601;
const INVALID_REQUEST: i64 = -32600;
const PARSE_ERROR: i64 = -32700;
const INTERNAL_ERROR: i64 = -32603;
/// The server is at one of its limits below; the request may be retried.
const SERVER_BUSY: i64 = -32000;
/// Largest message, in bytes: the input files of a job are files, not part
/// of it. A longer line is skipped unread and answered with an error.
const MAX_MESSAGE: usize = 64 * 1024 * 1024;
/// Requests answered at the same time (each runs on a thread of its own).
const MAX_REQUESTS: usize = 64;
/// Of these, requests that wait (`wait_job`, `subscriptions/listen`): the
/// rest stays free for status, cancellation and other short calls.
const MAX_WAITING: usize = 32;
/// Calls that run worker validation (`validate_job`, `submit_job`) at the
/// same time; further ones queue. Validation runs before CPU-slot admission.
const MAX_VALIDATIONS: usize = 4;
/// How long clients may cache `tools/list` and `server/discover`.
const CACHE_MS: u64 = 3_600_000;

const INSTRUCTIONS: &str = "Runs durable optimization jobs on this node with its registered native \
workers (fcmaes, LP-IP, SQP and application workers). Start with describe_node, then \
describe_worker for the profiles and options of a worker. Write an optimization.job/0.1 \
envelope, check it with validate_job and start it with submit_job. The request_key makes \
submission idempotent: the same key with the same content returns the existing job, other \
content under that key is rejected, so choose a new key for a new job. Jobs run detached from \
this server and survive its restart. Follow a job with wait_job or get_job and read get_result \
when it has ended. cancel_job stops it gracefully and keeps completed work; kill_job stops it \
at once. Every task result carries a claim (what the worker asserts) and evidence (how much of \
it was independently rechecked); there is no automatic winner across tasks or jobs.";

#[derive(Parser)]
#[command(
    name = "optimization-mcp",
    version,
    about = "MCP server (stdio) for the durable optimization jobs of one optimization-run node (Linux)"
)]
struct Args {
    /// Node root, as for optimization-run.
    #[arg(
        long,
        env = "OPTIMIZATION_RUN_ROOT",
        default_value = ".optimization-jobs"
    )]
    root: PathBuf,
    /// The optimization-run executable; by default the one next to this
    /// server.
    #[arg(long)]
    runner: Option<PathBuf>,
    /// How submit_job starts jobs: `process` runs `optimization-run run` in a
    /// session of its own, which outlives this server; `systemd` uses
    /// `optimization-run submit` (a systemd user manager is required).
    #[arg(long, value_enum, default_value_t = Launch::Process)]
    launch: Launch,
    /// Directory that relative input files of inline jobs are read from, by
    /// default the working directory.
    #[arg(long)]
    input_dir: Option<PathBuf>,
    /// Largest total size of the input store of put_input (NODE/mcp/inputs),
    /// in bytes.
    #[arg(long, default_value_t = inputs::DEFAULT_STORE_BYTES)]
    input_store_bytes: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, ValueEnum)]
pub enum Launch {
    Process,
    Systemd,
}

impl Launch {
    pub fn name(self) -> &'static str {
        match self {
            Launch::Process => "process",
            Launch::Systemd => "systemd",
        }
    }
}

pub struct Server {
    pub root: PathBuf,
    pub runner: PathBuf,
    pub launch: Launch,
    pub input_dir: PathBuf,
    /// Limit of the input store's total size.
    pub input_store_bytes: u64,
    out: Mutex<io::Stdout>,
    inflight: Mutex<HashMap<String, Arc<AtomicBool>>>,
    initialized: AtomicBool,
    /// JSON-RPC batches, part of protocol 2025-03-26 only.
    batches: AtomicBool,
    pub shutdown: AtomicBool,
    /// Requests counted against [`MAX_WAITING`].
    waiting: AtomicUsize,
    /// Running validations and the signal that one ended.
    validations: (Mutex<usize>, Condvar),
}

/// One of the `MAX_VALIDATIONS` validation places, given back on drop.
pub struct Permit<'a>(&'a Server);

impl Drop for Permit<'_> {
    fn drop(&mut self) {
        let (count, ended) = &self.0.validations;
        *count.lock().unwrap_or_else(|e| e.into_inner()) -= 1;
        ended.notify_one();
    }
}

/// One request: its era and whether it may be cancelled or report progress.
pub struct Ctx {
    pub modern: bool,
    /// The client declared the Tasks extension on this request.
    pub tasks: bool,
    pub cancel: Arc<AtomicBool>,
    pub progress: Option<Value>,
    pub id: Value,
}

pub enum Reply {
    Ok(Value),
    Err(i64, String, Option<Value>),
    /// No response: the request was cancelled, or it ended a subscription
    /// the client cancelled.
    Silent,
}

impl Ctx {
    pub fn stopped(&self, server: &Server) -> bool {
        self.cancel.load(Ordering::Relaxed) || server.shutdown.load(Ordering::Relaxed)
    }
}

fn supported() -> Vec<&'static str> {
    MODERN.iter().chain(LEGACY.iter()).copied().collect()
}

fn server_info() -> Value {
    json!({"name":"optimization-mcp","title":"Optimization jobs","version":env!("CARGO_PKG_VERSION")})
}

fn missing_tasks_capability() -> Reply {
    Reply::Err(
        MISSING_CAPABILITY,
        "Missing required client capability".into(),
        Some(json!({"requiredCapabilities":{"extensions":{TASKS:{}}}})),
    )
}

/// The protocol error of a task whose job cannot be read or cancelled. A job
/// removed from the node makes its task unknown.
fn job_error(job_id: &str, action: &str, e: &tools::ToolError) -> Reply {
    if e.code == "unknown_job" {
        return Reply::Err(
            INVALID_PARAMS,
            format!("Failed to retrieve task: its job {job_id} no longer exists on this node"),
            None,
        );
    }
    Reply::Err(
        INTERNAL_ERROR,
        format!("cannot {action} job {job_id}: {}: {}", e.code, e.message),
        None,
    )
}

impl Server {
    /// Waits for a validation place; a cancelled request stops waiting.
    pub fn validation_permit(&self, ctx: &Ctx) -> Result<Permit<'_>, tools::Fail> {
        let (count, ended) = &self.validations;
        let mut running = count.lock().unwrap_or_else(|e| e.into_inner());
        while *running >= MAX_VALIDATIONS {
            if ctx.stopped(self) {
                return Err(tools::Fail::Cancelled);
            }
            running = ended
                .wait_timeout(running, Duration::from_millis(100))
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
        *running += 1;
        Ok(Permit(self))
    }

    /// Writes one message as one line; a closed stdout ends the server.
    pub fn send(&self, message: &Value) {
        let mut out = self.out.lock().unwrap_or_else(|e| e.into_inner());
        let ok = serde_json::to_writer(&mut *out, message).is_ok()
            && out.write_all(b"\n").is_ok()
            && out.flush().is_ok();
        if !ok {
            std::process::exit(0);
        }
    }

    pub fn notify(&self, method: &str, params: Value) {
        self.send(&json!({"jsonrpc":"2.0","method":method,"params":params}));
    }

    /// Reports `progress` of `total` for a request that asked for progress.
    pub fn progress(&self, ctx: &Ctx, progress: u64, total: Option<u64>, message: &str) {
        if let Some(token) = &ctx.progress {
            let mut params = json!({"progressToken":token,"progress":progress,"message":message});
            if let Some(total) = total {
                params["total"] = json!(total);
            }
            self.notify("notifications/progress", params);
        }
    }

    /// The response to a request, if it gets one.
    fn finish(&self, id: &Value, cancel: &AtomicBool, reply: Reply, modern: bool) -> Option<Value> {
        self.inflight
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&id.to_string());
        // A cancelled request gets no response at all.
        if cancel.load(Ordering::Relaxed) {
            return None;
        }
        Some(match reply {
            Reply::Silent => return None,
            Reply::Ok(mut result) => {
                if modern {
                    let object = result.as_object_mut().expect("results are objects");
                    object
                        .entry("resultType")
                        .or_insert_with(|| json!("complete"));
                    let meta = object.entry("_meta").or_insert_with(|| json!({}));
                    meta[SERVER_INFO] = server_info();
                }
                json!({"jsonrpc":"2.0","id":id,"result":result})
            }
            Reply::Err(code, message, data) => {
                let mut error = json!({"code":code,"message":message});
                if let Some(data) = data {
                    error["data"] = data;
                }
                json!({"jsonrpc":"2.0","id":id,"error":error})
            }
        })
    }

    /// Decides how a request is served: `(modern, tasks)`, or the error that
    /// rejects it.
    fn era(&self, method: &str, params: &Value) -> Result<(bool, bool), Reply> {
        let meta = &params["_meta"];
        if !meta[PROTOCOL_VERSION].is_null() {
            if !meta[PROTOCOL_VERSION]
                .as_str()
                .is_some_and(|v| MODERN.contains(&v))
            {
                return Err(Reply::Err(
                    UNSUPPORTED_VERSION,
                    format!(
                        "Unsupported protocol version: {} is served per request; {} only after initialize, without _meta",
                        MODERN.join(", "),
                        LEGACY.join(", ")
                    ),
                    Some(json!({"supported":supported(),"requested":meta[PROTOCOL_VERSION]})),
                ));
            }
            if !meta[CLIENT_CAPABILITIES].is_object() {
                return Err(Reply::Err(
                    INVALID_PARAMS,
                    format!("_meta lacks {CLIENT_CAPABILITIES}"),
                    None,
                ));
            }
            let tasks = meta[CLIENT_CAPABILITIES]["extensions"][TASKS].is_object();
            return Ok((true, tasks));
        }
        if method == "initialize" || method == "ping" || self.initialized.load(Ordering::Relaxed) {
            return Ok((false, false));
        }
        Err(Reply::Err(
            INVALID_PARAMS,
            format!(
                "request lacks _meta {PROTOCOL_VERSION}: this server serves {} per request, and {} after initialize",
                MODERN.join(", "),
                LEGACY.join(", ")
            ),
            None,
        ))
    }

    /// Serves one request and returns its response, if any. A panic is a
    /// bug, but it still answers the request.
    fn request(
        self: &Arc<Self>,
        id: Value,
        method: String,
        params: Value,
        cancel: Arc<AtomicBool>,
    ) -> Option<Value> {
        let (reply, modern) = match self.era(&method, &params) {
            Err(reply) => (reply, false),
            Ok((modern, tasks)) => {
                let ctx = Ctx {
                    modern,
                    tasks,
                    progress: params["_meta"].get("progressToken").cloned(),
                    cancel: cancel.clone(),
                    id: id.clone(),
                };
                let reply = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    self.dispatch(&method, &params, &ctx)
                }))
                .unwrap_or_else(|_| {
                    Reply::Err(
                        INTERNAL_ERROR,
                        "internal error of optimization-mcp; its stderr has the details".into(),
                        None,
                    )
                });
                (reply, modern)
            }
        };
        self.finish(&id, &cancel, reply, modern)
    }

    fn dispatch(&self, method: &str, params: &Value, ctx: &Ctx) -> Reply {
        match (ctx.modern, method) {
            (true, "server/discover") => Reply::Ok(json!({
                "supportedVersions": supported(),
                "capabilities": {"tools": {}, "extensions": {TASKS: {}}},
                "instructions": INSTRUCTIONS,
                "ttlMs": CACHE_MS,
                "cacheScope": "public",
            })),
            (false, "initialize") => {
                let version = params["protocolVersion"]
                    .as_str()
                    .filter(|v| LEGACY.contains(v))
                    .unwrap_or(LEGACY[0]);
                self.initialized.store(true, Ordering::Relaxed);
                self.batches
                    .store(version == "2025-03-26", Ordering::Relaxed);
                Reply::Ok(json!({
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": false}},
                    "serverInfo": server_info(),
                    "instructions": INSTRUCTIONS,
                }))
            }
            (false, "ping") => Reply::Ok(json!({})),
            (_, "tools/list") => {
                let mut result = json!({"tools": tools::definitions()});
                if ctx.modern {
                    result["ttlMs"] = json!(CACHE_MS);
                    result["cacheScope"] = json!("public");
                }
                Reply::Ok(result)
            }
            (_, "tools/call") => self.call_tool(params, ctx),
            (true, "tasks/get" | "tasks/update" | "tasks/cancel") => {
                if !ctx.tasks {
                    return missing_tasks_capability();
                }
                self.task_method(method, params, ctx)
            }
            (true, "subscriptions/listen") => self.listen(params, ctx),
            _ => Reply::Err(
                METHOD_NOT_FOUND,
                format!("Method not found: {method}"),
                None,
            ),
        }
    }

    fn call_tool(&self, params: &Value, ctx: &Ctx) -> Reply {
        let Some(name) = params["name"].as_str() else {
            return Reply::Err(INVALID_PARAMS, "tools/call needs a tool name".into(), None);
        };
        let arguments = match &params["arguments"] {
            Value::Null => json!({}),
            Value::Object(_) => params["arguments"].clone(),
            _ => {
                return Reply::Err(
                    INVALID_PARAMS,
                    "tool arguments must be an object".into(),
                    None,
                );
            }
        };
        if !tools::exists(name) {
            return Reply::Err(INVALID_PARAMS, format!("Unknown tool: {name}"), None);
        }
        match tools::call(self, name, &arguments, ctx) {
            tools::Outcome::Done(value) => Reply::Ok(tools::tool_result(value, false)),
            tools::Outcome::Failed(error) => Reply::Ok(tools::tool_result(error.value(), true)),
            tools::Outcome::Task(task) => Reply::Ok(task),
            tools::Outcome::Cancelled => Reply::Silent,
        }
    }

    fn task_method(&self, method: &str, params: &Value, ctx: &Ctx) -> Reply {
        let Some(task_id) = params["taskId"].as_str() else {
            return Reply::Err(INVALID_PARAMS, "taskId must be a string".into(), None);
        };
        let job_id = match tasks::job_of(&self.root, task_id) {
            Ok(Some(job)) => job,
            Ok(None) => {
                return Reply::Err(
                    INVALID_PARAMS,
                    "Failed to retrieve task: Task not found".into(),
                    None,
                );
            }
            Err(e) => return Reply::Err(INTERNAL_ERROR, format!("task store: {e}"), None),
        };
        match method {
            "tasks/get" => match tasks::detailed(self, task_id, &job_id, ctx) {
                Ok(task) => Reply::Ok(task),
                Err(tools::Fail::Cancelled) => Reply::Silent,
                Err(tools::Fail::Tool(e)) => job_error(&job_id, "read", &e),
            },
            // No task of this server asks for input; responses are ignored.
            "tasks/update" => Reply::Ok(json!({})),
            _ => match tools::cancel(self, &job_id, false) {
                Ok(_) => Reply::Ok(json!({})),
                // A job that already ended has nothing to cancel; the
                // acknowledgement promises no transition.
                Err(tools::Fail::Tool(e)) if e.code == "already_terminal" => Reply::Ok(json!({})),
                Err(tools::Fail::Cancelled) => Reply::Silent,
                Err(tools::Fail::Tool(e)) => job_error(&job_id, "cancel", &e),
            },
        }
    }

    /// `subscriptions/listen`: task status notifications for `taskIds`. The
    /// server sends no other notification type; the stream stays open until
    /// the client cancels it.
    fn listen(&self, params: &Value, ctx: &Ctx) -> Reply {
        let Some(filter) = params["notifications"].as_object() else {
            return Reply::Err(
                INVALID_PARAMS,
                "subscriptions/listen needs a notifications object".into(),
                None,
            );
        };
        let wanted = filter.get("taskIds");
        if wanted.is_some() && !ctx.tasks {
            return missing_tasks_capability();
        }
        let mut tracked: Vec<(String, String)> = vec![];
        if let Some(ids) = wanted {
            let Some(ids) = ids.as_array() else {
                return Reply::Err(INVALID_PARAMS, "taskIds must be an array".into(), None);
            };
            for id in ids.iter().filter_map(Value::as_str) {
                if let Ok(Some(job)) = tasks::job_of(&self.root, id)
                    && !tracked.iter().any(|(t, _)| t == id)
                {
                    tracked.push((id.to_owned(), job));
                }
            }
        }
        let mut agreed = Map::new();
        if wanted.is_some() {
            agreed.insert(
                "taskIds".into(),
                json!(tracked.iter().map(|(t, _)| t).collect::<Vec<_>>()),
            );
        }
        self.notify(
            "notifications/subscriptions/acknowledged",
            json!({"_meta":{SUBSCRIPTION:ctx.id},"notifications":agreed}),
        );
        let mut last: HashMap<String, String> = HashMap::new();
        while !ctx.stopped(self) {
            tracked.retain(|(task_id, job_id)| {
                let Ok(mut task) = tasks::detailed(self, task_id, job_id, ctx) else {
                    return true;
                };
                let status = task["status"].as_str().unwrap_or_default().to_owned();
                if last.get(task_id) != Some(&status) {
                    if let Some(object) = task.as_object_mut() {
                        object.remove("resultType");
                        object.insert("_meta".into(), json!({SUBSCRIPTION:ctx.id}));
                    }
                    self.notify("notifications/tasks", task);
                    last.insert(task_id.clone(), status.clone());
                }
                !tasks::terminal_status(&status)
            });
            tools::pause(self, ctx, tasks::POLL);
        }
        Reply::Silent
    }

    fn notification(&self, method: &str, params: &Value) {
        if method == "notifications/cancelled" {
            let id = params["requestId"].to_string();
            if let Some(flag) = self
                .inflight
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .get(&id)
            {
                flag.store(true, Ordering::Relaxed);
            }
        }
        // notifications/initialized and anything else need no action.
    }

    fn error(id: Value, code: i64, message: &str) -> Value {
        json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
    }

    fn busy(id: Value, message: String) -> Value {
        json!({"jsonrpc":"2.0","id":id,"error":{"code":SERVER_BUSY,"message":message,
            "data":{"retryable":true}}})
    }

    /// Starts one message of the input: a request runs on a thread of its
    /// own and yields its response through the handle; a notification or a
    /// client's response yields nothing.
    fn accept(self: &Arc<Self>, message: Value) -> Option<thread::JoinHandle<Option<Value>>> {
        let method = message["method"].as_str().map(str::to_owned);
        let params = message.get("params").cloned().unwrap_or(json!({}));
        let immediate = |reply: Value| Some(thread::spawn(move || Some(reply)));
        match (method, message.get("id")) {
            // Responses from the client: this server sends no requests.
            (None, _) if message.is_object() && message.get("id").is_some() => None,
            (Some(method), None) if message.is_object() => {
                self.notification(&method, &params);
                None
            }
            (Some(method), Some(id)) if id.is_string() || id.is_number() => {
                let cancel = Arc::new(AtomicBool::new(false));
                let waits = method == "subscriptions/listen"
                    || (method == "tools/call" && params["name"] == "wait_job");
                {
                    let mut inflight = self.inflight.lock().unwrap_or_else(|e| e.into_inner());
                    if inflight.contains_key(&id.to_string()) {
                        // Answering under that ID would give it two responses.
                        eprintln!("optimization-mcp: request id {id} is already in use");
                        return immediate(Self::error(
                            Value::Null,
                            INVALID_REQUEST,
                            &format!("request id {id} is already in use"),
                        ));
                    }
                    if inflight.len() >= MAX_REQUESTS {
                        return immediate(Self::busy(
                            id.clone(),
                            format!(
                                "server busy: {MAX_REQUESTS} requests in progress; retry later"
                            ),
                        ));
                    }
                    if waits && self.waiting.fetch_add(1, Ordering::Relaxed) >= MAX_WAITING {
                        self.waiting.fetch_sub(1, Ordering::Relaxed);
                        return immediate(Self::busy(
                            id.clone(),
                            format!(
                                "server busy: {MAX_WAITING} waiting requests (wait_job, subscriptions/listen) in progress; retry later"
                            ),
                        ));
                    }
                    inflight.insert(id.to_string(), cancel.clone());
                }
                let server = self.clone();
                let id = id.clone();
                Some(thread::spawn(move || {
                    let response = server.request(id, method, params, cancel);
                    if waits {
                        server.waiting.fetch_sub(1, Ordering::Relaxed);
                    }
                    response
                }))
            }
            _ => immediate(Self::error(Value::Null, INVALID_REQUEST, "Invalid request")),
        }
    }

    fn serve(self: Arc<Self>) {
        let mut input = io::stdin().lock();
        let mut line = Vec::new();
        loop {
            match read_message(&mut input, &mut line) {
                Ok(Frame::End) | Err(_) => break,
                Ok(Frame::TooLong) => {
                    self.send(&Self::error(
                        Value::Null,
                        INVALID_REQUEST,
                        &format!("message longer than {MAX_MESSAGE} bytes; skipped"),
                    ));
                    continue;
                }
                Ok(Frame::Message) => {}
            }
            if line.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            let message: Value = match serde_json::from_slice(&line) {
                Ok(message) => message,
                Err(e) => {
                    self.send(&Self::error(
                        Value::Null,
                        PARSE_ERROR,
                        &format!("Parse error: {e}"),
                    ));
                    continue;
                }
            };
            match message {
                // A JSON-RPC batch (protocol 2025-03-26): one array of the
                // responses, sent when all of them are ready, so a stream
                // that never ends cannot be part of one.
                Value::Array(messages)
                    if !messages.is_empty() && self.batches.load(Ordering::Relaxed) =>
                {
                    let handles: Vec<_> = messages
                        .into_iter()
                        .filter_map(|m| {
                            if m["method"] == "subscriptions/listen" {
                                let id = m.get("id").cloned().unwrap_or(Value::Null);
                                let reply = Self::error(
                                    id,
                                    INVALID_REQUEST,
                                    "subscriptions/listen cannot be part of a batch",
                                );
                                return Some(thread::spawn(move || Some(reply)));
                            }
                            self.accept(m)
                        })
                        .collect();
                    let server = self.clone();
                    thread::spawn(move || {
                        let responses: Vec<Value> = handles
                            .into_iter()
                            .filter_map(|h| h.join().ok().flatten())
                            .collect();
                        if !responses.is_empty() {
                            server.send(&Value::Array(responses));
                        }
                    });
                }
                Value::Array(messages) => self.send(&Self::error(
                    Value::Null,
                    INVALID_REQUEST,
                    if messages.is_empty() {
                        "empty batch"
                    } else {
                        "JSON-RPC batches are part of protocol 2025-03-26 only; initialize with it to send them"
                    },
                )),
                message => {
                    if let Some(handle) = self.accept(message) {
                        let server = self.clone();
                        thread::spawn(move || {
                            if let Ok(Some(response)) = handle.join() {
                                server.send(&response);
                            }
                        });
                    }
                }
            }
        }
        // End of input is the stdio shutdown signal. Jobs keep running.
        self.shutdown.store(true, Ordering::Relaxed);
    }
}

enum Frame {
    Message,
    TooLong,
    End,
}

/// Reads one line of at most [`MAX_MESSAGE`] bytes into `line`. The rest of
/// a longer line is consumed without being kept.
fn read_message(input: &mut impl BufRead, line: &mut Vec<u8>) -> io::Result<Frame> {
    line.clear();
    if input
        .by_ref()
        .take(MAX_MESSAGE as u64 + 1)
        .read_until(b'\n', line)?
        == 0
    {
        return Ok(Frame::End);
    }
    if line.len() <= MAX_MESSAGE || line.ends_with(b"\n") {
        return Ok(Frame::Message);
    }
    line.clear();
    line.shrink_to(1 << 16);
    loop {
        let buffer = input.fill_buf()?;
        if buffer.is_empty() {
            return Ok(Frame::TooLong);
        }
        match buffer.iter().position(|&b| b == b'\n') {
            Some(end) => {
                input.consume(end + 1);
                return Ok(Frame::TooLong);
            }
            None => {
                let all = buffer.len();
                input.consume(all);
            }
        }
    }
}

pub fn main() {
    if !cfg!(target_os = "linux") {
        eprintln!("optimization-mcp: Linux is required");
        std::process::exit(2);
    }
    let args = Args::parse();
    let fail = |message: String| -> ! {
        eprintln!("optimization-mcp: {message}");
        std::process::exit(2)
    };
    let runner = args.runner.unwrap_or_else(|| {
        std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|dir| dir.join("optimization-run")))
            .unwrap_or_else(|| PathBuf::from("optimization-run"))
    });
    let runner = std::fs::canonicalize(&runner)
        .unwrap_or_else(|e| fail(format!("runner {}: {e}", runner.display())));
    if let Err(e) = std::fs::create_dir_all(&args.root) {
        fail(format!("node root {}: {e}", args.root.display()));
    }
    let root = std::fs::canonicalize(&args.root)
        .unwrap_or_else(|e| fail(format!("node root {}: {e}", args.root.display())));
    let input_dir = args
        .input_dir
        .map_or_else(std::env::current_dir, Ok)
        .and_then(std::fs::canonicalize)
        .unwrap_or_else(|e| fail(format!("input directory: {e}")));
    tools::clean_staging(&root);
    inputs::clean(&root);
    eprintln!(
        "optimization-mcp {}: node {}, runner {}, launch {}",
        env!("CARGO_PKG_VERSION"),
        root.display(),
        runner.display(),
        args.launch.name()
    );
    let server = Arc::new(Server {
        root,
        runner,
        launch: args.launch,
        input_dir,
        input_store_bytes: args.input_store_bytes,
        out: Mutex::new(io::stdout()),
        inflight: Mutex::new(HashMap::new()),
        initialized: AtomicBool::new(false),
        batches: AtomicBool::new(false),
        shutdown: AtomicBool::new(false),
        waiting: AtomicUsize::new(0),
        validations: (Mutex::new(0), Condvar::new()),
    });
    server.serve();
}
