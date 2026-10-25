//! Opt-in trusted local commands; deliberately separate from solver contracts.
use crate::{
    boot, capacity, check_systemd,
    execution::{self, Finalized, NativeResult, State},
    files, now, optional, read, state_write,
    supervision::{Budget, Containment, Observation},
};
use optimization_job_api::{
    Result, coded,
    storage::{digest, lock, write_atomic_json},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    os::unix::{fs::PermissionsExt, process::CommandExt},
    path::{Path, PathBuf},
    process::Command,
    time::Duration,
};

pub(crate) const SCHEMA: &str = "execution.command/0.1";
/// Absolute executables are hashed in place, not copied, so they are not
/// bound by the transfer limit.
const MAX_EXECUTABLE: u64 = 1 << 30;
const RESULT_SCHEMA: &str = "execution.command.result/0.1";
const RESULT_FILE: &str = "command-result.json";
const SEALED: &str = ".command-outputs";
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Resources {
    cpu_slots: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Limits {
    wall_seconds: f64,
    grace_seconds: f64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    path: String,
    sha256: String,
    bytes: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    file: Option<String>,
    #[serde(default)]
    executable: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Output {
    name: String,
    path: String,
    max_bytes: u64,
    required: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    schema_version: String,
    request_key: String,
    argv: Vec<String>,
    env: BTreeMap<String, String>,
    resources: Resources,
    limits: Limits,
    replay: String,
    inputs: Vec<Input>,
    outputs: Vec<Output>,
}
fn invalid(message: impl Into<String>) -> optimization_job_api::Error {
    coded("invalid_command_spec", message)
}
pub(crate) fn enabled(root: &Path) -> Result<bool> {
    Ok(optional(&root.join("node.json"))?["allow_commands"] == true)
}
pub(crate) fn validate(s: &Request) -> Result<()> {
    if s.schema_version != SCHEMA || s.replay != "never" {
        return Err(invalid("expected execution.command/0.1 with replay=never"));
    }
    if s.request_key.is_empty() || s.request_key.len() > 200 || s.request_key.contains('\0') {
        return Err(invalid("request_key must be 1..200 bytes without NUL"));
    }
    if s.argv.is_empty()
        || s.argv.len() > 256
        || s.argv[0].is_empty()
        || s.argv.iter().any(|a| a.len() > 16384 || a.contains('\0'))
        || s.argv.iter().map(String::len).sum::<usize>() > 65536
    {
        return Err(invalid(
            "argv must contain an executable and at most 64 KiB of literal arguments",
        ));
    }
    if s.env.len() > 128
        || s.env.iter().any(|(k, v)| {
            k.is_empty()
                || k.len() > 128
                || !k.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
                || k.as_bytes()[0].is_ascii_digit()
                || v.len() > 16384
                || v.contains('\0')
        })
        || s.env.values().map(String::len).sum::<usize>() > 65536
    {
        return Err(invalid("invalid or oversized explicit environment"));
    }
    if !(1..=1024).contains(&s.resources.cpu_slots)
        || !s.limits.wall_seconds.is_finite()
        || !(0.001..=604800.0).contains(&s.limits.wall_seconds)
        || !s.limits.grace_seconds.is_finite()
        || !(0.0..=3600.0).contains(&s.limits.grace_seconds)
    {
        return Err(invalid(
            "cpu_slots 1..1024; wall_seconds 0.001..604800; grace_seconds 0..3600",
        ));
    }
    if s.inputs.len() + s.outputs.len() > 128 {
        return Err(invalid("at most 128 inputs and outputs combined"));
    }
    let mut paths = Vec::new();
    let mut names = BTreeSet::new();
    let mut total = 0u64;
    for i in &s.inputs {
        files::relative(&i.path)?;
        if let Some(file) = &i.file {
            files::relative(file)?;
        }
        if !files::hash_ok(&i.sha256) || i.bytes > files::MAX_FILE {
            return Err(invalid("input must declare SHA-256 and at most 64 MiB"));
        }
        total += i.bytes;
        paths.push(i.path.as_str());
    }
    for o in &s.outputs {
        files::relative(&o.path)?;
        if o.name.is_empty()
            || o.name.len() > 100
            || !o
                .name
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
            || !names.insert(&o.name)
            || o.max_bytes > files::MAX_FILE
        {
            return Err(invalid("invalid/duplicate output name or byte limit"));
        }
        total += o.max_bytes;
        paths.push(o.path.as_str());
    }
    if total > files::MAX_TOTAL {
        return Err(invalid("declared inputs and output limits exceed 256 MiB"));
    }
    // Every directory prefix: `a`, `a.txt` and `a/b` do not sort as neighbours.
    let mut declared = BTreeSet::new();
    for path in &paths {
        if !declared.insert(*path) {
            return Err(invalid("input/output paths must not overlap"));
        }
    }
    for path in &paths {
        if path
            .match_indices('/')
            .any(|(at, _)| declared.contains(&path[..at]))
        {
            return Err(invalid("input/output paths must not overlap"));
        }
    }
    Ok(())
}
fn executable(s: &Request) -> Result<Value> {
    if let Some(path) = s.argv[0].strip_prefix("./") {
        if !s.inputs.iter().any(|i| i.path == path && i.executable) {
            return Err(invalid(
                "relative executable must be a declared executable input (./path)",
            ));
        }
        return Ok(json!({"input":path}));
    }
    if !Path::new(&s.argv[0]).is_absolute() {
        return Err(invalid(
            "executable must be absolute, or ./path for a declared executable input",
        ));
    }
    let path = fs::canonicalize(&s.argv[0])?;
    let metadata = fs::metadata(&path)?;
    if metadata.permissions().mode() & 0o111 == 0 {
        return Err(invalid("executable has no execute permission"));
    }
    if metadata.len() > MAX_EXECUTABLE {
        return Err(invalid("executable exceeds 1 GiB"));
    }
    let (bytes, hash) = files::fingerprint(&path, MAX_EXECUTABLE)?;
    Ok(json!({"path":path,"bytes":bytes,"sha256":hash}))
}
fn identity(s: &Request, executable: &Value) -> Result<String> {
    Ok(digest(&serde_json::to_vec(
        &json!({"spec":s,"executable":executable}),
    )?))
}
/// Set in processes started by the MCP server, whose submissions stay
/// optimization-only whatever file reaches the runner.
pub(crate) const REFUSE: &str = "OPTIMIZATION_RUN_REFUSE_COMMANDS";
pub(crate) fn refused() -> Result<()> {
    if std::env::var_os(REFUSE).is_some() {
        return Err(coded(
            "unsupported_job_kind",
            "command jobs are CLI-only; the MCP server does not validate or submit them",
        ));
    }
    Ok(())
}
fn staged(root: &Path, input: &Path) -> Result<(Request, Value, tempfile::TempDir, Value)> {
    refused()?;
    capacity(root)?;
    if !enabled(root)? {
        return Err(coded(
            "commands_disabled",
            "enable trusted local commands with node commands --enable",
        ));
    }
    let mut bytes = Vec::new();
    use std::io::Read;
    files::open(input)?
        .take(1_048_577)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 1_048_576 {
        return Err(invalid("command request exceeds 1 MiB"));
    }
    let mut s: Request = serde_json::from_slice(&bytes).map_err(|e| invalid(e.to_string()))?;
    validate(&s)?;
    if s.resources.cpu_slots as u64 > capacity(root)? {
        return Err(coded(
            "capacity_exceeded",
            "command requires more slots than node capacity",
        ));
    }
    let submitted = serde_json::to_value(&s)?;
    let exe = executable(&s)?;
    // `file` is relative to the request's directory, also for `--spec NAME`.
    let base = fs::canonicalize(
        std::path::absolute(input)?
            .parent()
            .ok_or_else(|| invalid("request file has no directory"))?,
    )?;
    let tmp = tempfile::tempdir_in(root)?;
    for i in &mut s.inputs {
        let source = match &i.file {
            Some(file) => files::beneath(&base, file)?,
            None => files::blob(root, &i.sha256)?,
        };
        let dest = files::beneath(tmp.path(), &i.path)?;
        fs::create_dir_all(dest.parent().unwrap())?;
        files::copy(
            &mut files::open(&source)?,
            &dest,
            i.bytes,
            Some((i.bytes, &i.sha256)),
        )?;
        fs::set_permissions(
            &dest,
            fs::Permissions::from_mode(if i.executable { 0o700 } else { 0o600 }),
        )?;
        fs::File::open(&dest)?.sync_all()?;
        i.file = None;
    }
    Ok((s, exe, tmp, submitted))
}
pub(crate) fn check(root: &Path, input: &Path) -> Result<Value> {
    let (s, exe, _, _) = staged(root, input)?;
    Ok(json!({"valid":true,"resolved":s,"executable":exe,"identity":identity(&s,&exe)?}))
}
pub(crate) fn prepare(
    root: &Path,
    input: &Path,
    dest: Option<PathBuf>,
    detached: bool,
) -> Result<(String, bool)> {
    let (s, exe, tmp, submitted) = staged(root, input)?;
    let id = digest(s.request_key.as_bytes())[..32].to_owned();
    let identity = identity(&s, &exe)?;
    let _guard = lock(&root.join("registry.lock"))?;
    let mut requests = optional(&root.join("requests.json"))?;
    if !requests[&id].is_null() {
        if requests[&id]["identity"] != identity {
            return Err(coded(
                "request_key_conflict",
                "request key already names another command, input, executable or optimization job; choose a new key",
            ));
        }
        return Ok((id, false));
    }
    if detached {
        check_systemd()?;
    }
    let dir = dest.unwrap_or_else(|| root.join("jobs").join(&id));
    let dir = std::path::absolute(dir)?;
    if fs::symlink_metadata(&dir).is_ok() {
        return Err(invalid("output already exists; refusing overwrite"));
    }
    let parent = dir
        .parent()
        .ok_or_else(|| invalid("output has no parent"))?;
    fs::create_dir_all(parent)?;
    let pending = tempfile::Builder::new()
        .prefix(".command-")
        .tempdir_in(parent)?;
    let stage = pending.path();
    fs::create_dir(stage.join("work"))?;
    for i in &s.inputs {
        let dest = files::beneath(&stage.join("work"), &i.path)?;
        fs::create_dir_all(dest.parent().unwrap())?;
        files::copy(
            &mut files::open(&tmp.path().join(&i.path))?,
            &dest,
            i.bytes,
            Some((i.bytes, &i.sha256)),
        )?;
        fs::set_permissions(
            &dest,
            fs::Permissions::from_mode(if i.executable { 0o700 } else { 0o600 }),
        )?;
        fs::File::open(&dest)?.sync_all()?;
    }
    fs::create_dir(stage.join(SEALED))?;
    for o in &s.outputs {
        fs::create_dir_all(
            files::beneath(&stage.join("work"), &o.path)?
                .parent()
                .unwrap(),
        )?;
    }
    let unit = if detached {
        Some(format!("optimization-job-{id}.service"))
    } else {
        None
    };
    write_atomic_json(&stage.join("submitted.json"), &submitted)?;
    write_atomic_json(&stage.join("resolved.json"), &s)?;
    write_atomic_json(
        &stage.join("provenance.json"),
        &json!({"identity":identity,"executable":exe,"unit":unit,"boot_id":boot()?,"attempt_id":id}),
    )?;
    state_write(
        &stage.join("job.json"),
        &json!({"id":id,"kind":"command","state":"submitted","submitted_at":now(),"unit":unit,"boot_id":boot()?}),
    )?;
    fs::File::open(stage)?.sync_all()?;
    // Registry lock serializes request IDs. Explicit output directories must be
    // absent; a directory created by another caller is never replaced.
    fs::create_dir(&dir)?;
    if let Err(e) = fs::rename(stage, &dir) {
        let _ = fs::remove_dir(&dir);
        return Err(e.into());
    }
    fs::File::open(parent)?.sync_all()?;
    let dir = fs::canonicalize(dir)?;
    requests[&id] = json!({"identity":identity,"directory":dir});
    write_atomic_json(&root.join("requests.json"), &requests)?;
    Ok((id, true))
}
pub(crate) struct Adapter {
    spec: Request,
    executable: Value,
}
pub(crate) struct Outcome {
    state: State,
    process: Option<Value>,
    collect: bool,
}
impl Adapter {
    pub(crate) fn load(dir: &Path) -> Result<Self> {
        let spec: Request = serde_json::from_value(read(&dir.join("resolved.json"))?)?;
        validate(&spec)?;
        let provenance = read(&dir.join("provenance.json"))?;
        if identity(&spec, &provenance["executable"])? != provenance["identity"] {
            return Err(invalid("staged command identity mismatch"));
        }
        Ok(Self {
            spec,
            executable: provenance["executable"].clone(),
        })
    }
}
impl execution::Adapter for Adapter {
    type Outcome = Outcome;
    fn kind(&self) -> &'static str {
        "command"
    }
    fn signal_on_stop(&self) -> bool {
        true
    }
    fn budget(&self) -> Budget {
        Budget {
            cpu_slots: self.spec.resources.cpu_slots,
            wall: Duration::from_secs_f64(self.spec.limits.wall_seconds),
            grace: Duration::from_secs_f64(self.spec.limits.grace_seconds),
        }
    }
    fn command(&self, dir: &Path) -> Result<Command> {
        if executable(&self.spec)? != self.executable {
            return Err(invalid("executable changed since staging"));
        }
        let work = dir.join("work");
        for i in &self.spec.inputs {
            files::verify(&files::beneath(&work, &i.path)?, i.bytes, &i.sha256)?;
        }
        // Run the verified file, but under the submitted argv[0]: multi-call
        // programs such as unxz or clang++ choose their behavior by it.
        let program = self.executable["path"]
            .as_str()
            .unwrap_or(&self.spec.argv[0]);
        let mut command = Command::new(program);
        command
            .arg0(&self.spec.argv[0])
            .args(&self.spec.argv[1..])
            .current_dir(work)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("OMP_NUM_THREADS", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("MKL_NUM_THREADS", "1")
            .envs(&self.spec.env);
        Ok(command)
    }
    fn completed(&self, _: &Path, observed: &Observation) -> Result<Outcome> {
        let state = if let Some(reason) = observed.stop_reason {
            reason.state()
        } else if observed.process.as_ref().is_some_and(|p| p.code == Some(0)) {
            State::Completed
        } else {
            State::Failed
        };
        Ok(Outcome {
            state,
            process: observed.process.as_ref().map(|p| json!(p)),
            collect: observed.containment == Containment::Stopped,
        })
    }
    fn cancelled_before_start(&self) -> Outcome {
        Outcome {
            state: State::Cancelled,
            process: None,
            collect: false,
        }
    }
    fn failed(&self) -> Outcome {
        Outcome {
            state: State::Failed,
            process: None,
            collect: false,
        }
    }
    fn finalize(
        &self,
        dir: &Path,
        mut outcome: Outcome,
        elapsed: Option<f64>,
    ) -> Result<Finalized> {
        let mut outputs = serde_json::Map::new();
        let mut errors = Vec::new();
        if outcome.collect {
            // The command can reach this directory; a replaced one is an
            // output error, never a finalization that fails on every repair.
            let sealed = dir.join(SEALED);
            let usable = match fs::symlink_metadata(&sealed) {
                Ok(m) => m.is_dir(),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    fs::create_dir(&sealed).is_ok()
                }
                Err(_) => false,
            };
            for o in &self.spec.outputs {
                let snapshot = (|| -> Result<Option<Value>> {
                    if !usable {
                        return Err(files::fail("sealed output directory is not a directory"));
                    }
                    let source = files::beneath(&dir.join("work"), &o.path)?;
                    if !o.required && !source.try_exists()? {
                        return Ok(None);
                    }
                    let dest = sealed.join(&o.name);
                    // Repair may follow a crash partway through publication.
                    // Reuse a snapshot only after verifying it against the source.
                    let meta = if dest.exists() {
                        let (bytes, hash) = files::fingerprint(&source, o.max_bytes)?;
                        files::verify(&dest, bytes, &hash)?;
                        json!({"bytes":bytes,"sha256":hash})
                    } else {
                        files::copy(&mut files::open(&source)?, &dest, o.max_bytes, None)?
                    };
                    Ok(Some(
                        json!({"path":format!("{SEALED}/{}",o.name),"bytes":meta["bytes"],"sha256":meta["sha256"]}),
                    ))
                })();
                match snapshot {
                    Ok(Some(meta)) => {
                        outputs.insert(o.name.clone(), meta);
                    }
                    Ok(None) => (),
                    Err(e) => errors.push(json!({"name":o.name,"message":e.to_string()})),
                }
            }
        }
        if !errors.is_empty() && outcome.state == State::Completed {
            outcome.state = State::Failed;
        }
        let value = json!({"schema_version":RESULT_SCHEMA,"state":outcome.state,"process":outcome.process,"elapsed_seconds":elapsed,"outputs":outputs,"output_errors":errors,"collection_attempted":outcome.collect});
        let file = dir.join(RESULT_FILE);
        write_atomic_json(&file, &value)?;
        let (bytes, sha256) = files::fingerprint(&file, files::MAX_FILE)?;
        Ok(Finalized {
            state: outcome.state,
            native_result: Some(NativeResult {
                file: RESULT_FILE.into(),
                schema_version: json!(RESULT_SCHEMA),
                bytes,
                sha256,
            }),
        })
    }
}
pub(crate) fn repair(dir: &Path, started: bool) -> Result<()> {
    let adapter = Adapter::load(dir)?;
    execution::finish(
        dir,
        &adapter,
        Outcome {
            state: State::Interrupted,
            process: None,
            collect: started,
        },
        None,
        Observation {
            containment: if started {
                Containment::Stopped
            } else {
                Containment::NotStarted
            },
            ..Observation::default()
        },
        "repair",
    )
}
pub(crate) fn result(dir: &Path) -> Result<Value> {
    let record = execution::record(dir)?;
    let attachment = &record["native_result"];
    if record["kind"] != "command"
        || attachment["file"] != RESULT_FILE
        || attachment["schema_version"] != RESULT_SCHEMA
    {
        return Err(invalid("not a command result attachment"));
    }
    files::verify(
        &dir.join(RESULT_FILE),
        attachment["bytes"].as_u64().ok_or("missing result size")?,
        attachment["sha256"]
            .as_str()
            .ok_or("missing result digest")?,
    )?;
    read(&dir.join(RESULT_FILE))
}
pub(crate) fn collect(dir: &Path, name: &str, dest: &Path) -> Result<Value> {
    let result = result(dir)?;
    let meta = &result["outputs"][name];
    if meta.is_null() {
        return Err(coded(
            "unknown_artifact",
            "no verified command output with this name",
        ));
    }
    // The published attachment is checked above. Still constrain the name and
    // path rather than trusting a path in arbitrary JSON.
    if name.is_empty()
        || !name
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        || meta["path"] != format!("{SEALED}/{name}")
    {
        return Err(invalid("invalid sealed output path"));
    }
    let bytes = meta["bytes"].as_u64().ok_or("missing output size")?;
    let hash = meta["sha256"].as_str().ok_or("missing output digest")?;
    files::copy(
        &mut files::open(&files::beneath(&dir.join(SEALED), name)?)?,
        dest,
        bytes,
        Some((bytes, hash)),
    )
}
