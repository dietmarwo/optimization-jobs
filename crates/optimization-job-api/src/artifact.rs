//! Artifacts: files of a job attempt that agents may read through the runner
//! (`jobs artifact`, MCP `get_artifact`), during the run and after it.
//!
//! `results` (the result journal) is built in. A worker adds its own files,
//! such as an evaluation log or a warm-start snapshot, by declaring them with
//! [`declare`] before it first writes them. Declarations are checked records
//! in `artifacts.jsonl` of the attempt directory, so workers in any language
//! can write them, and a runner that predates them simply ignores the file.
//! The final manifest lists every declared file that exists, and
//! `runner.artifact_index` records its format, size and SHA-256 when the
//! attempt is sealed.
use crate::{Result, coded, safe_name, storage};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::{
    collections::BTreeSet,
    fs,
    io::{self, BufRead, Read},
    path::Path,
};

/// The declarations of an attempt: checked records, version 1.
pub const DECLARATIONS: &str = "artifacts.jsonl";
const LOCK: &str = "artifacts.lock";
/// The built-in artifact: the result journal `results.jsonl`.
pub const RESULTS: &str = "results";
/// Artifact formats.
///
/// - `records`: an append-only journal of checked records, written with
///   [`storage::append_checked`] (any record version). Readable while the
///   job runs (complete records only) and in pages of records.
/// - `json`: one JSON document, replaced atomically with
///   [`storage::write_atomic_json`]. Read whole.
pub const FORMATS: [&str; 2] = ["records", "json"];
/// Files of the runner and the SDK in an attempt directory. No artifact may
/// use them; nor a name that starts with `.` or ends with `.lock` or `.tmp`.
pub const RESERVED: [&str; 22] = [
    "artifacts.jsonl",
    "artifacts.lock",
    "cancel.lock",
    "cancel.request",
    "child_finished",
    "containment.unknown",
    "events.jsonl",
    "inputs",
    "job.json",
    "job.lock",
    "provenance.json",
    "request.json",
    "resolved.json",
    "results.jsonl",
    "retries.jsonl",
    "run.json",
    "stderr.log",
    "stdout.log",
    "submitted.json",
    "worker",
    "worker-process.json",
    "worker.lock",
];
/// Declarations per attempt.
pub const MAX_DECLARATIONS: usize = 4096;
/// Bytes of a description.
pub const MAX_DESCRIPTION: usize = 200;
/// What one runner call returns inline: the whole content of an artifact,
/// or the records of one page.
pub const INLINE_CAP: usize = 1 << 20;
/// Records of one page at most.
pub const MAX_PAGE: usize = 10_000;

/// A file a worker declares in its attempt directory.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Declaration {
    /// Name agents use (`jobs artifact ID NAME`); unique in the attempt.
    pub name: String,
    /// File name in the attempt directory, no path.
    pub file: String,
    /// One of [`FORMATS`].
    pub format: String,
    /// The task that writes it, if one does.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub task_id: Option<usize>,
    /// What it holds and what it is for, for agents.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub description: String,
}

impl Declaration {
    /// A journal of checked records (see [`FORMATS`]).
    pub fn records(name: impl Into<String>, file: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            file: file.into(),
            format: "records".into(),
            task_id: None,
            description: String::new(),
        }
    }
    /// A JSON document replaced atomically (see [`FORMATS`]).
    pub fn json(name: impl Into<String>, file: impl Into<String>) -> Self {
        Self {
            format: "json".into(),
            ..Self::records(name, file)
        }
    }
    pub fn task(mut self, task_id: usize) -> Self {
        self.task_id = Some(task_id);
        self
    }
    pub fn describe(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
    /// The rules of a declaration, independent of other declarations.
    pub fn check(&self) -> std::result::Result<(), String> {
        let file = self.file.as_str();
        if !safe_name(&self.name) || self.name == RESULTS {
            return Err(format!("invalid or reserved artifact name {:?}", self.name));
        }
        if !safe_name(file)
            || RESERVED.contains(&file)
            || file.starts_with('.')
            || file.ends_with(".lock")
            || file.ends_with(".tmp")
        {
            return Err(format!(
                "artifact {}: invalid or reserved file name {file:?}",
                self.name
            ));
        }
        if !FORMATS.contains(&self.format.as_str()) {
            return Err(format!(
                "artifact {}: unknown format {:?}",
                self.name, self.format
            ));
        }
        if self.description.len() > MAX_DESCRIPTION || self.description.contains(char::is_control) {
            return Err(format!(
                "artifact {}: description over {MAX_DESCRIPTION} bytes or with control characters",
                self.name
            ));
        }
        Ok(())
    }
}

