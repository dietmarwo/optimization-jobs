use super::{Blob, Failure, Operation, PROTOCOL, Request, Response, Selection, frame, node};
use crate::{
    command, directory, execution, files, get, now, prepare, publish_stop, read, submit, terminal,
};
use optimization_job_api::{
    Result, coded, error_code, retryable,
    storage::{digest, lock, write_atomic_json},
};
use serde_json::{Value, json};
use std::{
    fs,
    io::{BufReader, Read, Write},
    path::{Path, PathBuf},
};

pub(super) fn serve() -> Result<()> {
    let mut input = BufReader::new(super::io::Deadline::new(libc::STDIN_FILENO)?);
    let mut actual = None;
    let result = (|| -> Result<(Value, Option<fs::File>)> {
        let request: Request = serde_json::from_slice(&frame(&mut input)?)
            .map_err(|e| coded("remote_protocol", e.to_string()))?;
        if request.schema_version != PROTOCOL || !request.root.is_absolute() {
            return Err(coded(
                "remote_protocol",
                "unsupported protocol or relative root",
            ));
        }
        let root = fs::canonicalize(&request.root)?;
        actual = node::identity(&root, false)?["node_id"]
            .as_str()
            .map(str::to_owned);
        if !matches!(request.operation, Operation::Describe) && request.node_id != actual {
            return Err(coded(
                "node_identity_mismatch",
                "the selected root has a different persistent identity",
            ));
        }
        if !matches!(request.operation, Operation::Put { .. }) {
            let mut extra = [0];
            if input.read(&mut extra)? != 0 {
                return Err(coded(
                    "remote_protocol",
                    "unexpected bytes after control request",
                ));
            }
        }
        handle(&root, request.operation, &mut input)
    })();
    let (response, file) = match result {
        Ok((value, file)) => (
            Response {
                schema_version: PROTOCOL.into(),
                node_id: actual,
                result: Some(value),
                error: None,
            },
            file,
        ),
        Err(error) => {
            let code = error_code(&error);
            (
                Response {
                    schema_version: PROTOCOL.into(),
                    node_id: actual,
                    result: None,
                    error: Some(Failure {
                        code: code.into(),
                        message: error.to_string(),
                        retryable: retryable(code),
                    }),
                },
                None,
            )
        }
    };
    let mut out = super::io::Deadline::new(libc::STDOUT_FILENO)?;
    serde_json::to_writer(&mut out, &response)?;
    out.write_all(b"\n")?;
    if let Some(source) = file {
        std::io::copy(&mut source.take(files::MAX_FILE + 1), &mut out)?;
    }
    out.flush()?;
    Ok(())
}
fn valid_id(id: &str) -> Result<()> {
    if !files::hash_ok(id) {
        return Err(coded("remote_protocol", "invalid dispatch identity"));
    }
    Ok(())
}
fn entry(root: &Path, id: &str) -> Result<PathBuf> {
    valid_id(id)?;
    Ok(root.join("remote-dispatch").join(format!("{id}.json")))
}
fn dispatch_lock(root: &Path, id: &str) -> PathBuf {
    root.join("remote-dispatch").join(format!("{id}.lock"))
}
/// A `preparing` record whose dispatch lock is free belongs to a helper that
/// stopped before the launch barrier: that dispatch launched nothing and never
/// will. Call only while holding the dispatch lock.
fn settle_interrupted(path: &Path) -> Result<()> {
    let mut record = read(path)?;
    if record["phase"] == "preparing" {
        record["phase"] = json!("prepare_failed");
        record["error"] = json!({"code":"interrupted","message":"the helper stopped before the launch barrier; nothing was launched"});
        write_atomic_json(path, &record)?;
    }
    Ok(())
}
fn lookup(root: &Path, id: &str) -> Result<Value> {
    let path = entry(root, id)?;
    if !path.exists() {
        return Ok(json!({"found":false,"dispatch_id":id}));
    }
    if read(&path)?["phase"] == "preparing" {
        let file = fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(dispatch_lock(root, id))?;
        // A held lock is a helper still preparing: the record stays as it is.
        if fs2::FileExt::try_lock_exclusive(&file).is_ok() {
            settle_interrupted(&path)?;
        }
    }
    let record = read(&path)?;
    let job = record["job_id"].as_str().and_then(|id| get(root, id).ok());
    Ok(json!({"found":true,"dispatch":record,"job":job}))
}
/// The local job of a dispatch, `remote_dispatch_unknown` when the node has no
/// dispatch with this ID or created no job for it.
fn local_job(root: &Path, id: &str) -> Result<String> {
    let path = entry(root, id)?;
    if !path.exists() {
        return Err(coded(
            "remote_dispatch_unknown",
            "this node has no dispatch with this ID",
        ));
    }
    let record = read(&path)?;
    match record["job_id"].as_str() {
        Some(job) if directory(root, job).is_ok() => Ok(job.to_owned()),
        _ => Err(coded(
            "remote_dispatch_unknown",
            format!(
                "dispatch {} created no local job (phase {})",
                id, record["phase"]
            ),
        )),
    }
}
fn job_dir(root: &Path, id: &str) -> Result<PathBuf> {
    directory(root, &local_job(root, id)?)
}
fn handle(root: &Path, op: Operation, input: &mut impl Read) -> Result<(Value, Option<fs::File>)> {
    let value = match op {
        Operation::Describe => node::describe(root)?,
        Operation::Put { sha256, bytes } => files::put_stream(root, input, bytes, &sha256)?,
        Operation::Submit {
            dispatch_id,
            identity,
            spec,
            inputs,
            worker,
        } => dispatch(root, &dispatch_id, &identity, spec, &inputs, worker)?,
        Operation::Lookup { dispatch_id } => lookup(root, &dispatch_id)?,
        Operation::Cancel {
            dispatch_id,
            immediate,
        } => {
            let dir = job_dir(root, &dispatch_id)?;
            if terminal(&read(&dir.join("job.json"))?["state"]) {
                return Err(coded("already_terminal", "attempt already ended"));
            }
            publish_stop(
                &dir,
                json!({"mode":if immediate{"immediate"}else{"graceful"},"reason":"cancelled","requested_at":now()}),
            )?;
            lookup(root, &dispatch_id)?
        }
        Operation::Execution { dispatch_id } => execution::record(&job_dir(root, &dispatch_id)?)?,
        Operation::Repair { dispatch_id } => {
            crate::repair(root, &local_job(root, &dispatch_id)?)?;
            lookup(root, &dispatch_id)?
        }
        Operation::Inspect {
            dispatch_id,
            selection,
        } => inspect(root, &dispatch_id, &selection)?.0,
        Operation::Download {
            dispatch_id,
            selection,
            bytes,
            sha256,
        } => {
            let (meta, path) = inspect(root, &dispatch_id, &selection)?;
            if meta["bytes"] != bytes || meta["sha256"] != sha256 {
                return Err(coded(
                    "file_transfer_failed",
                    "remote artifact changed after inspection",
                ));
            }
            return Ok((meta, Some(files::open(&path)?)));
        }
    };
    Ok((value, None))
}
fn dispatch(
    root: &Path,
    id: &str,
    identity: &str,
    mut spec: Value,
    inputs: &[Blob],
    worker: Option<Value>,
) -> Result<Value> {
    valid_id(identity)?;
    let path = entry(root, id)?;
    fs::create_dir_all(root.join("remote-dispatch"))?;
    let _guard = lock(&dispatch_lock(root, id))?;
    let binding = digest(&serde_json::to_vec(
        &json!({"identity":identity,"spec":spec,"inputs":inputs,"worker":worker}),
    )?);
    if path.exists() {
        let old = read(&path)?;
        if old["binding"] != binding {
            return Err(coded(
                "request_key_conflict",
                "dispatch id already binds different content",
            ));
        }
        settle_interrupted(&path)?;
        return lookup(root, id);
    }
    // A refusal is recorded under the lock, so that a lookup after a lost
    // answer proves that this dispatch launched nothing.
    let refused = (|| -> Result<()> {
        if node::durable()["available"] != true {
            return Err(coded(
                "durable_launcher_unavailable",
                "remote dispatch requires a responding systemd user manager and Linger=yes",
            ));
        }
        for path in [root.to_path_buf(), std::env::current_exe()?] {
            if path.to_string_lossy().contains('$') {
                return Err(coded(
                    "invalid_remote_node",
                    format!(
                        "systemd-run would expand `$` in {}; use a node root and helper path without `$`",
                        path.display()
                    ),
                ));
            }
        }
        let schema = spec["schema_version"].as_str().unwrap_or_default();
        if !matches!(schema, "optimization.job/0.1" | command::SCHEMA) {
            return Err(coded(
                "unsupported_job_kind",
                "remote execution accepts shared optimization jobs or opt-in command jobs",
            ));
        }
        if schema == command::SCHEMA && std::env::var_os(command::REFUSE).is_some() {
            return Err(coded(
                "unsupported_job_kind",
                "this caller refuses command execution",
            ));
        }
        if schema == "optimization.job/0.1" {
            let expected = worker.as_ref().ok_or_else(|| {
                coded(
                    "remote_protocol",
                    "optimization dispatch needs a pinned worker identity",
                )
            })?;
            let registered = crate::worker(root, spec["worker"].as_str().ok_or("missing worker")?)?;
            if registered["digest"] != expected["digest"] {
                return Err(coded(
                    "remote_worker_changed",
                    "worker registration changed after placement",
                ));
            }
        }
        Ok(())
    })();
    if let Err(error) = refused {
        write_atomic_json(
            &path,
            &json!({"schema_version":"execution.remote.dispatch/0.1","dispatch_id":id,"identity":identity,"binding":binding,"node_id":node::identity(root,false)?["node_id"],"phase":"rejected","created_at":now(),"job_id":null,"error":{"code":error_code(&error),"message":error.to_string()}}),
        )?;
        return lookup(root, id);
    }
    let key = format!("remote:{id}");
    spec["request_key"] = json!(key);
    let predicted = digest(key.as_bytes())[..32].to_owned();
    let mut record = json!({"schema_version":"execution.remote.dispatch/0.1","dispatch_id":id,"identity":identity,"binding":binding,"node_id":node::identity(root,false)?["node_id"],"phase":"preparing","created_at":now(),"job_id":predicted});
    write_atomic_json(&path, &record)?;
    let prepared = (|| -> Result<(String, bool)> {
        if inputs.len() > 128 {
            return Err(coded("remote_protocol", "too many input attachments"));
        }
        let tmp = tempfile::tempdir_in(root)?;
        let mut seen = std::collections::BTreeSet::new();
        let mut total = 0;
        for blob in inputs {
            if !seen.insert(blob.index)
                || blob.bytes > files::MAX_FILE
                || !files::hash_ok(&blob.sha256)
            {
                return Err(coded("remote_protocol", "invalid input attachment"));
            }
            total += blob.bytes;
            if total > files::MAX_TOTAL {
                return Err(coded(
                    "file_transfer_failed",
                    "remote inputs exceed 256 MiB",
                ));
            }
            let input = &mut spec["inputs"]
                .as_array_mut()
                .ok_or("missing inputs")?
                .get_mut(blob.index)
                .ok_or("bad input attachment index")?;
            if input["sha256"] != blob.sha256 {
                return Err(coded(
                    "file_transfer_failed",
                    "input attachment digest does not match request",
                ));
            }
            let file = format!("remote-input-{}", blob.index);
            let dest = tmp.path().join(&file);
            files::copy(
                &mut files::open(&files::blob(root, &blob.sha256)?)?,
                &dest,
                blob.bytes,
                Some((blob.bytes, &blob.sha256)),
            )?;
            input["file"] = json!(file);
        }
        if spec["inputs"]
            .as_array()
            .ok_or("inputs must be an array")?
            .len()
            != inputs.len()
        {
            return Err(coded(
                "remote_protocol",
                "every input must have a checked attachment",
            ));
        }
        let request = tmp.path().join("request.json");
        write_atomic_json(&request, &spec)?;
        prepare(root, &request, None, true)
    })();
    let (job_id, new) = match prepared {
        Ok(pair) => pair,
        Err(error) => {
            record["phase"] = json!("prepare_failed");
            record["error"] = json!({"code":error_code(&error),"message":error.to_string()});
            write_atomic_json(&path, &record)?;
            return lookup(root, id);
        }
    };
    if job_id != predicted {
        return Err(coded(
            "remote_protocol",
            "local request key resolved to an unexpected job id",
        ));
    }
    record["job_id"] = json!(job_id);
    let provenance = read(&directory(root, &job_id)?.join("provenance.json"))?;
    record["local_identity"] = provenance["identity"].clone();
    record["resolved_spec_sha256"] = json!(
        files::fingerprint(
            &directory(root, &job_id)?.join("resolved.json"),
            files::MAX_FILE
        )?
        .1
    );
    record["executable"] = provenance["executable"].clone();
    record["worker_digest"] = provenance["worker_digest"].clone();
    record["unit"] = read(&directory(root, &job_id)?.join("job.json"))?["unit"].clone();
    // This write is the at-most-once barrier. A crash on either side can leave
    // an uncertain attempt; observing/resending this dispatch NEVER launches it.
    record["phase"] = json!(if new {
        "launching"
    } else {
        "observed_existing"
    });
    write_atomic_json(&path, &record)?;
    if new {
        match submit(root, &job_id) {
            Ok(()) => record["phase"] = json!("accepted"),
            Err(error) => {
                record["phase"] = json!("launch_unknown");
                record["error"] = json!({"code":error_code(&error),"message":error.to_string()});
            }
        }
        write_atomic_json(&path, &record)?;
    }
    lookup(root, id)
}
fn inspect(root: &Path, id: &str, selection: &Selection) -> Result<(Value, PathBuf)> {
    let dir = job_dir(root, id)?;
    let record = execution::record(&dir)?;
    let (path, bytes, sha256) = match selection {
        Selection::Execution => {
            let path = dir.join(execution::RECORD_FILE);
            let (bytes, hash) = files::fingerprint(&path, files::MAX_FILE)?;
            (path, bytes, hash)
        }
        Selection::Native => {
            let native = &record["native_result"];
            let name = native["file"].as_str().ok_or("no native attachment")?;
            if !matches!(name, "run.json" | "command-result.json") {
                return Err(coded(
                    "remote_protocol",
                    "unsupported native attachment path",
                ));
            }
            (
                dir.join(name),
                native["bytes"].as_u64().ok_or("missing bytes")?,
                native["sha256"]
                    .as_str()
                    .ok_or("missing digest")?
                    .to_owned(),
            )
        }
        Selection::Output { name } => {
            let result = command::result(&dir)?;
            let meta = &result["outputs"][name];
            if meta.is_null()
                || name.is_empty()
                || !name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
            {
                return Err(coded(
                    "unknown_artifact",
                    "no sealed command output with this name",
                ));
            }
            (
                files::beneath(&dir.join(".command-outputs"), name)?,
                meta["bytes"].as_u64().ok_or("missing bytes")?,
                meta["sha256"].as_str().ok_or("missing digest")?.to_owned(),
            )
        }
        Selection::Artifact { name } => {
            if record["kind"] != "optimization" {
                return Err(coded(
                    "unsupported_job_kind",
                    "use command output selection",
                ));
            }
            let native = &record["native_result"];
            files::verify(
                &dir.join("run.json"),
                native["bytes"].as_u64().ok_or("missing bytes")?,
                native["sha256"].as_str().ok_or("missing digest")?,
            )?;
            let run = read(&dir.join("run.json"))?;
            let meta = &run["runner"]["artifact_index"][name];
            let file = meta["file"].as_str().ok_or_else(|| {
                coded(
                    "unknown_artifact",
                    "no sealed optimization artifact with this name",
                )
            })?;
            (
                files::beneath(&dir, file)?,
                meta["bytes"].as_u64().ok_or("missing bytes")?,
                meta["sha256"].as_str().ok_or("missing digest")?.to_owned(),
            )
        }
    };
    files::verify(&path, bytes, &sha256)?;
    Ok((
        json!({"schema_version":"execution.remote.file/0.1","selection":selection,"bytes":bytes,"sha256":sha256}),
        path,
    ))
}
