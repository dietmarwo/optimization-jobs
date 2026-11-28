//! Static resources and the Skills extension of the July MCP revision.
use super::{CACHE_MS, INVALID_PARAMS, Reply, apps};
use optimization_job_api::storage::digest;
use serde_json::{Value, json};
use std::sync::LazyLock;

pub(super) const SKILLS: &str = "io.modelcontextprotocol/skills";
const PAGE_SIZE: usize = 16;

pub(super) struct Resource {
    pub uri: &'static str,
    pub name: &'static str,
    pub description: Option<&'static str>,
    pub mime: &'static str,
    pub bytes: &'static [u8],
}

impl Resource {
    fn entry(&self) -> Value {
        let mut entry = json!({
            "uri": self.uri, "name": self.name, "mimeType": self.mime, "size": self.bytes.len(),
        });
        if let Some(description) = self.description {
            entry["description"] = json!(description);
        }
        entry
    }

    pub fn contents(&self) -> Value {
        let text = std::str::from_utf8(self.bytes).expect("embedded UTF-8 MCP resource");
        json!({"uri":self.uri,"mimeType":self.mime,"text":text})
    }
}

struct Skill {
    name: &'static str,
    description: &'static str,
    files: &'static [Resource],
}

impl Skill {
    fn entry(&self) -> Value {
        let resources: Vec<_> = self.files.iter().map(|file| {
            json!({"uri":file.uri,"size":file.bytes.len(),"digest":format!("sha256:{}",digest(file.bytes))})
        }).collect();
        json!({
            "uri": self.files[0].uri,
            "frontmatter": {"name":self.name,"description":self.description},
            "resources": resources,
        })
    }
}

macro_rules! resource {
    ($skill:literal, $file:literal, $name:expr, $description:expr) => {
        Resource {
            uri: concat!("skill://optimization-jobs/", $skill, "/", $file),
            name: $name,
            description: $description,
            mime: "text/markdown",
            bytes: include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/skills/",
                $skill,
                "/",
                $file
            )),
        }
    };
}

macro_rules! skill {
    ($name:literal, $description:literal, ["SKILL.md", $($file:literal,)+]) => {
        Skill {
            name: $name,
            description: $description,
            files: &[
                resource!($name, "SKILL.md", $name, Some($description)),
                $(resource!($name, $file, $file, None)),+
            ],
        }
    };
}
include!("../../skills/catalog.rs");

static ENTRIES: LazyLock<Vec<Value>> = LazyLock::new(|| CATALOG.iter().map(Skill::entry).collect());

pub(super) fn instructions() -> String {
    let uris = CATALOG
        .iter()
        .map(|s| s.files[0].uri)
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "{} Skills are available over skills/list at {uris}.",
        super::INSTRUCTIONS
    )
}

fn invalid(message: impl Into<String>) -> Reply {
    Reply::Err(INVALID_PARAMS, message.into(), None)
}

fn cached(mut data: Value) -> Reply {
    data["ttlMs"] = json!(CACHE_MS);
    data["cacheScope"] = json!("public");
    Reply::Ok(data)
}

fn page(entries: &[Value], params: &Value, field: &str, size: usize) -> Reply {
    let start = if let Some(cursor) = params.get("cursor") {
        let Some(start) = cursor
            .as_str()
            .and_then(|s| s.strip_prefix(field))
            .and_then(|s| s.strip_prefix(':'))
            .and_then(|s| s.parse::<usize>().ok().filter(|n| n.to_string() == s))
            .filter(|&n| n != 0 && n < entries.len() && n % size == 0)
        else {
            return invalid("unknown cursor");
        };
        start
    } else {
        0
    };
    let end = (start + size).min(entries.len());
    let mut data = json!({field: &entries[start..end]});
    if end < entries.len() {
        data["nextCursor"] = json!(format!("{field}:{end}"));
    }
    cached(data)
}

pub(super) fn dispatch(method: &str, params: &Value) -> Reply {
    let resources = || {
        CATALOG
            .iter()
            .flat_map(|skill| skill.files)
            .chain([&apps::RESOURCE])
    };
    match method {
        "skills/list" => page(&ENTRIES, params, "skills", PAGE_SIZE),
        "skills/get" => match params["uri"]
            .as_str()
            .and_then(|uri| ENTRIES.iter().find(|entry| entry["uri"] == uri))
        {
            Some(skill) => cached(json!({"skill":skill})),
            None => invalid("unknown skill URI"),
        },
        "resources/list" => {
            let entries: Vec<_> = resources().map(Resource::entry).collect();
            page(&entries, params, "resources", PAGE_SIZE)
        }
        "resources/templates/list" => page(&[], params, "resourceTemplates", PAGE_SIZE),
        "resources/read" => match params["uri"]
            .as_str()
            .and_then(|uri| resources().find(|file| file.uri == uri))
        {
            Some(file) => cached(json!({"contents":[file.contents()]})),
            None => invalid("unknown resource URI"),
        },
        _ => unreachable!("resource method"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn static_pages_validate_cursors() {
        let entries = [json!("a"), json!("b"), json!("c")];
        let Reply::Ok(first) = page(&entries, &json!({}), "skills", 2) else {
            panic!("expected a first page");
        };
        assert_eq!(first["skills"], json!(["a", "b"]));
        let Reply::Ok(second) = page(
            &entries,
            &json!({"cursor":first["nextCursor"]}),
            "skills",
            2,
        ) else {
            panic!("expected a second page");
        };
        assert_eq!(second["skills"], json!(["c"]));
        assert!(second.get("nextCursor").is_none());
        for cursor in [
            json!("skills:0"),
            json!("skills:3"),
            json!("resources:2"),
            Value::Null,
        ] {
            assert!(matches!(
                page(&entries, &json!({"cursor":cursor}), "skills", 2),
                Reply::Err(INVALID_PARAMS, _, None)
            ));
        }
    }
}
