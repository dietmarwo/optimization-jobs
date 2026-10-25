use crate::{boot, capacity, check_systemd, optional, read};
use optimization_job_api::{
    Result, coded,
    process::bounded_command,
    storage::{digest, lock, write_atomic_json},
};
use serde_json::{Value, json};
use std::{fs, io::Read, path::Path, time::Duration};

pub(crate) fn fresh_id() -> Result<String> {
    let mut bytes = [0u8; 32];
    fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(digest(&bytes))
}
pub(crate) fn identity(root: &Path, initialize: bool) -> Result<Value> {
    capacity(root)?;
    let _guard = if initialize {
        Some(lock(&root.join("registry.lock"))?)
    } else {
        None
    };
    let mut node = read(&root.join("node.json"))?;
    if node["node_id"].is_null() && initialize {
        node["node_id"] = json!(fresh_id()?);
        write_atomic_json(&root.join("node.json"), &node)?;
    }
    let id = node["node_id"]
        .as_str()
        .filter(|s| crate::files::hash_ok(s))
        .ok_or_else(|| {
            coded(
                "node_identity_unavailable",
                "initialize an existing node's persistent identity with node identity --init",
            )
        })?;
    Ok(
        json!({"schema_version":"execution.node.identity/0.1","node_id":id,"root":fs::canonicalize(root)?}),
    )
}
/// Detached remote work requires both the manager and lingering, not merely an
/// ssh session that happens to have a user bus. No fallback to nohup/foreground.
pub(crate) fn durable() -> Value {
    let manager = check_systemd().is_ok();
    let uid = unsafe { libc::geteuid() }.to_string();
    let linger = bounded_command(
        &[
            "loginctl".into(),
            "show-user".into(),
            uid,
            "--property=Linger".into(),
            "--value".into(),
        ],
        vec![],
        Duration::from_secs(5),
        4096,
    )
    .is_ok_and(|(status, out, _)| {
        status.success() && String::from_utf8_lossy(&out).trim() == "yes"
    });
    json!({"backend":"systemd_user","manager_available":manager,"linger":linger,"available":manager && linger})
}
pub(crate) fn describe(root: &Path) -> Result<Value> {
    let id = identity(root, false)?;
    let registry = optional(&root.join("workers.json"))?;
    let workers:serde_json::Map<String,Value>=registry.as_object().ok_or("invalid worker registry")?.iter().map(|(id,w)|(id.clone(),json!({"digest":w["digest"],"protocol":w["description"]["protocol"],"profiles":w["description"]["profiles"],"build":w["description"]["build"]}))).collect();
    Ok(
        json!({"schema_version":"execution.node/0.1","protocol":super::PROTOCOL,"node_id":id["node_id"],"root":id["root"],"boot_id":boot()?,"capacity":capacity(root)?,"capabilities":crate::execution::capabilities(root)?,"workers":workers,"durable_launcher":durable()}),
    )
}
