use super::*;
use crate::boot;
use tempfile::TempDir;

/// A test-only adapter. It has no optimization request, SDK, journal or native
/// result. It is deliberately not registered in the CLI or capabilities.
struct Neutral {
    executable: &'static str,
    args: &'static [&'static str],
}
impl Adapter for Neutral {
    type Outcome = State;
    fn kind(&self) -> &'static str {
        "fixture"
    }
    fn budget(&self) -> Budget {
        Budget {
            cpu_slots: 1,
            wall: Duration::from_millis(80),
            grace: Duration::ZERO,
        }
    }
    fn command(&self, _: &Path) -> Result<Command> {
        let mut command = Command::new(self.executable);
        command.args(self.args);
        Ok(command)
    }
    fn completed(&self, _: &Path, observed: &Observation) -> Result<State> {
        Ok(match observed.stop_reason {
            Some(reason) => reason.state(),
            None if observed
                .process
                .as_ref()
                .is_some_and(|exit| exit.code == Some(0)) =>
            {
                State::Completed
            }
            None => State::Failed,
        })
    }
    fn cancelled_before_start(&self) -> State {
        State::Cancelled
    }
    fn failed(&self) -> State {
        State::Failed
    }
    fn finalize(&self, _: &Path, state: State, _: Option<f64>) -> Result<Finalized> {
        Ok(Finalized {
            state,
            native_result: None,
        })
    }
}

const ID: &str = "0123456789abcdef0123456789abcdef";
fn node() -> (TempDir, std::path::PathBuf) {
    let root = tempfile::tempdir().unwrap();
    let dir = root.path().join("jobs").join(ID);
    fs::create_dir_all(&dir).unwrap();
    write_atomic_json(&root.path().join("node.json"), &json!({"capacity":1})).unwrap();
    write_atomic_json(&root.path().join("slots.json"), &json!({})).unwrap();
    write_atomic_json(
        &root.path().join("requests.json"),
        &json!({ID:{"directory":dir}}),
    )
    .unwrap();
    write_atomic_json(
        &dir.join("provenance.json"),
        &json!({
            "attempt_id":ID,"identity":"0".repeat(64),"boot_id":boot().unwrap(),"unit":null
        }),
    )
    .unwrap();
    write_atomic_json(
        &dir.join("job.json"),
        &json!({"id":ID,"state":"submitted","boot_id":boot().unwrap()}),
    )
    .unwrap();
    (root, dir)
}
fn no_mathematics(value: &Value) {
    if let Some(object) = value.as_object() {
        for (key, nested) in object {
            assert!(!["objective", "feasible", "claim", "results", "work"].contains(&key.as_str()));
            no_mathematics(nested);
        }
    }
}

#[test]
fn neutral_adapter_uses_the_lifecycle_without_optimization_output() {
    for (executable, state, code) in [("/bin/true", "completed", 0), ("/bin/false", "failed", 1)] {
        let (root, dir) = node();
        launch(root.path(), ID, |_| {
            Ok(Neutral {
                executable,
                args: &[],
            })
        })
        .unwrap();
        let record = record(&dir).unwrap();
        assert_eq!(record["state"], state);
        assert_eq!(record["kind"], "fixture");
        assert_eq!(record["observation"]["process"]["code"], code);
        assert_eq!(record["observation"]["containment"], "stopped");
        assert!(record["native_result"].is_null());
        no_mathematics(&record);
        assert!(!dir.join("run.json").exists());
        assert!(!dir.join("results.jsonl").exists());
        assert_eq!(read(&root.path().join("slots.json")).unwrap(), json!({}));
        assert_eq!(read(&dir.join("job.json")).unwrap()["state"], state);
        assert!(
            launch(root.path(), ID, |_| Ok(Neutral {
                executable,
                args: &[]
            }))
            .is_err()
        );
    }
}

#[test]
fn neutral_deadline_stops_the_process_and_releases_capacity() {
    let (root, dir) = node();
    launch(root.path(), ID, |_| {
        Ok(Neutral {
            executable: "/bin/sleep",
            args: &["30"],
        })
    })
    .unwrap();
    let record = record(&dir).unwrap();
    assert_eq!(record["state"], "timed_out");
    assert_eq!(record["observation"]["stop_reason"], "timed_out");
    assert_eq!(record["observation"]["process"]["signal"], libc::SIGKILL);
    assert_eq!(record["observation"]["containment"], "stopped");
    assert_eq!(read(&root.path().join("slots.json")).unwrap(), json!({}));
}

#[test]
fn queued_cancellation_does_not_create_a_process_or_native_result() {
    let (root, dir) = node();
    write_atomic_json(&dir.join("cancel.request"), &json!({"mode":"immediate"})).unwrap();
    launch(root.path(), ID, |_| {
        Ok(Neutral {
            executable: "/bin/true",
            args: &[],
        })
    })
    .unwrap();
    let record = record(&dir).unwrap();
    assert_eq!(record["state"], "cancelled");
    assert_eq!(record["observation"]["containment"], "not_started");
    assert_eq!(record["observation"]["stop_reason"], "cancelled");
    assert!(record["observation"]["process"].is_null());
    assert!(record["logs"]["stdout"].is_null());
    assert!(!dir.join("worker-process.json").exists());
    assert!(!dir.join("run.json").exists());
}

#[test]
fn spawn_failure_is_recorded_without_inventing_an_exit_code() {
    let (root, dir) = node();
    assert!(
        launch(root.path(), ID, |_| Ok(Neutral {
            executable: "/missing/p1-fixture",
            args: &[]
        }))
        .is_err()
    );
    let record = record(&dir).unwrap();
    assert_eq!(record["state"], "failed");
    assert_eq!(record["observation"]["containment"], "not_started");
    assert!(record["observation"]["process"].is_null());
    assert_eq!(read(&root.path().join("slots.json")).unwrap(), json!({}));
}

#[test]
fn process_record_write_failure_still_stops_the_spawned_process() {
    let (root, dir) = node();
    fs::create_dir(dir.join("worker-process.json")).unwrap();
    assert!(
        launch(root.path(), ID, |_| Ok(Neutral {
            executable: "/bin/sleep",
            args: &["30"]
        }))
        .is_err()
    );
    let record = record(&dir).unwrap();
    assert_eq!(record["state"], "failed");
    assert_eq!(record["observation"]["containment"], "stopped");
    assert_eq!(record["observation"]["process"]["signal"], libc::SIGKILL);
    assert_eq!(read(&root.path().join("slots.json")).unwrap(), json!({}));
}

#[test]
fn embedded_execution_schemas_match_the_published_files() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    for (name, embedded) in [
        (
            "execution.record-0.1.schema.json",
            include_str!("../../schemas/execution.record-0.1.schema.json"),
        ),
        (
            "execution.capabilities-0.1.schema.json",
            include_str!("../../schemas/execution.capabilities-0.1.schema.json"),
        ),
    ] {
        let published = root.join("../../docs/job-api/schemas").join(name);
        if published.exists() {
            assert_eq!(embedded, fs::read_to_string(published).unwrap());
        }
        serde_json::from_str::<Value>(embedded).unwrap();
    }
}