/// Declares an artifact of the attempt in `dir`, the attempt directory a
/// worker's `prepare` receives as `base`. Declare it in `solve`, before the
/// first write, so agents can read it while the job runs; never in `prepare`,
/// which also runs for validation. Repeating an identical declaration is a
/// no-op; another declaration of the same name or file is an error. Safe to
/// call from concurrent tasks.
pub fn declare(dir: &Path, declaration: &Declaration) -> Result<()> {
    declaration.check()?;
    let _lock = storage::lock(&dir.join(LOCK))?;
    let existing = declarations(dir)?;
    if let Some(old) = existing.iter().find(|d| d.name == declaration.name) {
        if old == declaration {
            return Ok(());
        }
        return Err(format!(
            "artifact {} is already declared differently",
            declaration.name
        )
        .into());
    }
    if existing.iter().any(|d| d.file == declaration.file) {
        return Err(format!("file {} is already declared", declaration.file).into());
    }
    if existing.len() >= MAX_DECLARATIONS {
        return Err(format!("more than {MAX_DECLARATIONS} artifacts declared").into());
    }
    storage::append_checked(&dir.join(DECLARATIONS), 1, declaration)?;
    Ok(())
}

/// The declarations of the attempt in `dir`, in declaration order; none if
/// there are none. A declaration that breaks the rules, or a second
/// declaration of a name or file, makes them all untrusted: an error.
pub fn declarations(dir: &Path) -> Result<Vec<Declaration>> {
    let path = dir.join(DECLARATIONS);
    if !path.exists() {
        return Ok(vec![]);
    }
    let list: Vec<Declaration> =
        storage::read_checked(&path, 1).map_err(|e| format!("{DECLARATIONS}: {e}"))?;
    let (mut names, mut files) = (BTreeSet::new(), BTreeSet::new());
    for d in &list {
        d.check().map_err(|e| format!("{DECLARATIONS}: {e}"))?;
        if !names.insert(&d.name) || !files.insert(&d.file) {
            return Err(format!("{DECLARATIONS}: {} or its file declared twice", d.name).into());
        }
    }
    if list.len() > MAX_DECLARATIONS {
        return Err(format!("{DECLARATIONS}: more than {MAX_DECLARATIONS} artifacts").into());
    }
    Ok(list)
}

/// Every artifact of the attempt: `results` first, then the declarations.
/// Files that do not exist (yet) are included.
pub fn all(dir: &Path) -> Result<Vec<Declaration>> {
    let mut list = vec![results()];
    list.extend(declarations(dir)?);
    Ok(list)
}

fn results() -> Declaration {
    Declaration::records(RESULTS, "results.jsonl")
        .describe("The result journal: one checked record per completed task")
}

/// [`all`], or `results` alone and the error when the declarations are
/// broken: what a running attempt serves.
pub fn all_or_results(dir: &Path) -> (Vec<Declaration>, Vec<String>) {
    match all(dir) {
        Ok(list) => (list, vec![]),
        Err(e) => (vec![results()], vec![e.to_string()]),
    }
}

fn entry(d: &Declaration) -> Map<String, Value> {
    let mut e = Map::new();
    e.insert("file".into(), json!(d.file));
    e.insert("format".into(), json!(d.format));
    if let Some(task) = d.task_id {
        e.insert("task_id".into(), json!(task));
    }
    if !d.description.is_empty() {
        e.insert("description".into(), json!(d.description));
    }
    e
}

/// The artifact index of a running attempt, for `jobs get`: every artifact
/// whose file exists, with its current size, and the problems found (a broken
/// declaration file leaves `results` alone).
pub fn progress(dir: &Path) -> (Value, Vec<String>) {
    let (list, errors) = all_or_results(dir);
    let mut index = Map::new();
    for d in list {
        if let Ok(meta) = fs::symlink_metadata(dir.join(&d.file))
            && meta.is_file()
        {
            let mut e = entry(&d);
            e.insert("bytes".into(), json!(meta.len()));
            index.insert(d.name.clone(), Value::Object(e));
        }
    }
    (Value::Object(index), errors)
}

