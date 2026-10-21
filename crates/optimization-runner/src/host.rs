//! What the host gives this process, for `node doctor`: CPUs (online, the
//! affinity mask, the cgroup quota, physical cores, NUMA nodes) and memory
//! (total, available, the cgroup limit), read from /proc and /sys. Anything
//! unavailable is `None` (JSON null). The parsers are pure functions over the
//! text of those files, so they are tested with fixtures.
use serde::Serialize;
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};

/// The host as this process sees it.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct Host {
    /// Online CPUs (`/sys/devices/system/cpu/online`).
    pub logical_cpus: Option<usize>,
    /// CPUs in this process's affinity mask (`Cpus_allowed_list`).
    pub affinity_cpus: Option<usize>,
    /// The cgroup CPU quota in CPUs: the most restrictive on the path to the
    /// root of the hierarchy.
    pub cgroup_cpu_limit: Option<f64>,
    /// `max(1, floor(min(affinity, quota)))`.
    pub usable_cpus: Option<usize>,
    /// Distinct (package, core) pairs among the allowed CPUs.
    pub physical_cores: Option<usize>,
    pub numa_nodes: Option<usize>,
    pub memory_total_bytes: Option<u64>,
    pub memory_available_bytes: Option<u64>,
    /// The cgroup memory limit, the most restrictive on the path.
    pub cgroup_memory_limit_bytes: Option<u64>,
    /// `min(available, limit - current)` over the limited cgroups.
    pub usable_memory_bytes: Option<u64>,
}

/// CPUs this parser accepts in one list: a guard against absurd ranges.
const MAX_CPUS: usize = 1 << 16;
/// cgroup v1 reports "no memory limit" as about 2^63, rounded to a page.
const UNLIMITED: u64 = 1 << 62;

/// A CPU list such as `0-3,8,10-11` (sysfs `online`, `Cpus_allowed_list`).
pub fn cpu_list(text: &str) -> Option<BTreeSet<usize>> {
    let text = text.trim();
    if text.is_empty() {
        return None;
    }
    let mut cpus = BTreeSet::new();
    for part in text.split(',').map(str::trim) {
        let (first, last): (usize, usize) = match part.split_once('-') {
            Some((a, b)) => (a.parse().ok()?, b.parse().ok()?),
            None => {
                let cpu = part.parse().ok()?;
                (cpu, cpu)
            }
        };
        if first > last || last >= MAX_CPUS {
            return None;
        }
        cpus.extend(first..=last);
    }
    Some(cpus)
}

/// The CPUs of `Cpus_allowed_list` in /proc/self/status.
pub fn allowed_cpus(status: &str) -> Option<BTreeSet<usize>> {
    status
        .lines()
        .find_map(|line| line.strip_prefix("Cpus_allowed_list:"))
        .and_then(cpu_list)
}

fn quota_cpus(quota: f64, period: f64) -> Option<f64> {
    (quota > 0.0 && period > 0.0 && quota.is_finite() && period.is_finite()).then(|| quota / period)
}

/// The quota of cgroup v2 `cpu.max` (`200000 100000`) in CPUs; `None` for
/// `max` (no limit) or text that is not a quota.
pub fn cpu_max(text: &str) -> Option<f64> {
    let mut fields = text.split_whitespace();
    let quota = fields.next()?;
    let period = fields.next().map_or(Some(100_000.0), |p| p.parse().ok())?;
    if quota == "max" {
        return None;
    }
    quota_cpus(quota.parse().ok()?, period)
}

/// The quota of cgroup v1 `cpu.cfs_quota_us` and `cpu.cfs_period_us` in
/// CPUs; `None` for the quota -1 (no limit).
pub fn cfs_quota(quota: &str, period: &str) -> Option<f64> {
    let quota: i64 = quota.trim().parse().ok()?;
    let period: i64 = period.trim().parse().ok()?;
    quota_cpus(quota as f64, period as f64)
}

/// `MemTotal` and `MemAvailable` of /proc/meminfo, in bytes.
pub fn meminfo(text: &str) -> (Option<u64>, Option<u64>) {
    let field = |name: &str| {
        text.lines().find_map(|line| {
            let mut fields = line
                .strip_prefix(name)?
                .strip_prefix(':')?
                .split_whitespace();
            let value: u64 = fields.next()?.parse().ok()?;
            match fields.next() {
                Some("kB") => value.checked_mul(1024),
                None => Some(value),
                _ => None,
            }
        })
    };
    (field("MemTotal"), field("MemAvailable"))
}

