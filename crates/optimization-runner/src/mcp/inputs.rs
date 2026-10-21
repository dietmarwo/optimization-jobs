//! `put_input`: the content-addressed input store of a node,
//! `NODE/mcp/inputs/<sha256>`. An MCP client that has no file system in
//! common with the server stores the input files of a job here, such as a
//! new LP model, and passes the store as the job's `input_dir`. The store
//! holds data, never code; a file is named by its SHA-256, so no name can
//! traverse paths or stand for other content. Jobs copy their inputs when
//! they are created, so removing a stored file never touches a job.
use super::{
    Ctx, Server,
    tools::{self, Fail},
};
use optimization_job_api::{
    MAX_INPUT_BYTES,
    storage::{digest, lock},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    io::Write,
    path::{Path, PathBuf},
    time::{Duration, SystemTime},
};

/// Default of `--input-store-bytes`: the total size of the store.
pub const DEFAULT_STORE_BYTES: u64 = 1 << 30;
/// Stored files not written or stored again for this long are removed when
/// a server starts.
const MAX_AGE: Duration = Duration::from_secs(7 * 86_400);
/// Temporary files that a killed server left behind.
const TEMPORARY_AGE: Duration = Duration::from_secs(86_400);

pub fn directory(root: &Path) -> PathBuf {
    root.join("mcp").join("inputs")
}

fn content_name(name: &str) -> bool {
    name.len() == 64
        && name
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn older_than(entry: &fs::DirEntry, age: Duration) -> bool {
    entry
        .metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.elapsed().ok())
        .is_some_and(|elapsed| elapsed > age)
}

/// Removes stored files not modified for 7 days and temporary files older
/// than a day.
pub fn clean(root: &Path) {
    for entry in fs::read_dir(directory(root))
        .into_iter()
        .flatten()
        .flatten()
    {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let stale = if content_name(&name) {
            older_than(&entry, MAX_AGE)
        } else {
            name.starts_with('.') && older_than(&entry, TEMPORARY_AGE)
        };
        if stale && entry.file_type().is_ok_and(|t| t.is_file()) {
            let _ = fs::remove_file(entry.path());
        }
    }
}

/// Decodes base64 (RFC 4648, alphabet `+/`), with or without its padding;
/// ASCII whitespace, as in line-wrapped encodings, is ignored.
pub fn base64(text: &str) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::with_capacity(text.len() / 4 * 3 + 2);
    let (mut buffer, mut bits) = (0u32, 0u32);
    let (mut data, mut padding) = (0usize, 0usize);
    for (at, c) in text.bytes().enumerate() {
        if c.is_ascii_whitespace() {
            continue;
        }
        if c == b'=' {
            padding += 1;
            continue;
        }
        if padding > 0 {
            return Err(format!("data after padding at byte {at}"));
        }
        let value = match c {
            b'A'..=b'Z' => c - b'A',
            b'a'..=b'z' => c - b'a' + 26,
            b'0'..=b'9' => c - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            _ => {
                return Err(format!(
                    "{:?} at byte {at} is not a base64 character",
                    c as char
                ));
            }
        };
        data += 1;
        buffer = buffer << 6 | u32::from(value);
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            bytes.push((buffer >> bits) as u8);
            buffer &= (1 << bits) - 1;
        }
    }
    if data % 4 == 1 {
        return Err(
            "truncated: the number of base64 characters is one more than a multiple of four".into(),
        );
    }
    if padding > 0 && (padding > 2 || (data + padding) % 4 != 0) {
        return Err("incorrect padding".into());
    }
    Ok(bytes)
}

fn too_large(what: &str, bytes: u64) -> Fail {
    tools::fail(
        "invalid_arguments",
        format!(
            "{what} has {bytes} bytes, over the input limit of {MAX_INPUT_BYTES} bytes (64 MiB)"
        ),
    )
}

