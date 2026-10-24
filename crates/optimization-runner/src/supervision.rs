//! Process mechanics only: bounded logs, stop/deadline handling and containment.
//! The adapter supplies the command and interprets its result.
use crate::{IMMEDIATE_GRACE, SIGNALS, Stop, boot, now, publish_stop, stop_request};
use optimization_job_api::{
    Result,
    process::{drain_file, group, group_stopped, terminate_process_group},
    storage::write_atomic_json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::os::unix::process::ExitStatusExt;
use std::{
    fs,
    path::Path,
    process::{Command, ExitStatus, Stdio},
    sync::atomic::Ordering,
    thread,
    time::{Duration, Instant},
};

#[derive(Clone, Copy)]
pub(crate) struct Budget {
    pub cpu_slots: usize,
    pub wall: Duration,
    pub grace: Duration,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Containment {
    NotStarted,
    Stopped,
    Unknown,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum StopReason {
    Cancelled,
    TimedOut,
}
impl StopReason {
    pub(crate) fn state(self) -> crate::execution::State {
        match self {
            Self::Cancelled => crate::execution::State::Cancelled,
            Self::TimedOut => crate::execution::State::TimedOut,
        }
    }
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProcessExit {
    pub code: Option<i32>,
    pub signal: Option<i32>,
}
impl From<ExitStatus> for ProcessExit {
    fn from(exit: ExitStatus) -> Self {
        Self {
            code: exit.code(),
            signal: exit.signal(),
        }
    }
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Observation {
    pub process: Option<ProcessExit>,
    pub stop_reason: Option<StopReason>,
    pub containment: Containment,
}
impl Default for Observation {
    fn default() -> Self {
        Self {
            process: None,
            stop_reason: None,
            containment: Containment::NotStarted,
        }
    }
}
impl Observation {
    pub(crate) fn can_release(&self) -> bool {
        self.containment != Containment::Unknown
    }
}

pub(crate) fn execute(
    dir: &Path,
    budget: Budget,
    mut command: Command,
    signal_on_stop: bool,
    start: Instant,
    observed: &mut Observation,
) -> Result<()> {
    let stdout = fs::File::create(dir.join("stdout.log"))?;
    let stderr = fs::File::create(dir.join("stderr.log"))?;
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    group(&mut command);
    let mut child = command.spawn()?;
    let pgid = child.id();
    observed.containment = Containment::Unknown;
    // Include the boot lookup in the guarded operation: every error after a
    // successful spawn must still stop/reap the child and retain uncertainty.
    let tracked = (|| -> Result<()> {
        write_atomic_json(
            &dir.join("worker-process.json"),
            &json!({"pgid":pgid,"boot_id":boot()?}),
        )?;
        Ok(())
    })();
    if let Err(error) = tracked {
        terminate_process_group(&mut child);
        observed.process = child.wait().ok().map(Into::into);
        if group_stopped(pgid).unwrap_or(false) {
            observed.containment = Containment::Stopped;
        }
        return Err(error);
    }
    let a = child.stdout.take().unwrap();
    let b = child.stderr.take().unwrap();
    let ta = thread::spawn(move || drain_file(a, stdout, 1_048_576));
    let tb = thread::spawn(move || drain_file(b, stderr, 1_048_576));
    let hard_deadline = start + budget.wall + budget.grace;
    let mut reason = None;
    let mut immediate_deadline: Option<Instant> = None;
    let mut signalled = 0;
    let mut command_deadline = None;
    let polled = (|| -> Result<ExitStatus> {
        loop {
            if let Some(exit) = child.try_wait()? {
                return Ok(exit);
            }
            let request = stop_request(dir);
            if reason.is_none() {
                if request != Stop::None {
                    reason = Some(StopReason::Cancelled);
                } else if start.elapsed() >= budget.wall {
                    reason = Some(StopReason::TimedOut);
                    publish_stop(dir, json!({"mode":"graceful","reason":"timed_out"}))?;
                }
            }
            if signal_on_stop && reason.is_some() && command_deadline.is_none() {
                // Trusted commands have no worker cancel.request protocol.
                // TERM the process group once, then enforce their own grace.
                unsafe {
                    libc::kill(-(pgid as i32), libc::SIGTERM);
                }
                command_deadline = Some(Instant::now() + budget.grace);
            }
            let from_signals = SIGNALS.load(Ordering::Relaxed);
            if from_signals > signalled {
                signalled = from_signals;
                let mode = if from_signals > 1 {
                    "immediate"
                } else {
                    "graceful"
                };
                publish_stop(
                    dir,
                    json!({"mode":mode,"reason":"signal","requested_at":now()}),
                )?;
            }
            if request == Stop::Immediate && immediate_deadline.is_none() {
                immediate_deadline = Some(Instant::now() + IMMEDIATE_GRACE);
            }
            let deadline = command_deadline.unwrap_or(hard_deadline).min(hard_deadline);
            let deadline = immediate_deadline.map_or(deadline, |d| d.min(deadline));
            if Instant::now() >= deadline {
                terminate_process_group(&mut child);
                return Ok(child.wait()?);
            }
            thread::sleep(Duration::from_millis(10));
        }
    })();
    observed.stop_reason = reason;
    if let Ok(exit) = &polled {
        observed.process = Some((*exit).into());
    }
    terminate_process_group(&mut child);
    let _ = child.wait();
    let verify = Instant::now();
    loop {
        match group_stopped(pgid) {
            Ok(true) => break,
            _ if verify.elapsed() < Duration::from_secs(2) => {
                thread::sleep(Duration::from_millis(10))
            }
            _ => {
                write_atomic_json(
                    &dir.join("containment.unknown"),
                    &json!({"pgid":pgid,"reason":"group liveness unknown; slots retained"}),
                )?;
                return Err("worker group termination unverified; reservation retained".into());
            }
        }
    }
    observed.containment = Containment::Stopped;
    ta.join().map_err(|_| "stdout drainer panic")??;
    tb.join().map_err(|_| "stderr drainer panic")??;
    polled?;
    Ok(())
}
