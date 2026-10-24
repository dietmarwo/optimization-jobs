//! Internal lifecycle shared by adapters. No optimizer request or result types.
//!
//! The neutral record is a terminal observation, not a second source of job
//! state. The optimization adapter still owns the native result and its claims.
use crate::{
    Stop, admission, directory, install_stop_handlers, now, read, state_write, stop_request,
    supervision::{self, Budget, Observation, StopReason},
    terminal,
};
use optimization_job_api::{
    Result, coded,
    storage::{lock, write_atomic_json},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    fs,
    path::Path,
    process::Command,
    thread,
    time::{Duration, Instant},
};

pub(crate) const RECORD_SCHEMA: &str = "execution.record/0.1";
pub(crate) const RECORD_FILE: &str = ".execution.json";

/// Adapter-specific accounting stays in Outcome and never reaches supervision.
pub(crate) trait Adapter {
    type Outcome;
    fn kind(&self) -> &'static str;
    fn budget(&self) -> Budget;
    fn command(&self, dir: &Path) -> Result<Command>;
    fn completed(&self, dir: &Path, observed: &Observation) -> Result<Self::Outcome>;
    fn cancelled_before_start(&self) -> Self::Outcome;
    fn failed(&self) -> Self::Outcome;
    fn finalize(
        &self,
        dir: &Path,
        outcome: Self::Outcome,
        elapsed: Option<f64>,
    ) -> Result<Finalized>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum State {
    Completed,
    Failed,
    Cancelled,
    TimedOut,
    Interrupted,
}
impl State {
    pub(crate) fn parse(value: &str) -> Result<Self> {
        Ok(serde_json::from_value(json!(value))?)
    }
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::TimedOut => "timed_out",
            Self::Interrupted => "interrupted",
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct NativeResult {
    pub file: String,
    // Legacy fcmaes manifests use the integer 1; the shared format uses a string.
    pub schema_version: Value,
    pub bytes: u64,
    pub sha256: String,
}
pub(crate) struct Finalized {
    pub state: State,
    pub native_result: Option<NativeResult>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Logs {
    stdout: Option<String>,
    stderr: Option<String>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {
    schema_version: String,
    attempt_id: String,
    identity: Option<String>,
    kind: String,
    state: State,
    source: String,
    cpu_slots: usize,
    started_at: Option<f64>,
    finished_at: f64,
    elapsed_seconds: Option<f64>,
    observation: Observation,
    logs: Logs,
    native_result: Option<NativeResult>,
}

pub(crate) fn capabilities() -> Value {
    json!({
        "schema_version":"execution.capabilities/0.1",
        "runner_version":env!("CARGO_PKG_VERSION"),
        "execution_kinds":["optimization"],
        "job_schemas":["optimization.job/0.1", "fcmaes.job/0.1"],
        "worker_protocols":["optimization.worker/0.1", "optimization.worker/0.2", "fcmaes.worker/0.1"],
        "optimization_result_schema":"optimization.result/0.2",
        "legacy_fcmaes_result_schema":1,
        "execution_record_schema":RECORD_SCHEMA,
        "execution_record_publication":"terminal",
        "command_jobs":false, "generic_file_transfer":false, "fleet":false
    })
}

/// The record of a finished attempt. It is served only when `job.json` is
/// terminal with the same state and finish time: the worker runs in the job
/// directory, and a launcher lost between the record and `job.json` leaves a
/// record that repair will replace.
pub(crate) fn record(dir: &Path) -> Result<Value> {
    let job = read(&dir.join("job.json"))?;
    if !terminal(&job["state"]) {
        return Err(coded(
            "attempt_active",
            "the attempt has not finished; wait for a terminal state (jobs wait), or repair it if its launcher was lost",
        ));
    }
    let unavailable = || {
        coded(
            "execution_unavailable",
            "this finished attempt has no execution record; it predates execution records",
        )
    };
    let bytes = fs::read(dir.join(RECORD_FILE)).map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            unavailable()
        } else {
            error.into()
        }
    })?;
    let record: Record = serde_json::from_slice(&bytes)?;
    if record.schema_version != RECORD_SCHEMA {
        return Err("unsupported execution record schema".into());
    }
    if json!(record.state) != job["state"] || json!(record.finished_at) != job["finished_at"] {
        return Err(unavailable());
    }
    Ok(serde_json::to_value(record)?)
}

/// Publish the native attachment first, the neutral observation second, and
/// the existing terminal job state last. A crash does not authorize a rerun.
pub(crate) fn finish<A: Adapter>(
    dir: &Path,
    adapter: &A,
    outcome: A::Outcome,
    elapsed: Option<f64>,
    observation: Observation,
    source: &str,
) -> Result<()> {
    let finalized = adapter.finalize(dir, outcome, elapsed)?;
    let provenance = read(&dir.join("provenance.json"))?;
    let mut state = read(&dir.join("job.json"))?;
    let finished_at = now();
    let record = Record {
        schema_version: RECORD_SCHEMA.into(),
        attempt_id: provenance["attempt_id"]
            .as_str()
            .or_else(|| state["id"].as_str())
            .ok_or("missing attempt id")?
            .into(),
        // Older provenance may lack the content identity. Do not invent one
        // or prevent recovery of an otherwise valid attempt.
        identity: provenance["identity"].as_str().map(str::to_owned),
        kind: adapter.kind().into(),
        state: finalized.state,
        source: source.into(),
        cpu_slots: adapter.budget().cpu_slots,
        started_at: state["started_at"].as_f64(),
        finished_at,
        elapsed_seconds: elapsed,
        observation,
        logs: Logs {
            stdout: dir
                .join("stdout.log")
                .is_file()
                .then(|| "stdout.log".into()),
            stderr: dir
                .join("stderr.log")
                .is_file()
                .then(|| "stderr.log".into()),
        },
        native_result: finalized.native_result,
    };
    write_atomic_json(&dir.join(RECORD_FILE), &record)?;
    state["state"] = json!(finalized.state);
    state["finished_at"] = json!(finished_at);
    state_write(&dir.join("job.json"), &state)
}

/// The adapter is loaded under the existing attempt lock, just as the request
/// was before extraction. Admission, cancellation and release ordering stays.
pub(crate) fn launch<A: Adapter>(
    root: &Path,
    id: &str,
    load: impl FnOnce(&Path) -> Result<A>,
) -> Result<()> {
    let dir = directory(root, id)?;
    let _owner = lock(&dir.join("job.lock"))?;
    let mut state = read(&dir.join("job.json"))?;
    if !matches!(state["state"].as_str(), Some("submitted" | "starting")) {
        return Err("attempt already started; no implicit restart".into());
    }
    let adapter = load(&dir)?;
    install_stop_handlers();
    state["state"] = json!("waiting");
    state_write(&dir.join("job.json"), &state)?;
    let queue = Instant::now();
    loop {
        if stop_request(&dir) != Stop::None {
            return finish(
                &dir,
                &adapter,
                adapter.cancelled_before_start(),
                Some(0.0),
                Observation {
                    stop_reason: Some(StopReason::Cancelled),
                    ..Observation::default()
                },
                "launcher",
            );
        }
        if admission::admit(root, id, &dir, adapter.budget().cpu_slots)? {
            break;
        }
        thread::sleep(Duration::from_millis(200));
    }
    let start = Instant::now();
    state["state"] = json!("running");
    state["started_at"] = json!(now());
    state["queue_seconds"] = json!(queue.elapsed().as_secs_f64());
    if let Err(error) = state_write(&dir.join("job.json"), &state) {
        admission::release(root, id)?;
        return Err(error);
    }
    let mut observed = Observation::default();
    let outcome = (|| {
        let command = adapter.command(&dir)?;
        supervision::execute(&dir, adapter.budget(), command, start, &mut observed)?;
        adapter.completed(&dir, &observed)
    })();
    // Unknown containment always retains its reservation, including an error
    // while recording the process group or determining liveness.
    if observed.can_release() {
        admission::release(root, id)?;
    }
    match outcome {
        Ok(outcome) => finish(
            &dir,
            &adapter,
            outcome,
            Some(start.elapsed().as_secs_f64()),
            observed,
            "launcher",
        ),
        Err(error) => {
            let _ = finish(
                &dir,
                &adapter,
                adapter.failed(),
                Some(start.elapsed().as_secs_f64()),
                observed,
                "launcher",
            );
            Err(error)
        }
    }
}

#[cfg(test)]
mod tests;