/// The `put_input` tool.
pub fn put(server: &Server, args: &Value, ctx: &Ctx) -> Result<Value, Fail> {
    let given: Vec<&str> = ["content", "content_base64", "from_artifact"]
        .into_iter()
        .filter(|key| !args[*key].is_null())
        .collect();
    let bytes = match given[..] {
        ["content"] => {
            let text = args["content"]
                .as_str()
                .ok_or_else(|| tools::fail("invalid_arguments", "content must be a string"))?;
            text.as_bytes().to_vec()
        }
        ["content_base64"] => {
            let text = args["content_base64"].as_str().ok_or_else(|| {
                tools::fail("invalid_arguments", "content_base64 must be a string")
            })?;
            base64(text).map_err(|e| {
                tools::fail(
                    "invalid_arguments",
                    format!("content_base64 is not valid base64: {e}"),
                )
            })?
        }
        ["from_artifact"] => artifact(server, &args["from_artifact"], ctx)?,
        _ => {
            return Err(tools::fail(
                "invalid_arguments",
                "pass exactly one of content (a string), content_base64 (a string) or from_artifact (an object)",
            ));
        }
    };
    if bytes.len() as u64 > MAX_INPUT_BYTES {
        return Err(too_large("the input", bytes.len() as u64));
    }
    store(server, &bytes)
}

/// The sealed manifest's view of its artifacts.
#[derive(Deserialize)]
struct Sealed {
    #[serde(default)]
    artifacts: BTreeMap<String, String>,
    #[serde(default)]
    runner: SealedRunner,
}

#[derive(Default, Deserialize)]
struct SealedRunner {
    #[serde(default)]
    artifact_index: BTreeMap<String, Value>,
}

/// The bytes of an artifact of an existing job, as a whole read of
/// `get_artifact` gives them: a `records` artifact up to its last complete
/// record. A sealed job serves what its manifest lists, checked against the
/// recorded SHA-256; a running job its declarations.
fn artifact(server: &Server, source: &Value, ctx: &Ctx) -> Result<Vec<u8>, Fail> {
    let invalid = || {
        tools::fail(
            "invalid_arguments",
            "from_artifact must be an object with job_id and name only",
        )
    };
    let keys = source.as_object().ok_or_else(invalid)?;
    if keys.keys().any(|k| k != "job_id" && k != "name") {
        return Err(invalid());
    }
    let id = tools::job_id(source)?;
    let name = tools::string(source, "name")?;
    let job = server.get(&id, ctx)?;
    let unknown = |why: &str| tools::fail("unknown_artifact", format!("job {id} {why}"));
    let directory = PathBuf::from(job["directory"].as_str().unwrap_or_default());
    let (file, format, sealed) = if tools::terminal(&job["state"]) {
        let bytes = tools::read_manifest(&job).map_err(Fail::Tool)?;
        let manifest: Sealed = serde_json::from_slice(&bytes)
            .map_err(|e| tools::fail("runner_error", format!("unreadable result manifest: {e}")))?;
        let file = manifest
            .artifacts
            .get(&name)
            .cloned()
            .ok_or_else(|| unknown(&format!("has no artifact {name:?}")))?;
        let index = manifest.runner.artifact_index.get(&name);
        let field = |key: &str| index.and_then(|e| e[key].as_str()).map(str::to_owned);
        let format = field("format").unwrap_or_else(|| {
            if name == optimization_job_api::artifact::RESULTS {
                "records".into()
            } else {
                "file".into()
            }
        });
        (file, format, field("sha256"))
    } else {
        let entry = &job["artifact_index"][&name];
        let file = entry["file"]
            .as_str()
            .ok_or_else(|| unknown(&format!("has no artifact {name:?} (or no file of it yet)")))?;
        let format = entry["format"].as_str().unwrap_or("file");
        (file.to_owned(), format.to_owned(), None)
    };
    let path = match fs::canonicalize(directory.join(&file)) {
        Ok(path) => path,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Err(unknown(&format!("has no file of artifact {name:?} yet")));
        }
        Err(e) => return Err(tools::fail("runner_error", format!("{file}: {e}"))),
    };
    let inside = fs::canonicalize(&directory).is_ok_and(|d| path.starts_with(d));
    if !inside || !path.is_file() {
        return Err(tools::fail(
            "runner_error",
            format!("artifact {name:?} escapes its job directory or is no regular file"),
        ));
    }
    let size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
    if size > MAX_INPUT_BYTES {
        return Err(too_large(&format!("artifact {name:?}"), size));
    }
    let mut bytes = tools::read_file(&path, MAX_INPUT_BYTES).map_err(|e| {
        if e.contains("over the cap") {
            too_large(&format!("artifact {name:?}"), MAX_INPUT_BYTES + 1)
        } else {
            tools::fail("runner_error", format!("{}: {e}", path.display()))
        }
    })?;
    if let Some(sealed) = sealed
        && digest(&bytes) != sealed
    {
        return Err(tools::fail(
            "runner_error",
            format!(
                "artifact {name:?} changed after the job ended: its SHA-256 differs from the manifest"
            ),
        ));
    }
    if format == "records" {
        bytes.truncate(bytes.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1));
    }
    Ok(bytes)
}

