//! Read-only App projection of a sealed, selected task result.
use super::{Ctx, Server, resources::Resource, tools};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use tools::{Fail, fail};

pub(super) const EXTENSION: &str = "io.modelcontextprotocol/ui";
pub(super) const VIEW: &str = "view_result";
pub(super) const PAGE: &str = "view_result_page";
const URI: &str = "ui://optimization-jobs/job-result.html";
const PAGE_SIZE: usize = 128;
const DESCRIPTOR_COLUMNS: usize = 4;

pub(super) static RESOURCE: Resource = Resource {
    uri: URI,
    name: "Optimization result viewer",
    description: Some("Inspect MODE Pareto fronts and MAP-Elites archives."),
    mime: "text/html;profile=mcp-app",
    bytes: include_bytes!("../../apps/job-result.html"),
};

pub(super) fn definition(paging: bool) -> Value {
    let mut properties = json!({
        "job_id": tools::job_id_property(),
        "task_id": {"type":"integer","minimum":0,"description":"Task ID from get_result."},
        "axes": {"type":"array","minItems":2,"maxItems":2,"uniqueItems":true,
                 "items":{"type":"integer","minimum":0},
                 "description":"Two zero-based objective indices for MODE. Default [0,1]."},
    });
    let (name, meta, title, description) = if paging {
        properties["offset"] = json!({"type":"integer","minimum":0});
        (
            PAGE,
            json!({"visibility":["app"]}),
            "Page through result points",
            "Read one page of the selected optimization result for the result viewer.",
        )
    } else {
        (
            VIEW,
            json!({"resourceUri":URI}),
            "View an optimization result",
            "A read-only view and text summary of one committed task. Visualizes a MODE front or MAP-Elites archive on supporting hosts.",
        )
    };
    json!({
        "name": name, "title": title, "description": description,
        "_meta": {"ui":meta},
        "annotations": {"readOnlyHint":true,"openWorldHint":false},
        "inputSchema":{"type":"object","properties":properties,
                       "required":["job_id","task_id"],"additionalProperties":false},
    })
}

#[derive(Default, Deserialize)]
struct Outcome<'a> {
    #[serde(default)]
    claim: Value,
    #[serde(default)]
    termination: Value,
    #[serde(default)]
    evidence: Value,
    #[serde(borrow, default)]
    details: Details<'a>,
}

#[derive(Default, Deserialize)]
struct Details<'a> {
    #[serde(borrow, default)]
    front: Vec<&'a RawValue>,
    #[serde(borrow, default)]
    elites: Vec<&'a RawValue>,
    #[serde(default)]
    objectives: usize,
    #[serde(default)]
    front_source: Value,
    #[serde(default)]
    hypervolume: Value,
    #[serde(default)]
    archive_kind: Value,
    #[serde(default)]
    grid: Value,
    #[serde(default)]
    descriptor_lower: Vec<f64>,
    #[serde(default)]
    descriptor_upper: Vec<f64>,
    #[serde(default)]
    capacity: Value,
    #[serde(default)]
    coverage: Value,
    #[serde(default)]
    qd_score: Value,
    #[serde(default)]
    generations: Value,
    #[serde(default)]
    requested_generations: Value,
}

#[derive(Deserialize)]
struct Point {
    objectives: Vec<f64>,
}

#[derive(Deserialize)]
struct Elite {
    niche: u64,
    fitness: f64,
    descriptor: Vec<f64>,
}

fn invalid(message: &str) -> Fail {
    fail("invalid_arguments", message)
}

fn unreadable(error: serde_json::Error) -> Fail {
    fail("runner_error", format!("unreadable task result: {error}"))
}

fn axes(args: &Value, dimensions: usize) -> Result<[usize; 2], Fail> {
    let invalid_axes = || invalid("axes must be two distinct objective indices in range");
    let chosen = match args.get("axes") {
        None => [0, 1],
        Some(value) => serde_json::from_value(value.clone()).map_err(|_| invalid_axes())?,
    };
    if chosen[0] == chosen[1] || chosen.iter().any(|&axis| axis >= dimensions) {
        return Err(invalid_axes());
    }
    Ok(chosen)
}

fn slice<T>(entries: &[T], offset: usize) -> Result<&[T], Fail> {
    if offset != 0 && offset >= entries.len() {
        return Err(invalid("offset is outside the result"));
    }
    Ok(&entries[offset..offset.saturating_add(PAGE_SIZE).min(entries.len())])
}

fn mode(details: &Details<'_>, offset: usize, args: &Value) -> Result<Value, Fail> {
    let total = details.front.len();
    let dimension = details.objectives;
    if dimension < 2 && total == 0 {
        return Ok(json!({"kind":"mode","front_source":details.front_source,"items":[],"total":0}));
    }
    let axes = axes(args, dimension)?;
    let mut page = Vec::new();
    for entry in slice(&details.front, offset)? {
        let point: Point = serde_json::from_str(entry.get()).map_err(unreadable)?;
        if point.objectives.len() != dimension {
            return Err(fail(
                "runner_error",
                "inconsistent MODE objective dimension",
            ));
        }
        page.push([point.objectives[axes[0]], point.objectives[axes[1]]]);
    }
    let hv = &details.hypervolume;
    let reference: Vec<_> = axes
        .iter()
        .filter_map(|&axis| hv["reference_point"][axis].as_f64())
        .collect();
    Ok(json!({
        "kind":"mode","front_source":details.front_source,"axes":axes,"objective_count":dimension,
        "hypervolume":{"value":hv["value"],"method":hv["method"],"exact":hv["exact"],"dimension":dimension,
                       "reference":reference, "standard_error":hv["standard_error"]},
        "items":page,"total":total,
    }))
}