/// A cgroup memory limit (v2 `memory.max`, v1 `memory.limit_in_bytes`) or
/// usage (`memory.current`, `memory.usage_in_bytes`) in bytes; `None` for
/// `max` and for the v1 value that means no limit.
pub fn memory_value(text: &str) -> Option<u64> {
    let text = text.trim();
    if text == "max" {
        return None;
    }
    text.parse::<u64>().ok().filter(|&n| n < UNLIMITED)
}

/// The cgroups of this process, from /proc/self/cgroup: the cgroup v2 path
/// and the v1 paths of the `cpu` and `memory` controllers.
#[derive(Debug, Default, PartialEq)]
pub struct Cgroups {
    pub unified: Option<String>,
    pub cpu: Option<String>,
    pub memory: Option<String>,
}

pub fn cgroups(text: &str) -> Cgroups {
    let mut found = Cgroups::default();
    for line in text.lines() {
        let mut fields = line.splitn(3, ':');
        let (Some(_), Some(controllers), Some(path)) =
            (fields.next(), fields.next(), fields.next())
        else {
            continue;
        };
        if controllers.is_empty() {
            found.unified = Some(path.to_owned());
        }
        for controller in controllers.split(',') {
            match controller {
                "cpu" => found.cpu = Some(path.to_owned()),
                "memory" => found.memory = Some(path.to_owned()),
                _ => {}
            }
        }
    }
    found
}

/// A cgroup path and its ancestors, the cgroup's own first: `/a/b` gives
/// `a/b`, `a` and the root (empty), relative to the hierarchy's mount.
pub fn ancestors(path: &str) -> Vec<String> {
    let parts: Vec<&str> = path.split('/').filter(|p| !p.is_empty()).collect();
    (0..=parts.len())
        .rev()
        .map(|n| parts[..n].join("/"))
        .collect()
}

/// `max(1, floor(min(affinity, quota)))` of the known values; the online
/// CPUs when neither is known.
pub fn usable_cpus(
    affinity: Option<usize>,
    quota: Option<f64>,
    logical: Option<usize>,
) -> Option<usize> {
    let known = [affinity.map(|n| n as f64), quota].into_iter().flatten();
    let least = known.reduce(f64::min).or(logical.map(|n| n as f64))?;
    Some((least.floor() as usize).max(1))
}

/// The memory a job can still use: `min(available, limit - current)` over
/// the cgroups with a limit (`current` unknown counts as 0).
pub fn usable_memory(available: Option<u64>, limits: &[(u64, Option<u64>)]) -> Option<u64> {
    let headroom = limits
        .iter()
        .map(|&(limit, current)| limit.saturating_sub(current.unwrap_or(0)));
    available.into_iter().chain(headroom).min()
}

/// The number of distinct (package, core) pairs, or `None` if the topology
/// of any CPU is unknown.
pub fn physical_cores(pairs: impl IntoIterator<Item = Option<(String, String)>>) -> Option<usize> {
    let mut cores = BTreeSet::new();
    for pair in pairs {
        cores.insert(pair?);
    }
    (!cores.is_empty()).then_some(cores.len())
}

/// The warnings of `node doctor` and `node init` for a node `capacity`.
pub fn warnings(capacity: Option<u64>, host: &Host) -> Vec<String> {
    let mut warnings = vec![];
    if let (Some(capacity), Some(usable)) = (capacity, host.usable_cpus)
        && capacity > usable as u64
    {
        warnings.push(format!(
            "capacity {capacity} exceeds the {usable} CPUs usable by this process (affinity or cgroup quota)"
        ));
    }
    warnings
}

fn read(path: impl AsRef<Path>) -> Option<String> {
    fs::read_to_string(path).ok()
}

/// The directories of a cgroup and its ancestors that exist below `base`, the
/// cgroup's own first. In a cgroup namespace or a container whose cgroup is
/// mounted as the root, the path is not visible below `base`; `base` itself
/// then holds the nearest limits.
fn levels(base: &Path, path: &str) -> Vec<PathBuf> {
    ancestors(path)
        .iter()
        .map(|relative| base.join(relative))
        .filter(|dir| dir.is_dir())
        .collect()
}

/// The cgroup v2 hierarchy: `/sys/fs/cgroup`, or `unified` below it on a
/// hybrid host.
fn unified_base() -> Option<PathBuf> {
    ["/sys/fs/cgroup", "/sys/fs/cgroup/unified"]
        .into_iter()
        .map(PathBuf::from)
        .find(|base| base.join("cgroup.controllers").is_file())
}