/// True if `path` is a regular file holding exactly the content of `sha256`.
fn intact(path: &Path, sha256: &str, size: usize) -> bool {
    fs::symlink_metadata(path).is_ok_and(|m| m.is_file() && m.len() == size as u64)
        && fs::read(path).is_ok_and(|bytes| digest(&bytes) == sha256)
}

/// Bytes of the regular files in the store, except `except`.
fn used(directory: &Path, except: &Path) -> std::io::Result<u64> {
    let mut total = 0u64;
    for entry in fs::read_dir(directory)?.flatten() {
        // A file removed meanwhile (another server's cleanup) counts as gone.
        let Ok(meta) = entry.metadata() else {
            continue;
        };
        if meta.is_file() && entry.path() != except {
            total = total.saturating_add(meta.len());
        }
    }
    Ok(total)
}

fn io_error(path: &Path, e: std::io::Error) -> Fail {
    tools::fail("runner_error", format!("{}: {e}", path.display()))
}

/// Writes `bytes` to the store, atomically, or refreshes the modification
/// time of the identical file already there.
fn store(server: &Server, bytes: &[u8]) -> Result<Value, Fail> {
    let directory = directory(&server.root);
    fs::create_dir_all(&directory).map_err(|e| io_error(&directory, e))?;
    let sha256 = digest(bytes);
    let target = directory.join(&sha256);
    let lock_path = server.root.join("mcp").join("inputs.lock");
    let _guard = lock(&lock_path).map_err(|e| io_error(&lock_path, e))?;
    if intact(&target, &sha256, bytes.len()) {
        fs::File::options()
            .write(true)
            .open(&target)
            .and_then(|f| f.set_modified(SystemTime::now()))
            .map_err(|e| io_error(&target, e))?;
    } else {
        let used = used(&directory, &target).map_err(|e| io_error(&directory, e))?;
        let limit = server.input_store_bytes;
        if used.saturating_add(bytes.len() as u64) > limit {
            return Err(tools::fail(
                "input_store_full",
                format!(
                    "the input store {} holds {used} bytes; {} more would exceed its limit of {limit} bytes (--input-store-bytes). Files not stored again for 7 days are removed when the server starts",
                    directory.display(),
                    bytes.len()
                ),
            ));
        }
        let temporary = directory.join(format!(".{sha256}.{}.tmp", std::process::id()));
        let written = (|| {
            let mut file = fs::File::create(&temporary)?;
            file.write_all(bytes)?;
            file.sync_all()?;
            fs::rename(&temporary, &target)?;
            fs::File::open(&directory)?.sync_all()
        })();
        if let Err(e) = written {
            let _ = fs::remove_file(&temporary);
            return Err(io_error(&target, e));
        }
    }
    Ok(json!({
        "file": sha256,
        "sha256": sha256,
        "bytes": bytes.len(),
        "input_dir": directory.to_string_lossy(),
    }))
}

#[cfg(test)]
mod tests {
    use super::base64;

    #[test]
    fn base64_decoding() {
        for (text, bytes) in [
            ("", &b""[..]),
            ("Zg==", b"f"),
            ("Zm8=", b"fo"),
            ("Zm9v", b"foo"),
            ("Zm9vYg", b"foob"),
            ("Zm9vYmE=", b"fooba"),
            ("Zm9v\r\nYmFy\n", b"foobar"),
            ("+/8=", &[0xfb, 0xff][..]),
        ] {
            assert_eq!(base64(text).unwrap(), bytes, "{text:?}");
        }
        for bad in [
            "Z", "Zm9vY", "Zg=", "Zg===", "Zg==Zg==", "Zm9v!", "Zm-_", "Z===", "Zm8==",
        ] {
            assert!(base64(bad).is_err(), "{bad:?}");
        }
    }
}
