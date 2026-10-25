//! Explicit placement and a bounded, fixed-helper protocol for trusted SSH peers.
mod agent;
pub(crate) mod fleet;
mod io;
pub(crate) mod node;
mod transport;

use optimization_job_api::{Result, coded};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{io::BufRead, path::PathBuf};

pub(crate) const PROTOCOL: &str = "execution.remote/0.1";
pub(crate) const MAX_CONTROL: usize = 4 * 1024 * 1024;
#[derive(Clone, Debug, Serialize, Deserialize, clap::Args)]
#[serde(deny_unknown_fields)]
pub(crate) struct Endpoint {
    #[arg(long)]
    pub host: String,
    #[arg(long)]
    pub user: String,
    #[arg(long, default_value_t = 22)]
    pub port: u16,
    #[arg(id = "remote_root", long = "remote-root")]
    pub root: PathBuf,
    #[arg(long)]
    pub helper: String,
    #[arg(long)]
    pub identity_file: Option<PathBuf>,
    #[arg(long)]
    pub known_hosts: PathBuf,
    #[arg(long, default_value_t = 30)]
    pub timeout_seconds: u64,
}
impl Endpoint {
    pub(crate) fn validate(&self) -> Result<()> {
        let word = |s: &str, allowed: &[u8], max: usize| {
            !s.is_empty()
                && s.len() <= max
                && !s.starts_with('-')
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || allowed.contains(&b))
        };
        if !word(&self.host, b".-:[]", 255)
            || !word(&self.user, b"._-", 64)
            || self.port == 0
            || !self.root.is_absolute()
            || self.root.to_string_lossy().len() > 4096
            // systemd-run would expand `$` in the launcher's --root argument.
            || self.root.to_string_lossy().contains('$')
            || !self.helper.starts_with('/')
            || !word(&self.helper, b"/._-", 4096)
            || self.helper.split('/').any(|s| s == ".." || s == ".")
            || !self.known_hosts.is_absolute()
            || !self
                .known_hosts
                .to_str()
                .is_some_and(|s| word(s, b"/._-", 4096))
            || self
                .identity_file
                .as_ref()
                .is_some_and(|p| !p.is_absolute())
            || !(1..=300).contains(&self.timeout_seconds)
        {
            return Err(coded(
                "invalid_remote_node",
                "invalid host/user/port, absolute root (without `$`), helper or key paths, or timeout (1..300 seconds)",
            ));
        }
        Ok(())
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    pub schema_version: String,
    pub root: PathBuf,
    pub node_id: Option<String>,
    pub operation: Operation,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Operation {
    Describe,
    Put {
        sha256: String,
        bytes: u64,
    },
    Submit {
        dispatch_id: String,
        identity: String,
        spec: Value,
        inputs: Vec<Blob>,
        worker: Option<Value>,
    },
    Lookup {
        dispatch_id: String,
    },
    Cancel {
        dispatch_id: String,
        immediate: bool,
    },
    Execution {
        dispatch_id: String,
    },
    Repair {
        dispatch_id: String,
    },
    Inspect {
        dispatch_id: String,
        selection: Selection,
    },
    Download {
        dispatch_id: String,
        selection: Selection,
        bytes: u64,
        sha256: String,
    },
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Blob {
    pub index: usize,
    pub bytes: u64,
    pub sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Selection {
    Native,
    Execution,
    Output { name: String },
    Artifact { name: String },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Response {
    pub schema_version: String,
    pub node_id: Option<String>,
    pub result: Option<Value>,
    pub error: Option<Failure>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Failure {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}
pub(crate) fn frame(reader: &mut impl BufRead) -> Result<Vec<u8>> {
    let mut out = Vec::new();
    loop {
        let chunk = reader.fill_buf()?;
        if chunk.is_empty() {
            return Err(coded("remote_protocol", "truncated JSON control frame"));
        }
        let stop = chunk.iter().position(|b| *b == b'\n');
        let n = stop.map_or(chunk.len(), |n| n + 1);
        if out.len() + n > MAX_CONTROL {
            return Err(coded("remote_protocol", "control frame exceeds 4 MiB"));
        }
        out.extend_from_slice(&chunk[..n]);
        reader.consume(n);
        if stop.is_some() {
            return Ok(out);
        }
    }
}
pub(crate) fn serve() -> Result<()> {
    agent::serve()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn control_frames_are_bounded_and_leave_binary_bytes_unconsumed() {
        let mut input = std::io::Cursor::new(b"{}\n\0binary\xff");
        assert_eq!(frame(&mut input).unwrap(), b"{}\n");
        let mut rest = Vec::new();
        std::io::Read::read_to_end(&mut input, &mut rest).unwrap();
        assert_eq!(rest, b"\0binary\xff");
        assert!(frame(&mut std::io::Cursor::new(b"{}")).is_err());
        assert!(frame(&mut std::io::Cursor::new(vec![b'x'; MAX_CONTROL + 1])).is_err());
    }
    #[test]
    fn shell_fragments_and_unknown_operations_are_rejected() {
        let mut e = Endpoint {
            host: "node.example".into(),
            user: "research".into(),
            port: 22,
            root: "/srv/jobs with spaces".into(),
            helper: "/usr/local/bin/optimization-run".into(),
            identity_file: None,
            known_hosts: "/home/user/.ssh/known_hosts".into(),
            timeout_seconds: 30,
        };
        assert!(e.validate().is_ok());
        e.root = "/srv/$HOME/jobs".into();
        assert!(e.validate().is_err());
        e.root = "/srv/jobs with spaces".into();
        for helper in [
            "runner",
            "/bin/runner;touch /tmp/pwned",
            "/bin/$(id)",
            "/a/../b",
        ] {
            e.helper = helper.into();
            assert!(e.validate().is_err());
        }
        assert!(
            serde_json::from_value::<Operation>(
                serde_json::json!({"kind":"shell","argv":["true"]})
            )
            .is_err()
        );
        assert!(
            serde_json::from_value::<Operation>(
                serde_json::json!({"kind":"lookup","dispatch_id":"x","extra":true})
            )
            .is_err()
        );
    }
    #[test]
    fn identity_initialization_is_explicit_and_persistent() {
        let root = tempfile::tempdir().unwrap();
        crate::write_atomic_json(
            &root.path().join("node.json"),
            &serde_json::json!({"capacity":1}),
        )
        .unwrap();
        assert!(node::identity(root.path(), false).is_err());
        let first = node::identity(root.path(), true).unwrap();
        assert_eq!(first, node::identity(root.path(), true).unwrap());
        assert_eq!(first, node::identity(root.path(), false).unwrap());
    }
}
