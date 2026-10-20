use optimization_job_api::{artifact::*, storage::*};
use serde_json::{Value, json};
use std::fs;

#[test]
fn declarations_are_checked_unique_and_idempotent() {
    let d = tempfile::tempdir().unwrap();
    let log = Declaration::records("log-0", "log-0.jsonl")
        .task(0)
        .describe("Evaluation log");
    declare(d.path(), &log).unwrap();
    declare(d.path(), &log).unwrap();
    assert_eq!(declarations(d.path()).unwrap(), vec![log.clone()]);
    // The same name or file again, differently: refused.
    assert!(declare(d.path(), &Declaration::json("log-0", "other.json")).is_err());
    assert!(declare(d.path(), &Declaration::json("other", "log-0.jsonl")).is_err());
    for bad in [
        Declaration::json(RESULTS, "r.json"),
        Declaration::json("a/b", "x.json"),
        Declaration::json("x", "../x.json"),
        Declaration::json("x", "run.json"),
        Declaration::json("x", "inputs"),
        Declaration::json("x", ".hidden"),
        Declaration::json("x", "state.lock"),
        Declaration::json("x", "partial.tmp"),
        Declaration {
            format: "binary".into(),
            ..Declaration::json("x", "x.bin")
        },
        Declaration::json("x", "x.json").describe("a\nb"),
        Declaration::json("x", "x.json").describe("x".repeat(MAX_DESCRIPTION + 1)),
    ] {
        assert!(declare(d.path(), &bad).is_err(), "{bad:?}");
    }
    let all = all(d.path()).unwrap();
    assert_eq!(
        all.iter().map(|d| d.name.as_str()).collect::<Vec<_>>(),
        [RESULTS, "log-0"]
    );
    // A forged duplicate in the file makes every declaration untrusted.
    append_checked(&d.path().join(DECLARATIONS), 1, &log.clone().task(1)).unwrap();
    assert!(declarations(d.path()).is_err());
}

#[test]
fn concurrent_declarations_from_tasks() {
    let d = tempfile::tempdir().unwrap();
    std::thread::scope(|s| {
        for t in 0..8 {
            let dir = d.path();
            s.spawn(move || {
                for i in 0..10 {
                    let name = format!("a-{t}-{i}");
                    declare(
                        dir,
                        &Declaration::json(&name, format!("{name}.json")).task(t),
                    )
                    .unwrap();
                }
            });
        }
    });
    assert_eq!(declarations(d.path()).unwrap().len(), 80);
}

#[test]
fn sealing_indexes_existing_regular_files_with_digests() {
    let d = tempfile::tempdir().unwrap();
    let dir = d.path();
    append_checked(&dir.join("results.jsonl"), 1, &json!({"task_id":0})).unwrap();
    declare(dir, &Declaration::records("log", "log.jsonl").task(0)).unwrap();
    declare(dir, &Declaration::json("snapshot", "snapshot.json")).unwrap();
    declare(dir, &Declaration::json("never", "never.json")).unwrap();
    declare(dir, &Declaration::json("link", "link.json")).unwrap();
    append_checked(&dir.join("log.jsonl"), 1, &json!({"x":[1.0]})).unwrap();
    write_atomic_json(&dir.join("snapshot.json"), &json!({"points":[]})).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(dir.join("snapshot.json"), dir.join("link.json")).unwrap();
    let (files, index, errors) = sealed(dir);
    assert_eq!(
        files,
        json!({"results":"results.jsonl","log":"log.jsonl","snapshot":"snapshot.json"})
    );
    let bytes = fs::read(dir.join("snapshot.json")).unwrap();
    assert_eq!(index["snapshot"]["sha256"], json!(digest(&bytes)));
    assert_eq!(index["snapshot"]["bytes"], json!(bytes.len()));
    assert_eq!(index["log"]["format"], json!("records"));
    assert_eq!(index["log"]["task_id"], json!(0));
    #[cfg(unix)]
    assert_eq!(errors.len(), 1, "{errors:?}");
    let (progress, _) = progress(dir);
    assert_eq!(progress["log"]["bytes"], index["log"]["bytes"]);
    assert!(progress["log"].get("sha256").is_none());
    // A broken declaration file leaves the results artifact and an error.
    fs::write(dir.join(DECLARATIONS), b"garbage\n").unwrap();
    let (files, _, errors) = sealed(dir);
    assert_eq!(files, json!({"results":"results.jsonl"}));
    assert_eq!(errors.len(), 1);
}

#[test]
fn pages_hold_complete_checked_records_within_the_cap() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("log.jsonl");
    for i in 0..25 {
        append_checked(&p, 1, &json!({"id":i})).unwrap();
    }
    // A record being appended is not visible yet.
    let mut data = fs::read(&p).unwrap();
    data.extend_from_slice(b"{\"schema_version\":1,\"chec");
    fs::write(&p, &data).unwrap();
    let first = page(&p, 0, 10).unwrap();
    assert_eq!(first["available"], json!(25));
    assert_eq!(first["next_offset"], json!(10));
    assert_eq!(first["records"][3], json!({"id":3}));
    let last = page(&p, 20, 10).unwrap();
    assert_eq!(last["records"].as_array().unwrap().len(), 5);
    assert_eq!(last["next_offset"], json!(25));
    assert_eq!(page(&p, 99, 10).unwrap()["next_offset"], json!(25));
    assert!(page(&p, 0, 0).is_err() && page(&p, 0, MAX_PAGE + 1).is_err());
    let whole = content(&p, "records").unwrap();
    assert!(whole["content"].as_str().unwrap().ends_with('\n'));
    assert_eq!(whole["content"].as_str().unwrap().lines().count(), 25);
    // A corrupted record is an error, not a silently shorter page.
    let text = fs::read_to_string(&p)
        .unwrap()
        .replace("\\\"id\\\":2}", "\\\"id\\\":9}");
    fs::write(&p, text).unwrap();
    assert!(page(&p, 0, 10).is_err());
    assert_eq!(page(&p, 10, 10).unwrap()["records"][0], json!({"id":10}));
    // Pages stop at the inline cap and say where to continue.
    let big = d.path().join("big.jsonl");
    let text = "x".repeat(400_000);
    for _ in 0..4 {
        append_checked(&big, 1, &json!({"text":text})).unwrap();
    }
    let p1 = page(&big, 0, 100).unwrap();
    assert_eq!(p1["records"].as_array().unwrap().len(), 2);
    assert_eq!(p1["next_offset"], json!(2));
    assert!(content(&big, "records").is_err());
    let huge = d.path().join("huge.jsonl");
    append_checked(&huge, 1, &json!({"text":"x".repeat(INLINE_CAP)})).unwrap();
    assert!(page(&huge, 0, 1).is_err());
    let _: Vec<Value> = read_checked(&big, 1).unwrap();
}