/// The cgroup v1 hierarchy of a controller (`cpu` may be mounted with
/// `cpuacct`).
fn v1_base(names: &[&str]) -> Option<PathBuf> {
    names
        .iter()
        .map(|name| Path::new("/sys/fs/cgroup").join(name))
        .find(|base| base.is_dir())
}

fn cpu_quota(groups: &Cgroups) -> Option<f64> {
    let quotas: Vec<f64> = if let (Some(path), Some(base)) =
        (&groups.cpu, v1_base(&["cpu", "cpu,cpuacct", "cpuacct,cpu"]))
    {
        levels(&base, path)
            .iter()
            .filter_map(|dir| {
                cfs_quota(
                    &read(dir.join("cpu.cfs_quota_us"))?,
                    &read(dir.join("cpu.cfs_period_us"))?,
                )
            })
            .collect()
    } else if let (Some(path), Some(base)) = (&groups.unified, unified_base()) {
        levels(&base, path)
            .iter()
            .filter_map(|dir| cpu_max(&read(dir.join("cpu.max"))?))
            .collect()
    } else {
        vec![]
    };
    quotas.into_iter().reduce(f64::min)
}

/// The memory limits on the path to the root, each with the cgroup's usage.
fn memory_limits(groups: &Cgroups) -> Vec<(u64, Option<u64>)> {
    let (dirs, limit, current) =
        if let (Some(path), Some(base)) = (&groups.memory, v1_base(&["memory"])) {
            (
                levels(&base, path),
                "memory.limit_in_bytes",
                "memory.usage_in_bytes",
            )
        } else if let (Some(path), Some(base)) = (&groups.unified, unified_base()) {
            (levels(&base, path), "memory.max", "memory.current")
        } else {
            return vec![];
        };
    dirs.iter()
        .filter_map(|dir| {
            let limit = memory_value(&read(dir.join(limit))?)?;
            Some((
                limit,
                read(dir.join(current)).and_then(|t| memory_value(&t)),
            ))
        })
        .collect()
}

