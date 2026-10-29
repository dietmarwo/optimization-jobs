//! The job envelope `optimization.job/0.1`: its types and rules, its input
//! files, and the [`Request`] that also accepts the legacy format (the
//! guide's section [Envelope](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#envelope)).
use crate::{Result, coded, legacy, storage};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs,
    path::{Component, Path},
};

/// The schema version of the job envelope, the value of
/// [`JobSpec::schema_version`].
pub const SCHEMA: &str = "optimization.job/0.1";
/// The worker protocol of this build. It adds the result contract 0.2
/// (evidence, refutations, objective bounds and the infeasibility and
/// certified claims) to the process protocol of 0.1.
pub const PROTOCOL: &str = "optimization.worker/0.2";
/// Worker protocols the runner accepts. Every 0.1 result record is a valid
/// 0.2 record, so 0.1 workers keep working; a 0.1 runner rejects 0.2 workers
/// at registration instead of failing on their journals.
pub const PROTOCOLS: [&str; 2] = ["optimization.worker/0.1", PROTOCOL];
/// True if the runner accepts a worker that describes itself with `protocol`.
pub fn protocol_supported(protocol: &Value) -> bool {
    protocol.as_str().is_some_and(|p| PROTOCOLS.contains(&p))
}
/// The largest input file, 64 MiB.
pub const MAX_INPUT_BYTES: u64 = 64 * 1024 * 1024;

