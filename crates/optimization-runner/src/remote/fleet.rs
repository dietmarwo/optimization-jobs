use super::{Blob, Endpoint, Failure, Operation, Selection, node, transport};
use crate::{command, files, now, optional, read};
use clap::{Subcommand, ValueEnum};
use optimization_job_api::{
    Result, coded,
    storage::{digest, lock, write_atomic_json},
};
use serde_json::{Value, json};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
};

#[derive(Subcommand)]
pub(crate) enum Cli {
    Nodes {
        #[command(subcommand)]
        command: Nodes,
    },
    Submit {
        #[arg(long)]
        node: String,
        #[arg(long)]
        spec: PathBuf,
    },
    List,
    Get {
        id: String,
    },
    /// Continue checked staging only, or observe an already issued dispatch.
    Resume {
        id: String,
    },
    /// Observe the same bound node; never issue another launch.
    Reconcile {
        id: String,
    },
    Cancel {
        id: String,
        #[arg(long)]
        now: bool,
    },
    Execution {
        id: String,
    },
    Repair {
        id: String,
    },
    Collect {
        id: String,
        #[arg(long, value_enum, default_value = "native")]
        kind: FileKind,
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        destination: PathBuf,
    },
}
#[derive(Subcommand)]
pub(crate) enum Nodes {
    Add {
        name: String,
        #[command(flatten)]
        endpoint: Endpoint,
    },
    List,
    Probe {
        name: String,
    },
}
#[derive(Clone, ValueEnum)]
pub(crate) enum FileKind {
    Native,
    Execution,
    Output,
    Artifact,
}
fn json_call(e: &Endpoint, id: Option<&str>, op: Operation) -> Result<Value> {
    let mut reply = transport::call(e, id, op, None)?;
    let mut byte = [0];
    if reply.body.read(&mut byte)? != 0 {
        return Err(coded(
            "remote_protocol",
            "unexpected bytes after control response",
        ));
    }
    Ok(reply.value)
}
fn dir(root: &Path, id: &str) -> Result<PathBuf> {
    if id.len() != 32 || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(coded("unknown_job", "invalid fleet job id"));
    }
    Ok(root.join("fleet/jobs").join(id))
}
fn coordinator(root: &Path) -> Result<String> {
    let path = root.join("fleet/config.json");
    let v = if path.exists() {
        read(&path)?
    } else {
        let v = json!({"schema_version":"execution.fleet/0.1","coordinator_id":node::fresh_id()?});
        write_atomic_json(&path, &v)?;
        v
    };
    Ok(v["coordinator_id"]
        .as_str()
        .filter(|s| files::hash_ok(s))
        .ok_or("invalid coordinator identity")?
        .into())
}
fn registered(root: &Path, name: &str) -> Result<Value> {
    let node = optional(&root.join("fleet/nodes.json"))?[name].clone();
    if node.is_null() {
        return Err(coded(
            "unknown_remote_node",
            "register an explicit node first with fleet nodes add",
        ));
    }
    Ok(node)
}
fn endpoint(state: &Value) -> Result<Endpoint> {
    Ok(serde_json::from_value(state["endpoint"].clone())?)
}
fn bound_node(state: &Value) -> Result<&str> {
    state["node_id"]
        .as_str()
        .ok_or_else(|| "missing pinned node identity".into())
}
fn dispatch_id(state: &Value) -> Result<&str> {
    state["dispatch_id"]
        .as_str()
        .ok_or_else(|| "missing dispatch id".into())
}
fn save(dir: &Path, state: &mut Value) -> Result<()> {
    state["updated_at"] = json!(now());
    write_atomic_json(&dir.join("dispatch.json"), state)?;
    Ok(())
}
fn observe(state: &mut Value, answer: Value) -> Result<()> {
    if answer["found"] == false {
        if state["phase"] != "staging" {
            state["phase"] = json!("unknown");
        }
        state["observation"] = json!(
            "not_observed; resume only an unsent staging intent; never move an uncertain dispatch"
        );
        state["remote"] = answer;
        return Ok(());
    }
    let r = &answer["dispatch"];
    if r["dispatch_id"] != state["dispatch_id"]
        || r["identity"] != state["identity"]
        || r["node_id"] != state["node_id"]
    {
        return Err(coded(
            "remote_protocol",
            "remote dispatch binding differs from persisted intent",
        ));
    }
    let key = format!("remote:{}", dispatch_id(state)?);
    // A refused dispatch has no local job.
    if !r["job_id"].is_null() && r["job_id"] != digest(key.as_bytes())[..32] {
        return Err(coded(
            "remote_protocol",
            "unexpected remote local-job mapping",
        ));
    }
    if let Some(identity) = r["local_identity"].as_str() {
        if !files::hash_ok(identity)
            || state
                .get("remote_identity")
                .is_some_and(|old| old != identity)
        {
            return Err(coded("remote_protocol", "remote resolved identity changed"));
        }
        state["remote_identity"] = json!(identity);
    }
    let job = &answer["job"];
    let phase = if crate::terminal(&job["state"]) {
        "finished"
    } else if matches!(r["phase"].as_str(), Some("prepare_failed" | "rejected")) {
        "rejected"
    } else if r["phase"] == "accepted"
        || r["phase"] == "observed_existing"
        || matches!(job["state"].as_str(), Some("waiting" | "running"))
    {
        "accepted"
    } else {
        "unknown"
    };
    state["phase"] = json!(phase);
    state["remote"] = answer;
    Ok(())
}
fn reconcile(dir: &Path, state: &mut Value) -> Result<()> {
    let e = endpoint(state)?;
    let answer = json_call(
        &e,
        Some(bound_node(state)?),
        Operation::Lookup {
            dispatch_id: dispatch_id(state)?.into(),
        },
    );
    match answer {
        Ok(value) => observe(state, value)?,
        Err(error) => {
            state["last_error"] = json!(error.to_string());
            save(dir, state)?;
            return Err(error);
        }
    }
    save(dir, state)
}
fn start_unknown(state: &Value, cause: impl std::fmt::Display) -> optimization_job_api::Error {
    let id = state["id"].as_str().unwrap_or("");
    coded(
        "start_unknown",
        format!(
            "fleet job {id} has an uncertain dispatch on its pinned node: {cause}; use fleet reconcile {id}"
        ),
    )
}
/// After a request may have reached the node: the dispatch is uncertain.
fn uncertain(dir: &Path, state: &mut Value, cause: impl std::fmt::Display) -> Result<()> {
    state["phase"] = json!("unknown");
    state["last_error"] = json!(cause.to_string());
    save(dir, state)?;
    Err(start_unknown(state, cause))
}
/// The caller's view of a saved dispatch: a refused dispatch fails with the
/// node's code, an uncertain one with `start_unknown`.
fn settled(state: &Value) -> Result<()> {
    match state["phase"].as_str() {
        Some("rejected") => {
            let error = &state["remote"]["dispatch"]["error"];
            Err(transport::refusal(&Failure {
                code: error["code"].as_str().unwrap_or("runner_error").into(),
                message: error["message"]
                    .as_str()
                    .unwrap_or("the node refused this dispatch")
                    .into(),
                retryable: false,
            }))
        }
        Some("unknown") => Err(start_unknown(state, "the node has not confirmed a start")),
        _ => Ok(()),
    }
}
fn send(dir: &Path, state: &mut Value) -> Result<()> {
    if state["phase"] != "staging" {
        reconcile(dir, state)?;
        return settled(state);
    }
    if state["spec"]["schema_version"] == command::SCHEMA
        && std::env::var_os(command::REFUSE).is_some()
    {
        return Err(coded(
            "unsupported_job_kind",
            "this caller refuses command jobs",
        ));
    }
    let e = endpoint(state)?;
    let id = bound_node(state)?.to_owned();
    let discovery = json_call(&e, Some(&id), Operation::Describe)?;
    if discovery["durable_launcher"]["available"] != true {
        return Err(coded(
            "durable_launcher_unavailable",
            "the bound node no longer has a verified durable launcher",
        ));
    }
    let blobs: Vec<Blob> = serde_json::from_value(state["inputs"].clone())?;
    for blob in &blobs {
        let path = dir.join("inputs").join(blob.index.to_string());
        files::verify(&path, blob.bytes, &blob.sha256)?;
        let reply = transport::call(
            &e,
            Some(&id),
            Operation::Put {
                sha256: blob.sha256.clone(),
                bytes: blob.bytes,
            },
            Some(files::open(&path)?),
        )?;
        if reply.value["sha256"] != blob.sha256 || reply.value["bytes"] != blob.bytes {
            return Err(coded(
                "remote_protocol",
                "upload acknowledgement did not match the staged input",
            ));
        }
    }
    let dispatch = dispatch_id(state)?.to_owned();
    let operation = Operation::Submit {
        dispatch_id: dispatch.clone(),
        identity: state["identity"].as_str().ok_or("missing identity")?.into(),
        spec: state["spec"].clone(),
        inputs: blobs,
        worker: state["worker"].as_object().map(|_| state["worker"].clone()),
    };
    // The intent is saved after SSH started and before the request is written:
    // an error before that point leaves the job staging, with nothing sent.
    let mut sent = false;
    let answer = transport::exchange(&e, Some(&id), operation, None, &mut || {
        state["phase"] = json!("dispatching");
        save(dir, state)?;
        sent = true;
        Ok(())
    });
    match answer {
        Err(error) if !sent => {
            state["last_error"] = json!(error.to_string());
            save(dir, state)?;
            Err(error)
        }
        Err(error) => uncertain(dir, state, error),
        Ok(Ok(mut reply)) => {
            let mut byte = [0];
            if reply.body.read(&mut byte)? != 0 {
                return uncertain(dir, state, "unexpected bytes after control response");
            }
            observe(state, reply.value)?;
            save(dir, state)?;
            settled(state)
        }
        Ok(Err(failure)) => {
            // The helper answered, so it has finished, and its dispatch record,
            // if it wrote one, is final for this request.
            let refusal = transport::refusal(&failure);
            match json_call(
                &e,
                Some(&id),
                Operation::Lookup {
                    dispatch_id: dispatch,
                },
            ) {
                Ok(answer) if answer["found"] == false => {
                    state["phase"] = json!("staging");
                    state["last_error"] = json!(refusal.to_string());
                    save(dir, state)?;
                    Err(refusal)
                }
                Ok(answer) => {
                    observe(state, answer)?;
                    save(dir, state)?;
                    settled(state)?;
                    Err(refusal)
                }
                Err(error) => uncertain(dir, state, format!("{refusal}; lookup: {error}")),
            }
        }
    }
}
fn submit(root: &Path, name: &str, input: &Path) -> Result<Value> {
    let source = fs::canonicalize(input)?;
    let base = source.parent().ok_or("spec has no parent")?;
    let mut bytes = Vec::new();
    files::open(&source)?
        .take(super::MAX_CONTROL as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > super::MAX_CONTROL {
        return Err(coded("invalid_job", "fleet spec exceeds 4 MiB"));
    }
    let mut spec: Value = serde_json::from_slice(&bytes)?;
    match spec["schema_version"].as_str() {
        Some(command::SCHEMA) => {
            if std::env::var_os(command::REFUSE).is_some() {
                return Err(coded(
                    "unsupported_job_kind",
                    "this caller refuses command jobs",
                ));
            }
            let typed: command::Request = serde_json::from_value(spec.clone())?;
            command::validate(&typed)?;
        }
        Some("optimization.job/0.1") => {
            let typed: optimization_job_api::JobSpec = serde_json::from_value(spec.clone())?;
            typed.validate()?;
        }
        _ => {
            return Err(coded(
                "unsupported_job_kind",
                "fleet accepts shared optimization jobs and opt-in commands",
            ));
        }
    }
    if spec.get("inputs").is_none() {
        spec["inputs"] = json!([]);
    }
    let key = spec["request_key"]
        .as_str()
        .ok_or("missing request key")?
        .to_owned();
    let id = digest(key.as_bytes())[..32].to_owned();
    let target = dir(root, &id)?;
    let _guard = lock(&root.join("fleet").join(format!("{id}.lock")))?;
    if target.exists() {
        // The same request again continues or observes the persisted job; it
        // needs neither the node's current state nor the original input files.
        let mut state = read(&target.join("dispatch.json"))?;
        let mut normalized = spec.clone();
        for (index, input) in normalized["inputs"]
            .as_array_mut()
            .ok_or("inputs must be an array")?
            .iter_mut()
            .enumerate()
        {
            input["file"] = json!(format!("remote-input-{index}"));
        }
        if state["spec"] != normalized || state["node_name"] != name {
            return Err(coded(
                "request_key_conflict",
                "fleet key already binds different work or placement; an uncertain attempt cannot move to another node",
            ));
        }
        send(&target, &mut state)?;
        return Ok(state);
    }
    let node = registered(root, name)?;
    let e: Endpoint = serde_json::from_value(node["endpoint"].clone())?;
    let discovery = json_call(&e, node["node_id"].as_str(), Operation::Describe)?;
    let worker = if spec["schema_version"] == "optimization.job/0.1" {
        let name = spec["worker"].as_str().ok_or("missing worker")?;
        let w = discovery["workers"][name].clone();
        if w.is_null() {
            return Err(coded(
                "unknown_worker",
                "worker is not registered on the explicitly selected node",
            ));
        }
        Some(w)
    } else {
        if discovery["capabilities"]["command_jobs"] != true {
            return Err(coded(
                "commands_disabled",
                "the selected node has not enabled trusted commands",
            ));
        }
        None
    };
    if spec["resources"]["cpu_slots"].as_u64().unwrap_or(u64::MAX)
        > discovery["capacity"].as_u64().unwrap_or(0)
    {
        return Err(coded(
            "capacity_exceeded",
            "request exceeds selected node's capacity",
        ));
    }
    let tmp = tempfile::Builder::new()
        .prefix(&format!(".fleet-stage-{id}-"))
        .tempdir_in(root)?;
    fs::create_dir(tmp.path().join("inputs"))?;
    let mut blobs = Vec::new();
    let mut total = 0;
    let inputs = spec["inputs"]
        .as_array_mut()
        .ok_or("inputs must be an array")?;
    for (index, input) in inputs.iter_mut().enumerate() {
        let hash = input["sha256"]
            .as_str()
            .ok_or("missing input SHA-256")?
            .to_owned();
        let path = match input["file"].as_str() {
            Some(file) => files::beneath(base, file)?,
            None => files::blob(root, &hash)?,
        };
        let (bytes, actual) = files::fingerprint(&path, files::MAX_FILE)?;
        if actual != hash
            || input
                .get("bytes")
                .is_some_and(|v| v.as_u64() != Some(bytes))
        {
            return Err(coded(
                "file_transfer_failed",
                "input size/digest differs from the fleet request",
            ));
        }
        total += bytes;
        if total > files::MAX_TOTAL {
            return Err(coded("file_transfer_failed", "fleet inputs exceed 256 MiB"));
        }
        let dest = tmp.path().join("inputs").join(index.to_string());
        files::copy(&mut files::open(&path)?, &dest, bytes, Some((bytes, &hash)))?;
        input["file"] = json!(format!("remote-input-{index}"));
        blobs.push(Blob {
            index,
            bytes,
            sha256: hash,
        });
    }
    let identity = digest(&serde_json::to_vec(
        &json!({"spec":spec,"inputs":blobs,"node":node,"worker":worker}),
    )?);
    if discovery["durable_launcher"]["available"] != true {
        return Err(coded(
            "durable_launcher_unavailable",
            "remote dispatch requires systemd user manager and Linger=yes",
        ));
    }
    let coordinator = {
        let _guard = lock(&root.join("fleet/registry.lock"))?;
        coordinator(root)?
    };
    let dispatch = digest(format!("{coordinator}:{id}").as_bytes());
    let mut state = json!({"schema_version":"execution.fleet.job/0.1","id":id,"request_key":key,"coordinator_id":coordinator,"dispatch_id":dispatch,"node_name":name,"node_id":node["node_id"],"endpoint":e,"identity":identity,"spec":spec,"inputs":blobs,"worker":worker,"phase":"staging","created_at":now(),"collections":{}});
    write_atomic_json(&tmp.path().join("dispatch.json"), &state)?;
    fs::create_dir_all(target.parent().unwrap())?;
    fs::rename(tmp.path(), &target)?;
    fs::File::open(target.parent().unwrap())?.sync_all()?;
    send(&target, &mut state)?;
    Ok(state)
}
fn collect(
    dir: &Path,
    state: &mut Value,
    selection: Selection,
    destination: &Path,
) -> Result<Value> {
    let e = endpoint(state)?;
    let node = bound_node(state)?.to_owned();
    let dispatch = dispatch_id(state)?.to_owned();
    let meta = json_call(
        &e,
        Some(&node),
        Operation::Inspect {
            dispatch_id: dispatch.clone(),
            selection: selection.clone(),
        },
    )?;
    let bytes = meta["bytes"]
        .as_u64()
        .filter(|n| *n <= files::MAX_FILE)
        .ok_or_else(|| coded("remote_protocol", "invalid remote file size"))?;
    let hash = meta["sha256"]
        .as_str()
        .filter(|s| files::hash_ok(s))
        .ok_or_else(|| coded("remote_protocol", "invalid remote file digest"))?
        .to_owned();
    let dest = std::path::absolute(destination)?;
    let collection = digest(&serde_json::to_vec(
        &json!({"selection":selection,"destination":dest}),
    )?);
    if fs::symlink_metadata(&dest).is_ok() {
        let prior = &state["collections"][&collection];
        if prior["sha256"] == hash && prior["bytes"] == bytes {
            files::verify(&dest, bytes, &hash)?;
            state["collections"][&collection]["phase"] = json!("complete");
            save(dir, state)?;
            return Ok(json!({"destination":dest,"bytes":bytes,"sha256":hash,"reused":true}));
        }
        return Err(coded(
            "file_transfer_failed",
            "collection destination exists; choose a new file",
        ));
    }
    state["collections"][&collection] = json!({"selection":selection,"destination":dest,"bytes":bytes,"sha256":hash,"phase":"transferring"});
    save(dir, state)?;
    let result = (|| -> Result<Value> {
        let mut reply = transport::call(
            &e,
            Some(&node),
            Operation::Download {
                dispatch_id: dispatch,
                selection,
                bytes,
                sha256: hash.clone(),
            },
            None,
        )?;
        if reply.value != meta {
            return Err(coded(
                "remote_protocol",
                "download header changed after inspection",
            ));
        }
        let mut result = files::copy(&mut reply.body, &dest, bytes, Some((bytes, &hash)))?;
        result["destination"] = json!(dest);
        Ok(result)
    })();
    match result {
        Ok(value) => {
            state["collections"][&collection]["phase"] = json!("complete");
            save(dir, state)?;
            Ok(value)
        }
        Err(error) => {
            state["collections"][&collection]["phase"] = json!("retryable_transfer");
            state["collections"][&collection]["error"] = json!(error.to_string());
            save(dir, state)?;
            Err(error)
        }
    }
}
pub(crate) fn run(root: &Path, cli: Cli) -> Result<Value> {
    fs::create_dir_all(root.join("fleet"))?;
    match cli {
        Cli::Nodes { command } => match command {
            Nodes::List => optional(&root.join("fleet/nodes.json")),
            Nodes::Add { name, endpoint } => {
                if !optimization_job_api::safe_name(&name) {
                    return Err(coded("invalid_remote_node", "invalid node name"));
                }
                endpoint.validate()?;
                let discovered = json_call(&endpoint, None, Operation::Describe)?;
                let id = discovered["node_id"]
                    .as_str()
                    .filter(|s| files::hash_ok(s))
                    .ok_or_else(|| {
                        coded("remote_protocol", "remote node has no persistent identity")
                    })?;
                let value = json!({"node_id":id,"endpoint":endpoint});
                let _guard = lock(&root.join("fleet/registry.lock"))?;
                let mut nodes = optional(&root.join("fleet/nodes.json"))?;
                if !nodes[&name].is_null() && nodes[&name] != value {
                    return Err(coded(
                        "invalid_remote_node",
                        "node name already pins another endpoint or identity; use a new name",
                    ));
                }
                nodes[&name] = value.clone();
                coordinator(root)?;
                write_atomic_json(&root.join("fleet/nodes.json"), &nodes)?;
                Ok(value)
            }
            Nodes::Probe { name } => {
                let n = registered(root, &name)?;
                let e = serde_json::from_value(n["endpoint"].clone())?;
                json_call(&e, n["node_id"].as_str(), Operation::Describe)
            }
        },
        Cli::Submit { node, spec } => submit(root, &node, &spec),
        Cli::List => {
            let path = root.join("fleet/jobs");
            let mut jobs = Vec::new();
            if path.exists() {
                for item in fs::read_dir(path)? {
                    jobs.push(read(&item?.path().join("dispatch.json"))?);
                }
            }
            Ok(json!(jobs))
        }
        Cli::Get { id } => read(&dir(root, &id)?.join("dispatch.json")),
        other => {
            let id = match &other {
                Cli::Resume { id }
                | Cli::Reconcile { id }
                | Cli::Cancel { id, .. }
                | Cli::Execution { id }
                | Cli::Repair { id }
                | Cli::Collect { id, .. } => id,
                _ => unreachable!(),
            };
            let target = dir(root, id)?;
            let _guard = lock(&root.join("fleet").join(format!("{id}.lock")))?;
            let mut state = read(&target.join("dispatch.json"))?;
            match other {
                Cli::Resume { .. } => send(&target, &mut state)?,
                Cli::Reconcile { .. } => reconcile(&target, &mut state)?,
                Cli::Cancel { now, .. } => {
                    let answer = json_call(
                        &endpoint(&state)?,
                        Some(bound_node(&state)?),
                        Operation::Cancel {
                            dispatch_id: dispatch_id(&state)?.into(),
                            immediate: now,
                        },
                    )?;
                    observe(&mut state, answer)?;
                    save(&target, &mut state)?;
                }
                Cli::Repair { .. } => {
                    let answer = json_call(
                        &endpoint(&state)?,
                        Some(bound_node(&state)?),
                        Operation::Repair {
                            dispatch_id: dispatch_id(&state)?.into(),
                        },
                    )?;
                    observe(&mut state, answer)?;
                    save(&target, &mut state)?;
                }
                Cli::Execution { .. } => {
                    return json_call(
                        &endpoint(&state)?,
                        Some(bound_node(&state)?),
                        Operation::Execution {
                            dispatch_id: dispatch_id(&state)?.into(),
                        },
                    );
                }
                Cli::Collect {
                    kind,
                    name,
                    destination,
                    ..
                } => {
                    let selection = match (kind, name) {
                        (FileKind::Native, None) => Selection::Native,
                        (FileKind::Execution, None) => Selection::Execution,
                        (FileKind::Output, Some(name)) => Selection::Output { name },
                        (FileKind::Artifact, Some(name)) => Selection::Artifact { name },
                        _ => {
                            return Err(coded(
                                "invalid_command",
                                "output/artifact kinds require --name; native/execution must omit it",
                            ));
                        }
                    };
                    return collect(&target, &mut state, selection, &destination);
                }
                _ => unreachable!(),
            }
            Ok(state)
        }
    }
}
