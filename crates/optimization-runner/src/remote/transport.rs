//! Single-threaded nonblocking pipes bound control/transfer time even when a
//! descendant keeps a pipe open. Output is spooled to disk, not a binary Vec.
use super::{Endpoint, MAX_CONTROL, PROTOCOL, Request, Response, frame};
use optimization_job_api::{
    Result, coded,
    process::{group, terminate_process_group},
};
use std::{
    fs::File,
    io::{BufReader, Read, Seek, Write},
    os::fd::AsRawFd,
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

pub(crate) struct Reply {
    pub value: serde_json::Value,
    pub body: BufReader<File>,
    _spool: tempfile::NamedTempFile,
}
fn nonblocking(fd: &impl AsRawFd) -> Result<()> {
    let fd = fd.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}
fn exited(child: &Child) -> Result<bool> {
    let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
    if unsafe {
        libc::waitid(
            libc::P_PID,
            child.id(),
            &mut info,
            libc::WEXITED | libc::WNOWAIT | libc::WNOHANG,
        )
    } < 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(unsafe { info.si_pid() } != 0)
}
fn drain(
    pipe: &mut impl Read,
    output: &mut impl Write,
    kept: &mut u64,
    limit: u64,
) -> Result<bool> {
    let mut buf = [0u8; 65536];
    loop {
        match pipe.read(&mut buf) {
            Ok(0) => return Ok(true),
            Ok(n) => {
                *kept += n as u64;
                if *kept > limit {
                    return Err(coded(
                        "remote_protocol",
                        "SSH output exceeds its byte limit",
                    ));
                }
                output.write_all(&buf[..n])?;
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => return Ok(false),
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.into()),
        }
    }
}
pub(crate) fn call(
    endpoint: &Endpoint,
    node_id: Option<&str>,
    operation: super::Operation,
    input: Option<File>,
) -> Result<Reply> {
    endpoint.validate()?;
    let req = Request {
        schema_version: PROTOCOL.into(),
        root: endpoint.root.clone(),
        node_id: node_id.map(Into::into),
        operation,
    };
    let mut prefix = serde_json::to_vec(&req)?;
    prefix.push(b'\n');
    if prefix.len() > MAX_CONTROL {
        return Err(coded(
            "remote_protocol",
            "request exceeds control frame limit",
        ));
    }
    let mut cmd = Command::new("ssh");
    cmd.args([
        "-T",
        "-x",
        "-oBatchMode=yes",
        "-oStrictHostKeyChecking=yes",
        "-oForwardAgent=no",
        "-oClearAllForwardings=yes",
        "-oPermitLocalCommand=no",
        "-oControlMaster=no",
        "-oControlPath=none",
        "-oControlPersist=no",
        "-oGlobalKnownHostsFile=/dev/null",
        "-oKnownHostsCommand=none",
        "-oUpdateHostKeys=no",
        "-oConnectionAttempts=1",
        "-oServerAliveInterval=5",
        "-oServerAliveCountMax=2",
    ])
    .arg(format!(
        "-oConnectTimeout={}",
        endpoint.timeout_seconds.min(30)
    ))
    .arg("-o")
    .arg(format!(
        "UserKnownHostsFile={}",
        endpoint.known_hosts.display()
    ))
    .arg("-p")
    .arg(endpoint.port.to_string());
    if let Some(key) = &endpoint.identity_file {
        cmd.arg("-oIdentitiesOnly=yes").arg("-i").arg(key);
    }
    // Only the validated helper path and these two fixed tokens reach a remote
    // shell. Roots, argv, environment and payloads travel solely over stdin.
    cmd.arg("--")
        .arg(format!("{}@{}", endpoint.user, endpoint.host))
        .arg(format!("{} remote serve", endpoint.helper));
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    group(&mut cmd);
    let mut child = cmd
        .spawn()
        .map_err(|e| coded("remote_transport", format!("cannot start SSH: {e}")))?;
    let result = (|| -> Result<_> {
        let mut stdin = Some(child.stdin.take().unwrap());
        let mut stdout = child.stdout.take().unwrap();
        let mut stderr = child.stderr.take().unwrap();
        nonblocking(stdin.as_ref().unwrap())?;
        nonblocking(&stdout)?;
        nonblocking(&stderr)?;
        let mut body = input;
        let mut pending = prefix;
        let mut offset = 0;
        let mut out = tempfile::Builder::new()
            .prefix(".optimization-ssh-")
            .tempfile()?;
        let mut err = Vec::new();
        let mut out_n = 0;
        let mut err_n = 0;
        let mut out_done = false;
        let mut err_done = false;
        let start = Instant::now();
        let mut stopped = None;
        loop {
            if stopped.is_none() && exited(&child)? {
                terminate_process_group(&mut child);
                stopped = Some(Instant::now());
            }
            if stdin.is_some() {
                if offset == pending.len() {
                    pending.clear();
                    offset = 0;
                    if let Some(file) = &mut body {
                        let mut buf = [0u8; 65536];
                        let n = file.read(&mut buf)?;
                        pending.extend_from_slice(&buf[..n]);
                        if n == 0 {
                            body = None;
                        }
                    }
                    if pending.is_empty() {
                        stdin = None;
                    }
                }
                if let Some(pipe) = &mut stdin
                    && offset < pending.len()
                {
                    match pipe.write(&pending[offset..]) {
                        Ok(n) => offset += n,
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => (),
                        Err(e) if e.kind() == std::io::ErrorKind::BrokenPipe => stdin = None,
                        Err(e) => return Err(e.into()),
                    }
                }
            }
            if !out_done {
                out_done = drain(
                    &mut stdout,
                    out.as_file_mut(),
                    &mut out_n,
                    MAX_CONTROL as u64 + crate::files::MAX_FILE,
                )?;
            }
            if !err_done {
                err_done = drain(&mut stderr, &mut err, &mut err_n, 65536)?;
            }
            if stopped.is_some() && out_done && err_done {
                break;
            }
            if start.elapsed() >= Duration::from_secs(endpoint.timeout_seconds)
                || stopped.is_some_and(|t| t.elapsed() >= Duration::from_secs(2))
            {
                return Err(coded(
                    "remote_transport",
                    "SSH/control deadline exceeded; reconcile the same node and dispatch instead of replaying",
                ));
            }
            thread::sleep(Duration::from_millis(2));
        }
        let status = child.wait()?;
        if !status.success() {
            return Err(coded(
                "remote_transport",
                format!("SSH exited {status}: {}", String::from_utf8_lossy(&err)),
            ));
        }
        out.as_file_mut().rewind()?;
        let mut reader = BufReader::new(out.reopen()?);
        let response: Response = serde_json::from_slice(&frame(&mut reader)?)
            .map_err(|e| coded("remote_protocol", format!("invalid response: {e}")))?;
        if response.schema_version != PROTOCOL {
            return Err(coded("remote_protocol", "unsupported remote protocol"));
        }
        if node_id.is_some() && response.node_id.as_deref() != node_id {
            return Err(coded(
                "node_identity_mismatch",
                "remote node identity differs from the pinned identity",
            ));
        }
        if response.result.is_some() && response.error.is_some() {
            return Err(coded(
                "remote_protocol",
                "response has both success and error",
            ));
        }
        if let Some(error) = response.error {
            return Err(coded(
                if error.code == "attempt_active" {
                    "attempt_active"
                } else {
                    "remote_rejected"
                },
                format!("{}: {}", error.code, error.message),
            ));
        }
        let actual = response.node_id.clone();
        let value = response
            .result
            .ok_or_else(|| coded("remote_protocol", "response has neither result nor error"))?;
        if value["schema_version"] == "execution.node/0.1"
            && (value["node_id"].as_str() != actual.as_deref()
                || actual.as_ref().is_none_or(|id| !crate::files::hash_ok(id)))
        {
            return Err(coded(
                "remote_protocol",
                "discovery identity disagrees with response envelope",
            ));
        }
        Ok(Reply {
            value,
            body: reader,
            _spool: out,
        })
    })();
    if result.is_err() {
        terminate_process_group(&mut child);
        let _ = child.wait();
    }
    result
}