/// The CPU slots of a job: `outer_workers * inner_threads <= cpu_slots <= 1024`
/// (the guide's section [Eight CPU slots](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#eight-cpu-slots)).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Resources {
    /// Slots the runner reserves for the whole attempt.
    pub cpu_slots: usize,
    /// Tasks solved at the same time.
    pub outer_workers: usize,
    /// Numerical threads of each task.
    pub inner_threads: usize,
}
/// The time limits of a job.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    /// Execution time after which the worker stops its tasks: positive and
    /// at most one year (31,536,000 seconds).
    pub wall_time_seconds: f64,
    /// Time between the wall-time deadline and killing the worker, 0 to
    /// 86,400 seconds.
    pub grace_seconds: f64,
}
/// A named input file of a job: an LP model, or data a registered model reads.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Input {
    /// The unique [safe name](safe_name) the worker looks the file up by
    /// ([`JobSpec::input_bytes`]).
    pub name: String,
    /// The path, relative to the submitted specification; `inputs/NAME` in
    /// an attempt directory.
    pub file: String,
    /// The lowercase hexadecimal SHA-256 of the file, checked on every read.
    pub sha256: String,
}
/// A job envelope `optimization.job/0.1` (the guide's section [Envelope](https://github.com/dietmarwo/optimization-jobs/blob/main/docs/job-api.md#envelope)).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct JobSpec {
    /// Exactly [`SCHEMA`].
    pub schema_version: String,
    /// The caller-chosen idempotency key, 1 to 200 bytes. [`JobSpec::digest`]
    /// excludes it.
    pub request_key: String,
    /// The ID of the registered worker that runs the job.
    pub worker: String,
    /// The worker profile the payload follows, such as `lp-ip.solve/1`.
    pub payload_schema: String,
    /// The profile's options (model, algorithm and budget) as a JSON object.
    /// The worker rejects unknown fields.
    pub payload: Value,
    /// The CPU slots of the job.
    pub resources: Resources,
    /// The time limits of the job.
    pub limits: Limits,
    /// Input files, at most 16; empty for a model without data.
    #[serde(default)]
    pub inputs: Vec<Input>,
    /// Filled by the worker during validation, never inferred by the runner.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub task_count: Option<usize>,
}
/// True for a plain name of 1 to 80 bytes of ASCII letters, digits, `-`, `_`
/// and `.`, other than `.` and `..`. Worker IDs and the names of inputs,
/// artifacts and work counters are safe names.
pub fn safe_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 80
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
        && s != "."
        && s != ".."
}
impl JobSpec {
    /// Checks the envelope's rules without reading a file: the schema
    /// version, the request key and worker name, `outer_workers *
    /// inner_threads <= cpu_slots <= 1024`, the time limits, at most 1,000,000
    /// tasks and 16 inputs, and inputs with unique names, contained relative
    /// paths and lowercase SHA-256 values.
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != SCHEMA
            || self.request_key.is_empty()
            || self.request_key.len() > 200
            || !safe_name(&self.worker)
            || self.payload_schema.is_empty()
            || !self.payload.is_object()
        {
            return Err("invalid job envelope, schema, request_key or worker".into());
        }
        let r = &self.resources;
        if r.cpu_slots == 0
            || r.cpu_slots > 1024
            || r.outer_workers == 0
            || r.inner_threads == 0
            || r.outer_workers
                .checked_mul(r.inner_threads)
                .is_none_or(|n| n > r.cpu_slots)
        {
            return Err(
                "resources require 1 <= outer_workers * inner_threads <= cpu_slots <= 1024".into(),
            );
        }
        if !self.limits.wall_time_seconds.is_finite()
            || !(0.0..=31_536_000.0).contains(&self.limits.wall_time_seconds)
            || self.limits.wall_time_seconds == 0.0
            || !self.limits.grace_seconds.is_finite()
            || !(0.0..=86400.0).contains(&self.limits.grace_seconds)
        {
            return Err("invalid wall time or grace".into());
        }
        if self.task_count.is_some_and(|n| n == 0 || n > 1_000_000) || self.inputs.len() > 16 {
            return Err("invalid task/input count".into());
        }
        let mut names = BTreeSet::new();
        for i in &self.inputs {
            if !safe_name(&i.name)
                || !names.insert(&i.name)
                || i.sha256.len() != 64
                || !i
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                || i.file.is_empty()
                || Path::new(&i.file)
                    .components()
                    .any(|c| !matches!(c, Component::Normal(_) | Component::CurDir))
                || !Path::new(&i.file)
                    .components()
                    .any(|c| matches!(c, Component::Normal(_)))
            {
                return Err("input requires unique safe name, relative contained path and lowercase SHA-256".into());
            }
        }
        Ok(())
    }
    /// The `spec_digest` that identifies the experiment: the SHA-256 of the
    /// specification without its request key.
    pub fn digest(&self) -> Result<String> {
        let mut v = serde_json::to_value(self)?;
        v.as_object_mut().unwrap().remove("request_key");
        Ok(storage::digest(&serde_json::to_vec(&v)?))
    }
    /// The bytes of the input named `name`, read relative to `base` and
    /// checked by [`checked_input`].
    pub fn input_bytes(&self, base: &Path, name: &str) -> Result<Vec<u8>> {
        let input = self
            .inputs
            .iter()
            .find(|i| i.name == name)
            .ok_or("missing model input")?;
        checked_input(base, input)
    }
}
/// Reads `input` relative to `base`. Fails if its path leaves `base`, also
/// through a symbolic link, if the file exceeds [`MAX_INPUT_BYTES`], or if its
/// SHA-256 differs from `input.sha256`.
pub fn checked_input(base: &Path, input: &Input) -> Result<Vec<u8>> {
    let base = fs::canonicalize(base)?;
    let path = fs::canonicalize(base.join(&input.file))?;
    if !path.starts_with(&base) || !path.is_file() || fs::metadata(&path)?.len() > MAX_INPUT_BYTES {
        return Err("input escapes directory or exceeds 64 MiB".into());
    }
    // The bounded read also covers a file that grows after the metadata check.
    use std::io::Read;
    let mut bytes = Vec::new();
    fs::File::open(path)?
        .take(MAX_INPUT_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_INPUT_BYTES || storage::digest(&bytes) != input.sha256 {
        return Err("input SHA-256 mismatch or oversized input".into());
    }
    Ok(bytes)
}
/// Copies the inputs of `s` from `from` into `to/inputs`, each checked by
/// [`checked_input`] and synced, and points each input's `file` at its copy.
pub fn stage_inputs(s: &mut JobSpec, from: &Path, to: &Path) -> Result<()> {
    fs::create_dir_all(to.join("inputs"))?;
    for i in &mut s.inputs {
        let bytes = checked_input(from, i)?;
        i.file = format!("inputs/{}", i.name);
        let path = to.join(&i.file);
        fs::write(&path, bytes)?;
        fs::File::open(path)?.sync_all()?;
    }
    fs::File::open(to.join("inputs"))?.sync_all()?;
    Ok(())
}
/// A submitted job, in the current envelope or in the legacy format.
#[derive(Clone, Debug, Serialize)]
#[serde(untagged)]
pub enum Request {
    /// An `fcmaes.job/0.1` job, resolved by [`legacy::JobSpec::resolve`].
    Legacy(legacy::JobSpec),
    /// An `optimization.job/0.1` job, checked by [`JobSpec::validate`].
    Job(JobSpec),
}
impl Request {
    /// Parses and validates a submitted job; every failure is `invalid_job`.
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        Self::parse_unchecked(bytes).map_err(|e| coded("invalid_job", e.to_string()))
    }
    fn parse_unchecked(bytes: &[u8]) -> Result<Self> {
        let v: Value = serde_json::from_slice(bytes)?;
        match v["schema_version"].as_str() {
            Some("fcmaes.job/0.1") => Ok(Self::Legacy(
                serde_json::from_value::<legacy::JobSpec>(v)?.resolve()?,
            )),
            Some(SCHEMA) => {
                let s: JobSpec = serde_json::from_value(v)?;
                s.validate()?;
                Ok(Self::Job(s))
            }
            _ => Err("unsupported job schema".into()),
        }
    }
    /// The caller's idempotency key.
    pub fn request_key(&self) -> &str {
        match self {
            Self::Legacy(s) => &s.request_key,
            Self::Job(s) => &s.request_key,
        }
    }
    /// The worker ID; `native` for a legacy job.
    pub fn worker(&self) -> &str {
        match self {
            Self::Legacy(_) => "native",
            Self::Job(s) => &s.worker,
        }
    }
    /// The CPU slots the job reserves: `cpu_slots`, or `execution.workers`
    /// for a legacy job.
    pub fn slots(&self) -> usize {
        match self {
            Self::Legacy(s) => s.execution.workers,
            Self::Job(s) => s.resources.cpu_slots,
        }
    }
    /// The wall-time limit in seconds.
    pub fn wall(&self) -> f64 {
        match self {
            Self::Legacy(s) => s.budget.wall_time_seconds,
            Self::Job(s) => s.limits.wall_time_seconds,
        }
    }
    /// The grace period after the wall-time limit, in seconds.
    pub fn grace(&self) -> f64 {
        match self {
            Self::Legacy(s) => s.budget.grace_seconds,
            Self::Job(s) => s.limits.grace_seconds,
        }
    }
    /// The job's `spec_digest`, which excludes the request key.
    pub fn digest(&self) -> Result<String> {
        match self {
            Self::Legacy(s) => s.digest(),
            Self::Job(s) => s.digest(),
        }
    }
    /// Writes the job as JSON to `path`, atomically.
    pub fn save(&self, path: &Path) -> Result<()> {
        Ok(storage::write_atomic_json(path, self)?)
    }
}
