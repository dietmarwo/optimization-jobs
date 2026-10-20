//! Tasks of the MCP Tasks extension. A task stands for one submitted job;
//! its ID is an unguessable token stored in the node root, so tasks survive
//! a restart of the server just as their jobs do. Its status is derived from
//! the job's state each time it is read.
use super::{
    Ctx, Server,
    tools::{self, Fail, ToolError},
};
use optimization_job_api::storage::{lock, write_atomic_json};
use serde_json::{Value, json};
use std::{
    fs, io,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

/// Suggested polling interval, and the interval of task notifications.
pub const POLL: Duration = Duration::from_secs(2);

fn directory(root: &Path) -> PathBuf {
    root.join("mcp")
}

fn store(root: &Path) -> PathBuf {
    directory(root).join("tasks.json")
}

fn read(root: &Path) -> io::Result<Value> {
    match fs::read(store(root)) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(io::Error::other),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(json!({})),
        Err(e) => Err(e),
    }
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or_default()
}

/// The job a task stands for.
pub fn job_of(root: &Path, task_id: &str) -> io::Result<Option<String>> {
    Ok(read(root)?[task_id]["job_id"].as_str().map(str::to_owned))
}

pub fn terminal_status(status: &str) -> bool {
    matches!(status, "completed" | "failed" | "cancelled")
}

fn store_error(e: io::Error) -> Fail {
    Fail::Tool(ToolError {
        code: "runner_error".into(),
        message: format!("task store: {e}"),
        retryable: false,
    })
}

/// The `CreateTaskResult` for a submitted job. A resubmission of the same
/// job returns its existing task.
pub fn create(server: &Server, job_id: &str, job: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let task_id = {
        fs::create_dir_all(directory(&server.root)).map_err(store_error)?;
        let _guard = lock(&directory(&server.root).join("tasks.lock")).map_err(store_error)?;
        let mut tasks = read(&server.root).map_err(store_error)?;
        let existing = tasks.as_object().and_then(|tasks| {
            tasks
                .iter()
                .find(|(_, t)| t["job_id"] == job_id)
                .map(|(id, _)| id.clone())
        });
        match existing {
            Some(id) => id,
            None => {
                let id = format!("task-{}", tools::task_token().map_err(store_error)?);
                tasks[&id] = json!({"job_id":job_id,"created_at":now()});
                write_atomic_json(&store(&server.root), &tasks).map_err(store_error)?;
                id
            }
        }
    };
    let created = read(&server.root).map_err(store_error)?[&task_id]["created_at"].as_f64();
    let mut task = describe(server, &task_id, created, job, ctx)?;
    // A CreateTaskResult carries the task, not its result: tasks/get does.
    if let Some(object) = task.as_object_mut() {
        object.remove("result");
        object.remove("error");
    }
    task["resultType"] = json!("task");
    Ok(task)
}

/// The `DetailedTask` of `tasks/get` and of task notifications.
pub fn detailed(server: &Server, task_id: &str, job_id: &str, ctx: &Ctx) -> Result<Value, Fail> {
    let created = read(&server.root).map_err(store_error)?[task_id]["created_at"].as_f64();
    let job = server.get(job_id, ctx)?;
    describe(server, task_id, created, &job, ctx)
}

fn describe(
    server: &Server,
    task_id: &str,
    created: Option<f64>,
    job: &Value,
    ctx: &Ctx,
) -> Result<Value, Fail> {
    let created = created.unwrap_or_else(now);
    let updated = ["submitted_at", "started_at", "finished_at"]
        .iter()
        .filter_map(|k| job[*k].as_f64())
        .fold(created, f64::max);
    let id = job["job_id"].as_str().unwrap_or_default();
    let state = job["state"].as_str().unwrap_or("unknown");
    let mut task = json!({
        "taskId": task_id,
        "createdAt": iso(created),
        "lastUpdatedAt": iso(updated),
        "ttlMs": null,
        "pollIntervalMs": POLL.as_millis() as u64,
    });
    if state == "cancelled" {
        task["status"] = json!("cancelled");
        task["statusMessage"] = json!(format!(
            "job {id} was cancelled; get_result with job_id {id} returns the tasks it completed"
        ));
    } else if tools::terminal(&job["state"]) {
        task["status"] = json!("completed");
        task["statusMessage"] = json!(format!("job {id} ended {state}"));
        task["result"] = final_result(server, job, ctx)?;
    } else if let Some(observed) = job["observed_state"].as_str() {
        // Nothing will finish this attempt: say so instead of letting a
        // client poll forever.
        let message = format!(
            "job {id} was observed {observed}; repair_job with job_id {id} finalizes it, then get_result returns its committed tasks"
        );
        task["status"] = json!("completed");
        task["statusMessage"] = json!(message);
        task["result"] = tools::tool_result(
            json!({"job":job,"error":{"code":"attempt_interrupted","message":message,"retryable":false}}),
            true,
        );
    } else {
        task["status"] = json!("working");
        let mut message = format!("job {id} is {state}");
        if let (Some(done), Some(all)) = (
            job["completed_tasks"].as_u64(),
            job["requested_tasks"].as_u64(),
        ) {
            message.push_str(&format!(", {done} of {all} tasks completed"));
        }
        task["statusMessage"] = json!(message);
    }
    Ok(task)
}

/// What submit_job returns once the job has ended: its state and the result
/// summary of get_result. A failed or interrupted job is a tool error.
fn final_result(server: &Server, job: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let failed = matches!(job["state"].as_str(), Some("failed" | "interrupted"));
    match tools::manifest(server, job, ctx) {
        Ok(manifest) => Ok(tools::tool_result(
            json!({"job":job,"result":tools::summary(job, &manifest)}),
            failed,
        )),
        Err(Fail::Tool(error)) => Ok(tools::tool_result(
            json!({"job":job,"error":error.value()["error"]}),
            true,
        )),
        Err(Fail::Cancelled) => Err(Fail::Cancelled),
    }
}

/// RFC 3339 UTC time of a Unix timestamp, with milliseconds.
pub fn iso(unix: f64) -> String {
    let millis = (unix * 1000.0).round() as i64;
    let (seconds, ms) = (millis.div_euclid(1000), millis.rem_euclid(1000));
    let (days, day) = (seconds.div_euclid(86_400), seconds.rem_euclid(86_400));
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{ms:03}Z",
        day / 3600,
        day % 3600 / 60,
        day % 60
    )
}

#[cfg(test)]
mod tests {
    use super::iso;

    #[test]
    fn iso_times() {
        assert_eq!(iso(0.0), "1970-01-01T00:00:00.000Z");
        assert_eq!(iso(951_782_400.5), "2000-02-29T00:00:00.500Z");
        assert_eq!(iso(1_792_463_779.2), "2026-10-20T02:36:19.200Z");
        assert_eq!(iso(-1.0), "1969-12-31T23:59:59.000Z");
    }
}