/// Reads the host from /proc and /sys.
pub fn host() -> Host {
    let online = read("/sys/devices/system/cpu/online").and_then(|t| cpu_list(&t));
    let allowed = read("/proc/self/status").and_then(|t| allowed_cpus(&t));
    let groups = read("/proc/self/cgroup")
        .map(|t| cgroups(&t))
        .unwrap_or_default();
    let quota = cpu_quota(&groups);
    let cpus = allowed.as_ref().or(online.as_ref());
    let physical = cpus.and_then(|cpus| {
        physical_cores(cpus.iter().map(|cpu| {
            let topology = PathBuf::from(format!("/sys/devices/system/cpu/cpu{cpu}/topology"));
            let package = read(topology.join("physical_package_id"))?;
            let core = read(topology.join("core_id"))?;
            Some((package.trim().to_owned(), core.trim().to_owned()))
        }))
    });
    let numa = fs::read_dir("/sys/devices/system/node")
        .ok()
        .map(|entries| {
            entries
                .flatten()
                .filter(|e| {
                    e.file_name()
                        .to_str()
                        .and_then(|n| n.strip_prefix("node"))
                        .is_some_and(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()))
                })
                .count()
        });
    let (total, available) = read("/proc/meminfo")
        .map(|t| meminfo(&t))
        .unwrap_or_default();
    let limits = memory_limits(&groups);
    let (logical, affinity) = (online.map(|c| c.len()), allowed.map(|c| c.len()));
    Host {
        logical_cpus: logical,
        affinity_cpus: affinity,
        cgroup_cpu_limit: quota,
        usable_cpus: usable_cpus(affinity, quota, logical),
        physical_cores: physical,
        numa_nodes: numa.filter(|&n| n > 0),
        memory_total_bytes: total,
        memory_available_bytes: available,
        cgroup_memory_limit_bytes: limits.iter().map(|&(limit, _)| limit).min(),
        usable_memory_bytes: usable_memory(available, &limits),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cpu_lists() {
        let cpus = cpu_list("0-3,8,10-11\n").unwrap();
        assert_eq!(
            cpus.into_iter().collect::<Vec<_>>(),
            [0, 1, 2, 3, 8, 10, 11]
        );
        assert_eq!(cpu_list("5").unwrap().len(), 1);
        for bad in ["", "3-1", "a", "0-", "0-99999999"] {
            assert_eq!(cpu_list(bad), None, "{bad:?}");
        }
        let status =
            "Name:\tcat\nCpus_allowed:\tff\nCpus_allowed_list:\t0-1,4\nMems_allowed_list:\t0\n";
        assert_eq!(allowed_cpus(status).unwrap().len(), 3);
        assert_eq!(allowed_cpus("Name:\tcat\n"), None);
    }

    #[test]
    fn cpu_quotas() {
        assert_eq!(cpu_max("max 100000\n"), None);
        assert_eq!(cpu_max("200000 100000\n"), Some(2.0));
        assert_eq!(cpu_max("150000 100000"), Some(1.5));
        assert_eq!(cpu_max(""), None);
        assert_eq!(cfs_quota("-1\n", "100000\n"), None);
        assert_eq!(cfs_quota("400000\n", "100000\n"), Some(4.0));
        assert_eq!(cfs_quota("50000", "0"), None);
    }

    #[test]
    fn memory() {
        let text = "MemTotal:        8222320 kB\nMemFree:         6479216 kB\nMemAvailable:    7514380 kB\n";
        assert_eq!(
            meminfo(text),
            (Some(8_222_320 * 1024), Some(7_514_380 * 1024))
        );
        assert_eq!(meminfo("MemTotal: 1 MB\n"), (None, None));
        assert_eq!(memory_value("max\n"), None);
        assert_eq!(memory_value("6272172032\n"), Some(6_272_172_032));
        // cgroup v1 without a limit.
        assert_eq!(memory_value("9223372036854771712\n"), None);
        assert_eq!(
            usable_memory(Some(100), &[(80, Some(30)), (60, None)]),
            Some(50)
        );
        assert_eq!(usable_memory(Some(10), &[(80, Some(30))]), Some(10));
        assert_eq!(usable_memory(None, &[(80, Some(90))]), Some(0));
        assert_eq!(usable_memory(None, &[]), None);
    }

    #[test]
    fn cgroup_paths() {
        let v2 = cgroups("0::/user.slice/user-1000.slice/session-2.scope\n");
        assert_eq!(
            v2.unified.as_deref(),
            Some("/user.slice/user-1000.slice/session-2.scope")
        );
        assert_eq!((v2.cpu, v2.memory), (None, None));
        assert_eq!(
            ancestors("/user.slice/user-1000.slice/session-2.scope"),
            [
                "user.slice/user-1000.slice/session-2.scope",
                "user.slice/user-1000.slice",
                "user.slice",
                ""
            ]
        );
        assert_eq!(ancestors("/"), [""]);
        let v1 = cgroups("12:cpu,cpuacct:/docker/abc\n4:memory:/docker/abc\n0::/\n");
        assert_eq!(
            (
                v1.cpu.as_deref(),
                v1.memory.as_deref(),
                v1.unified.as_deref()
            ),
            (Some("/docker/abc"), Some("/docker/abc"), Some("/"))
        );
    }

    #[test]
    fn usable_cpus_and_warnings() {
        assert_eq!(usable_cpus(Some(8), Some(2.5), Some(64)), Some(2));
        assert_eq!(usable_cpus(Some(8), None, Some(64)), Some(8));
        assert_eq!(usable_cpus(None, Some(0.5), None), Some(1));
        assert_eq!(usable_cpus(None, None, Some(4)), Some(4));
        assert_eq!(usable_cpus(None, None, None), None);
        let pairs = ["0:0", "0:1", "0:0", "1:0"]
            .map(|p| p.split_once(':').map(|(a, b)| (a.to_owned(), b.to_owned())));
        assert_eq!(physical_cores(pairs), Some(3));
        assert_eq!(physical_cores([None]), None);
        let host = Host {
            usable_cpus: Some(8),
            ..Host::default()
        };
        assert_eq!(
            warnings(Some(64), &host),
            ["capacity 64 exceeds the 8 CPUs usable by this process (affinity or cgroup quota)"]
        );
        assert!(warnings(Some(8), &host).is_empty());
        assert!(warnings(None, &host).is_empty());
    }

    #[test]
    fn this_host() {
        let host = host();
        let json = serde_json::to_value(&host).unwrap();
        assert_eq!(json.as_object().unwrap().len(), 10);
        if Path::new("/sys/devices/system/cpu/online").exists() {
            assert!(host.logical_cpus.is_some_and(|n| n >= 1));
            assert!(host.usable_cpus.is_some_and(|n| n >= 1));
        }
    }
}
