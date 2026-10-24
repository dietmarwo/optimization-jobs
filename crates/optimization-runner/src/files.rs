//! Bounded binary transfers. A final name is published only after verification.
use optimization_job_api::{Result, coded, storage::lock};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::OpenOptionsExt,
    path::{Component, Path, PathBuf},
};

pub(crate) const MAX_FILE: u64 = 64 * 1024 * 1024;
pub(crate) const MAX_TOTAL: u64 = 256 * 1024 * 1024;
const STORE_LIMIT: u64 = 1024 * 1024 * 1024;

pub(crate) fn fail(message: impl Into<String>) -> optimization_job_api::Error {
    coded("file_transfer_failed", message)
}
pub(crate) fn hash_ok(hash: &str) -> bool {
    hash.len() == 64
        && hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub(crate) fn relative(path: &str) -> Result<()> {
    if path.is_empty()
        || path.contains('\0')
        || path.len() > 512
        || path.contains('\\')
        || path.split('/').any(|s| {
            s.is_empty()
                || s.starts_with('.')
                || matches!(
                    s,
                    "job.json"
                        | "resolved.json"
                        | "submitted.json"
                        | "provenance.json"
                        | "run.json"
                        | "command-result.json"
                        | "worker"
                        | "cancel.request"
                )
        })
        || !Path::new(path)
            .components()
            .all(|c| matches!(c, Component::Normal(_)))
    {
        return Err(fail(
            "expected a relative path without dot components or runtime names",
        ));
    }
    Ok(())
}
/// Refuse symlinks in every component. This is a checked materialization path,
/// not a security boundary against hostile code running under the same UID.
pub(crate) fn beneath(base: &Path, path: &str) -> Result<PathBuf> {
    relative(path)?;
    if fs::symlink_metadata(base)?.file_type().is_symlink() {
        return Err(fail("symlink transfer root"));
    }
    let mut out = base.to_path_buf();
    for component in Path::new(path).components() {
        out.push(component);
        match fs::symlink_metadata(&out) {
            Ok(m) if m.file_type().is_symlink() => return Err(fail("symlink in transfer path")),
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(out)
}
pub(crate) fn open(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)?;
    if !file.metadata()?.is_file() {
        return Err(fail("transfer source must be a regular file"));
    }
    Ok(file)
}
pub(crate) fn fingerprint(path: &Path, limit: u64) -> Result<(u64, String)> {
    let mut source = open(path)?;
    let mut sink = std::io::sink();
    stream(&mut source, &mut sink, limit)
}
fn stream(source: &mut impl Read, sink: &mut impl Write, limit: u64) -> Result<(u64, String)> {
    let mut hash = Sha256::new();
    let mut count = 0;
    let mut buf = [0u8; 65536];
    loop {
        // Read at most one byte beyond the limit, even for unbounded stdin.
        let nmax = buf.len().min((limit.saturating_sub(count) + 1) as usize);
        let n = source.read(&mut buf[..nmax])?;
        if n == 0 {
            break;
        }
        count += n as u64;
        if count > limit {
            return Err(fail("file exceeds byte limit"));
        }
        hash.update(&buf[..n]);
        sink.write_all(&buf[..n])?;
    }
    Ok((count, format!("{:x}", hash.finalize())))
}
pub(crate) fn verify(path: &Path, bytes: u64, hash: &str) -> Result<()> {
    if bytes > MAX_FILE || !hash_ok(hash) {
        return Err(fail("invalid byte count or SHA-256"));
    }
    if fingerprint(path, bytes)? != (bytes, hash.into()) {
        return Err(fail("file length or SHA-256 mismatch"));
    }
    Ok(())
}
/// No-clobber publication in the destination filesystem, after fsync. Errors
/// drop the partial; process termination may leave .transfer-*.
pub(crate) fn copy(
    source: &mut impl Read,
    dest: &Path,
    limit: u64,
    expected: Option<(u64, &str)>,
) -> Result<Value> {
    if limit > MAX_FILE {
        return Err(fail("file limit exceeds 64 MiB"));
    }
    let absolute = std::path::absolute(dest)?;
    let dest = absolute.as_path();
    let parent = dest
        .parent()
        .ok_or_else(|| fail("destination has no parent"))?;
    let mut tmp = tempfile::Builder::new()
        .prefix(".transfer-")
        .tempfile_in(parent)?;
    let (bytes, sha256) = stream(source, tmp.as_file_mut(), limit)?;
    if let Some((n, hash)) = expected
        && (n != bytes || hash != sha256)
    {
        return Err(fail("file length or SHA-256 mismatch"));
    }
    tmp.as_file().sync_all()?;
    tmp.persist_noclobber(dest)
        .map_err(|e| fail(format!("refusing to replace destination: {}", e.error)))?;
    File::open(parent)?.sync_all()?;
    Ok(json!({"bytes":bytes,"sha256":sha256}))
}
pub(crate) fn blob(root: &Path, hash: &str) -> Result<PathBuf> {
    if !hash_ok(hash) {
        return Err(fail("expected lowercase SHA-256"));
    }
    Ok(root.join("blobs").join(hash))
}
pub(crate) fn put(root: &Path, source: &Path, bytes: u64, hash: &str) -> Result<Value> {
    crate::capacity(root)?;
    if bytes > MAX_FILE {
        return Err(fail("file exceeds 64 MiB"));
    }
    let dest = blob(root, hash)?;
    let _guard = lock(&root.join("files.lock"))?;
    fs::create_dir_all(root.join("blobs"))?;
    // Do not consume a retry's stdin when the verified blob is already present.
    if fs::symlink_metadata(&dest).is_ok() {
        verify(&dest, bytes, hash)?;
        return Ok(json!({"sha256":hash,"bytes":bytes,"reused":true}));
    }
    let mut used = 0u64;
    for item in fs::read_dir(root.join("blobs"))? {
        used = used.saturating_add(item?.metadata()?.len());
    }
    if used.saturating_add(bytes) > STORE_LIMIT {
        return Err(fail(
            "blob store quota exceeded (1 GiB); remove unused retained blobs explicitly",
        ));
    }
    let result = if source == Path::new("-") {
        copy(
            &mut std::io::stdin().lock(),
            &dest,
            bytes,
            Some((bytes, hash)),
        )?
    } else {
        copy(&mut open(source)?, &dest, bytes, Some((bytes, hash)))?
    };
    Ok(result)
}
pub(crate) fn get(root: &Path, hash: &str, bytes: u64, dest: &Path) -> Result<Value> {
    crate::capacity(root)?;
    if bytes > MAX_FILE {
        return Err(fail("file exceeds 64 MiB"));
    }
    copy(
        &mut open(&blob(root, hash)?)?,
        dest,
        bytes,
        Some((bytes, hash)),
    )
}
pub(crate) fn cleanup(root: &Path) -> Result<Value> {
    crate::capacity(root)?;
    let _guard = lock(&root.join("files.lock"))?;
    let dir = root.join("blobs");
    let mut removed = 0;
    if dir.exists() {
        for item in fs::read_dir(&dir)? {
            let item = item?;
            if item.file_name().to_string_lossy().starts_with(".transfer-")
                && item.file_type()?.is_file()
            {
                fs::remove_file(item.path())?;
                removed += 1;
            }
        }
        File::open(&dir)?.sync_all()?;
    }
    Ok(json!({"removed_partials":removed,"verified_blobs_retained":true}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn failed_transfers_publish_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let dest = dir.path().join("out");
        for (data, limit, expected) in [
            (b"abc".as_slice(), 2, None),
            (b"ab".as_slice(), 3, Some((3, "bad"))),
        ] {
            assert!(copy(&mut &data[..], &dest, limit, expected).is_err());
            assert!(!dest.exists());
            assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
        }
        struct Broken;
        impl Read for Broken {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("interrupted transfer"))
            }
        }
        assert!(copy(&mut Broken, &dest, 3, None).is_err());
        assert!(!dest.exists());
    }
    #[test]
    fn never_clobbers_or_follows_links() {
        let dir = tempfile::tempdir().unwrap();
        let dest = dir.path().join("out");
        fs::write(&dest, b"old").unwrap();
        assert!(copy(&mut b"new".as_slice(), &dest, 3, None).is_err());
        assert_eq!(fs::read(&dest).unwrap(), b"old");
        std::os::unix::fs::symlink(&dest, dir.path().join("link")).unwrap();
        assert!(open(&dir.path().join("link")).is_err());
        assert!(beneath(dir.path(), "link").is_err());
        for path in [
            "../out",
            "/out",
            "a/../out",
            "a//out",
            "job.json",
            ".execution.json",
        ] {
            assert!(relative(path).is_err());
        }
    }
}
