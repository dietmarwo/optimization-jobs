//! Optimization adapter: worker invocation, mathematical outcome validation and
//! native manifest construction. The execution core does not interpret these.
use crate::{
    execution::{self, Adapter as ExecutionAdapter, Finalized, NativeResult, State},
    read, spec,
    supervision::{Budget, Containment, Observation},
};
use optimization_job_api::{
    Request, Result, artifact, result,
    storage::{digest, write_atomic_json},
};
use serde_json::{Value, json};
use std::{fs, path::Path, process::Command, time::Duration};

pub(crate) struct Adapter {
    request: Request,
}
pub(crate) struct Outcome {
    status: State,
    exact: bool,
}
impl Adapter {
    pub(crate) fn load(dir: &Path) -> Result<Self> {
        Ok(Self {
            request: spec(&dir.join("resolved.json"))?,
        })
    }
}
impl ExecutionAdapter for Adapter {
    type Outcome = Outcome;
    fn kind(&self) -> &'static str {
        "optimization"
    }
    fn budget(&self) -> Budget {
        Budget {
            cpu_slots: self.request.slots(),
            wall: Duration::from_secs_f64(self.request.wall()),
            grace: Duration::from_secs_f64(self.request.grace()),
        }
    }
    fn command(&self, dir: &Path) -> Result<Command> {
        let provenance = read(&dir.join("provenance.json"))?;
        if json!(digest(&fs::read(dir.join("worker"))?)) != provenance["worker_digest"] {
            return Err("staged worker digest mismatch".into());
        }
        let mut command = Command::new(dir.join("worker"));
        command
            .arg("execute")
            .arg(dir)
            .current_dir(dir)
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("OMP_NUM_THREADS", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("MKL_NUM_THREADS", "1");
        Ok(command)
    }
    fn completed(&self, dir: &Path, observed: &Observation) -> Result<Outcome> {
        let worker = if observed
            .process
            .as_ref()
            .is_some_and(|exit| exit.code == Some(0))
        {
            result::worker_outcome(dir, &self.request)?
        } else {
            None
        };
        let exact = worker.is_some();
        let status = match (observed.stop_reason, worker) {
            (Some(reason), _) => reason.state(),
            (None, Some((status, _))) => State::parse(&status)?,
            (None, None) => State::Failed,
        };
        Ok(Outcome { status, exact })
    }
    fn cancelled_before_start(&self) -> Outcome {
        Outcome {
            status: State::Cancelled,
            exact: true,
        }
    }
    fn failed(&self) -> Outcome {
        Outcome {
            status: State::Failed,
            exact: false,
        }
    }
    fn finalize(&self, dir: &Path, outcome: Outcome, elapsed: Option<f64>) -> Result<Finalized> {
        let provenance = read(&dir.join("provenance.json"))?;
        let worker_digest = provenance["worker_digest"]
            .as_str()
            .ok_or("missing worker digest")?;
        // Invalid journals still seal the attempt as failed, without trusted
        // mathematical results or work totals, exactly as before extraction.
        let (state, mut run) = match result::manifest(
            dir,
            &self.request,
            outcome.status.as_str(),
            outcome.exact,
            elapsed.unwrap_or(0.0),
            worker_digest,
        ) {
            Ok(run) => (outcome.status, run),
            Err(error) => (
                State::Failed,
                result::unreadable_manifest(
                    &self.request,
                    elapsed.unwrap_or(0.0),
                    worker_digest,
                    &error.to_string(),
                ),
            ),
        };
        run["runner"]["attempt_id"] = provenance["attempt_id"].clone();
        run["runner"]["build"] = provenance["build"].clone();
        if elapsed.is_none() {
            run["elapsed_seconds"] = Value::Null;
        }
        write_atomic_json(&dir.join("run.json"), &run)?;
        let (bytes, sha256) = artifact::digest_file(&dir.join("run.json"))?;
        Ok(Finalized {
            state,
            native_result: Some(NativeResult {
                file: "run.json".into(),
                schema_version: run["schema_version"].clone(),
                bytes,
                sha256,
            }),
        })
    }
}

/// Called only after the existing repair path proves liveness is gone and
/// holds both locks. No observed exit code is invented after launcher loss.
/// `started` is whether `job.json` reached `running`, which the launcher
/// writes before it spawns the worker.
pub(crate) fn repair(dir: &Path, unadmitted: bool, started: bool) -> Result<()> {
    let adapter = Adapter::load(dir)?;
    let replayable = result::repair(dir, &adapter.request).is_ok();
    let (outcome, elapsed) = if unadmitted {
        (
            Outcome {
                status: State::Interrupted,
                exact: true,
            },
            Some(0.0),
        )
    } else if let Some((status, elapsed)) = replayable
        .then(|| result::worker_outcome(dir, &adapter.request))
        .transpose()?
        .flatten()
    {
        (
            Outcome {
                status: State::parse(&status)?,
                exact: true,
            },
            Some(elapsed),
        )
    } else {
        (
            Outcome {
                status: State::Interrupted,
                exact: false,
            },
            None,
        )
    };
    execution::finish(
        dir,
        &adapter,
        outcome,
        elapsed,
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