fn map_elites(details: &Details<'_>, offset: usize) -> Result<Value, Fail> {
    let total = details.elites.len();
    let dimensions = details.descriptor_lower.len();
    let mut page = Vec::new();
    for entry in slice(&details.elites, offset)? {
        let mut elite: Elite = serde_json::from_str(entry.get()).map_err(unreadable)?;
        elite.descriptor.truncate(DESCRIPTOR_COLUMNS);
        page.push(
            json!({"niche":elite.niche,"fitness":elite.fitness,"descriptor":elite.descriptor}),
        );
    }
    let grid = if dimensions == 2 && details.archive_kind == "grid" {
        details.grid.clone()
    } else {
        Value::Null
    };
    Ok(json!({
        "kind":"map-elites","archive_kind":details.archive_kind,"grid":grid,
        "descriptor_count":dimensions,"descriptor_lower":details.descriptor_lower.iter().take(2).collect::<Vec<_>>(),
        "descriptor_upper":details.descriptor_upper.iter().take(2).collect::<Vec<_>>(),
        "capacity":details.capacity,"coverage":details.coverage,"qd_score":details.qd_score,
        "items":page,"total":total,
    }))
}

pub(super) fn view(server: &Server, args: &Value, ctx: &Ctx, paging: bool) -> Result<Value, Fail> {
    if args
        .as_object()
        .expect("tool arguments are an object")
        .keys()
        .any(|key| {
            !(matches!(key.as_str(), "job_id" | "task_id" | "axes") || paging && key == "offset")
        })
    {
        return Err(invalid("unknown result-view argument"));
    }
    let job_id = tools::job_id(args)?;
    let task_id = args["task_id"]
        .as_u64()
        .ok_or_else(|| invalid("task_id must be a non-negative integer"))?;
    let offset = match args.get("offset") {
        Some(value) => value
            .as_u64()
            .and_then(|offset| usize::try_from(offset).ok())
            .ok_or_else(|| invalid("offset must be a non-negative integer"))?,
        None => 0,
    };
    let job = server.get(&job_id, ctx)?;
    let bytes = tools::read_manifest(&job).map_err(Fail::Tool)?;
    let (profile, record) = tools::result_record(&bytes, task_id)?;
    #[derive(Deserialize)]
    struct Task<'a> {
        #[serde(borrow, default)]
        outcome: Outcome<'a>,
    }
    let task: Task<'_> = serde_json::from_str(record.get()).map_err(unreadable)?;
    let outcome = task.outcome;
    let details = outcome.details;
    let profile_name = profile.as_str().unwrap_or("optimization");
    let label = match profile_name {
        "fcmaes.mode/1" => "MODE Pareto front",
        "fcmaes.map-elites/1" => "MAP-Elites archive",
        _ => "Optimization result",
    };
    let state = job["state"].as_str().unwrap_or("unknown");
    let claim = outcome.claim.as_str().unwrap_or("unavailable");
    let termination = outcome.termination.as_str().unwrap_or("unavailable");
    let evidence = outcome.evidence["level"].as_str().unwrap_or("unavailable");
    let mut data = match profile_name {
        "fcmaes.mode/1" => mode(&details, offset, args)?,
        "fcmaes.map-elites/1" => map_elites(&details, offset)?,
        _ => json!({"kind":"summary","total":0,"items":[]}),
    };
    let total = data["total"].as_u64().unwrap_or(0);
    let displayed = data["items"].as_array().map_or(0, Vec::len);
    let summary = format!(
        "{label} for job {job_id}, task {task_id}. Job {state}. Claim {claim}, termination {termination}, evidence {evidence}. Showing {displayed} of {total} entries. Inspect the selected task with get_result for its full evidence."
    );
    data["job_id"] = json!(job_id);
    data["task_id"] = json!(task_id);
    data["state"] = json!(state);
    data["claim"] = json!(claim);
    data["termination"] = json!(termination);
    data["evidence"] = json!(evidence);
    data["label"] = json!(label);
    data["generations"] = details.generations;
    data["requested_generations"] = details.requested_generations;
    data["offset"] = json!(offset);
    data["page_size"] = json!(PAGE_SIZE);
    Ok(json!({
        "content":[{"type":"text","text":summary}],
        "structuredContent":data,
        "isError":false,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_empty_mode_front_has_no_invented_hypervolume() {
        let details = Details {
            objectives: 3,
            front_source: json!("final_population"),
            ..Details::default()
        };
        let empty = mode(&details, 0, &json!({"axes":[0,2]}))
            .ok()
            .expect("a valid projection of an empty front");
        assert_eq!(empty["items"], json!([]));
        assert_eq!(empty["total"], 0);
        assert_eq!(empty["axes"], json!([0, 2]));
        assert!(empty["hypervolume"]["value"].is_null());
        assert!(mode(&details, 0, &json!({"axes":[0,3]})).is_err());
    }
}
