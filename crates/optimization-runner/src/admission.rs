//! Locked node admission and conservative reconciliation. This is the single
//! resource authority for every local execution adapter.
use crate::{
    Stop, attempt_processes_gone, boot, capacity, directory, optional, read, stop_request,
};
use optimization_job_api::{
    Result,
    process::bounded_command,
    storage::{lock, write_atomic_json},
};
use serde_json::{Value, json};
use std::{fs, path::Path, time::Duration};

/// Drop reservations whose holders are provably gone: a previous boot, an
/// inactive systemd unit with an empty cgroup, or an attempt whose launcher
/// and worker locks are both free. Unknown liveness keeps the reservation.
pub(crate) fn reconcile_ledger(root: &Path, ledger: &mut Value) -> Result<()> {
    let current_boot = boot()?;
    let keys: Vec<String> = ledger
        .as_object()
        .ok_or("invalid ledger")?
        .keys()
        .cloned()
        .collect();
    for id in keys {
        let r = &ledger[&id];
        let old_boot = r["boot_id"].as_str().is_some_and(|b| b != current_boot);
        // A running service owns its reservation. A missing/unknown manager state is not proof of death.
        let stopped = if let Some(unit) = r["unit"].as_str() {
            let args = vec![
                "systemctl".into(),
                "--user".into(),
                "show".into(),
                unit.into(),
                "--property=ActiveState,ControlGroup".into(),
            ];
            match bounded_command(&args, vec![], Duration::from_secs(5), 16384) {
                Ok((s, out, _)) if s.success() => {
                    let v = String::from_utf8_lossy(&out);
                    let inactive = v
                        .lines()
                        .any(|x| x == "ActiveState=inactive" || x == "ActiveState=failed");
                    let cg = v.lines().find_map(|x| x.strip_prefix("ControlGroup="));
                    // Only accept manager-empty cgroup, or an explicitly unpopulated cgroup.events.
                    let empty = match cg {
                        Some("") => true,
                        Some(c) if c.starts_with('/') && !c.contains("..") => {
                            fs::read_to_string(format!("/sys/fs/cgroup{c}/cgroup.events"))
                                .map(|s| s.lines().any(|x| x == "populated 0"))
                                .unwrap_or(false)
                        }
                        _ => false,
                    };
                    inactive && empty
                }
                _ => false,
            }
        } else {
            false
        };
        // Foreground jobs have no unit; a launcher killed by SIGKILL (or a
        // closed terminal) would otherwise hold its slots until reboot.
        let gone = directory(root, &id)
            .map(|dir| attempt_processes_gone(&dir))
            .unwrap_or(false);
        if old_boot || stopped || gone {
            ledger.as_object_mut().unwrap().remove(&id);
        }
    }
    Ok(())
}
pub(crate) fn admit(root: &Path, id: &str, dir: &Path, slots: usize) -> Result<bool> {
    if stop_request(dir) != Stop::None {
        return Ok(false);
    }
    let _guard = lock(&root.join("slots.lock"))?;
    let mut ledger = optional(&root.join("slots.json"))?;
    reconcile_ledger(root, &mut ledger)?;
    let used = ledger
        .as_object()
        .ok_or("bad ledger")?
        .values()
        .try_fold(0u64, |s, v| {
            s.checked_add(v["slots"].as_u64().ok_or("bad slots")?)
                .ok_or("slots overflow")
        })?;
    if ledger.get(id).is_some() {
        return Err("attempt already reserved; refusing duplicate launch".into());
    }
    let accepted = used
        .checked_add(slots as u64)
        .is_some_and(|n| n <= capacity(root).unwrap_or(0));
    if accepted {
        let p = read(&dir.join("provenance.json"))?;
        ledger[id] = json!({"slots":slots,"boot_id":boot()?,"unit":p["unit"],"launcher_pid":std::process::id()});
    }
    write_atomic_json(&root.join("slots.json"), &ledger)?;
    Ok(accepted)
}
pub(crate) fn release(root: &Path, id: &str) -> Result<()> {
    let _g = lock(&root.join("slots.lock"))?;
    let mut l = optional(&root.join("slots.json"))?;
    l.as_object_mut().ok_or("invalid ledger")?.remove(id);
    write_atomic_json(&root.join("slots.json"), &l)?;
    Ok(())
}