/// The manifest's view of the artifacts when an attempt is sealed: the
/// `artifacts` map (name to file), `runner.artifact_index` (format, size,
/// SHA-256, task, description) and the problems found. Only regular files
/// that exist are listed; a broken declaration file lists `results` alone.
/// An artifact problem never fails the attempt: its results stand.
pub fn sealed(dir: &Path) -> (Value, Value, Vec<String>) {
    let (list, mut errors) = all_or_results(dir);
    let (mut files, mut index) = (Map::new(), Map::new());
    for d in list {
        let path = dir.join(&d.file);
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.is_file() => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Ok(_) => {
                errors.push(format!(
                    "artifact {}: {} is not a regular file",
                    d.name, d.file
                ));
                continue;
            }
            Err(e) => {
                errors.push(format!("artifact {}: {e}", d.name));
                continue;
            }
        }
        let (bytes, sha256) = match digest_file(&path) {
            Ok(digest) => digest,
            Err(e) => {
                errors.push(format!("artifact {}: {e}", d.name));
                continue;
            }
        };
        let mut e = entry(&d);
        e.insert("bytes".into(), json!(bytes));
        e.insert("sha256".into(), json!(sha256));
        files.insert(d.name.clone(), json!(d.file));
        index.insert(d.name, Value::Object(e));
    }
    (Value::Object(files), Value::Object(index), errors)
}

/// Size and SHA-256 of a file, read in blocks.
pub fn digest_file(path: &Path) -> Result<(u64, String)> {
    use sha2::{Digest, Sha256};
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 16];
    let mut bytes = 0u64;
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        bytes += n as u64;
        hasher.update(&buffer[..n]);
    }
    Ok((bytes, format!("{:x}", hasher.finalize())))
}

/// The whole content of an artifact, at most [`INLINE_CAP`] bytes. A
/// `records` artifact is read up to its last complete line, so a record
/// being appended is never cut.
pub fn content(path: &Path, format: &str) -> Result<Value> {
    let size = fs::metadata(path)?.len();
    if size > INLINE_CAP as u64 {
        return Err(coded(
            "artifact_too_large",
            format!(
                "the artifact has {size} bytes, over the {INLINE_CAP}-byte inline cap; {}",
                if format == "records" {
                    "read it in pages with offset and limit"
                } else {
                    "read the file in the job directory"
                }
            ),
        ));
    }
    let mut data = fs::read(path)?;
    if format == "records" {
        data.truncate(data.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1));
    }
    let sha256 = storage::digest(&data);
    let bytes = data.len();
    let text = String::from_utf8(data).map_err(|_| "artifact is not UTF-8 text")?;
    Ok(json!({"format":format,"bytes":bytes,"sha256":sha256,"content":text}))
}

/// Records `offset..offset + limit` of a `records` artifact: the payloads of
/// complete records whose checksums hold, at most [`INLINE_CAP`] bytes of
/// payload (always at least one record). `next_offset` is where the next
/// page starts; `available` counts the complete records now in the file,
/// which a running job may extend.
///
/// A record is a newline-terminated, non-blank line; a final line without
/// its newline is still being written and does not count. The file is read
/// once as a stream: records before `offset` are only counted, and only the
/// page's records are parsed and checked, so a page costs one pass over the
/// bytes and memory for the page alone, however long the artifact is.
pub fn page(path: &Path, offset: usize, limit: usize) -> Result<Value> {
    if !(1..=MAX_PAGE).contains(&limit) {
        return Err(coded(
            "invalid_command",
            format!("limit must lie in 1..={MAX_PAGE}"),
        ));
    }
    let mut reader = io::BufReader::with_capacity(1 << 16, fs::File::open(path)?);
    let mut line = Vec::new();
    let (mut index, mut size, mut full) = (0usize, 0usize, false);
    let mut records = Vec::new();
    loop {
        line.clear();
        if reader.read_until(b'\n', &mut line)? == 0 || line.last() != Some(&b'\n') {
            break;
        }
        if line.iter().all(u8::is_ascii_whitespace) {
            continue;
        }
        if index >= offset && records.len() < limit && !full {
            let envelope: storage::Envelope = serde_json::from_slice(&line)
                .map_err(|e| format!("record {index} of the artifact is no checked record: {e}"))?;
            if envelope.checksum != storage::digest(envelope.payload_json.as_bytes()) {
                return Err(format!("record {index} of the artifact fails its checksum").into());
            }
            if size + envelope.payload_json.len() > INLINE_CAP {
                if records.is_empty() {
                    return Err(coded(
                        "artifact_too_large",
                        format!(
                            "record {index} alone exceeds the {INLINE_CAP}-byte inline cap; read the file in the job directory"
                        ),
                    ));
                }
                full = true;
            } else {
                size += envelope.payload_json.len();
                records.push(serde_json::from_str::<Value>(&envelope.payload_json)?);
            }
        }
        index += 1;
    }
    let next = offset.min(index) + records.len();
    Ok(
        json!({"format":"records","offset":offset,"records":records,"next_offset":next,"available":index}),
    )
}
