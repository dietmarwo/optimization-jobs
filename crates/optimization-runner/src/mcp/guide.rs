//! `get_guide`: the entry point for agents, `ai-context.md` of this
//! repository, which chooses among the solvers before any worker or profile
//! is chosen. MCP-only clients cannot read the repository, so the server
//! carries a copy (`guide/ai-context.md` inside the crate, so the published
//! package builds on its own; a test keeps it identical).
use super::tools::{self, Fail};
use serde_json::{Value, json};

pub const GUIDE: &str = include_str!("../../guide/ai-context.md");
const NAME: &str = "ai-context.md";
/// What the guide's relative links resolve against.
const BASE_URL: &str = "https://github.com/dietmarwo/optimization-jobs/blob/main/";

/// An ATX heading (`#` to `######`) outside fenced code blocks: its byte
/// offset in the text, its level and its text.
#[derive(Debug, PartialEq)]
pub struct Heading {
    pub offset: usize,
    pub level: usize,
    pub text: String,
}

/// The level and text of a heading line, if it is one.
fn heading(line: &str) -> Option<(usize, String)> {
    let indent = line.len() - line.trim_start_matches(' ').len();
    let rest = &line[indent..];
    let level = rest.len() - rest.trim_start_matches('#').len();
    if indent > 3 || !(1..=6).contains(&level) {
        return None;
    }
    let rest = &rest[level..];
    if !(rest.is_empty() || rest.starts_with([' ', '\t'])) {
        return None;
    }
    // An optional closing sequence of #s.
    let text = rest.trim();
    let closed = text.trim_end_matches('#');
    let text = if closed.is_empty() || closed.ends_with([' ', '\t']) {
        closed.trim_end()
    } else {
        text
    };
    Some((level, text.to_owned()))
}

/// The headings of a Markdown text, skipping fenced code blocks, whose
/// lines may start with `#` too (shell comments).
pub fn headings(text: &str) -> Vec<Heading> {
    let mut found = vec![];
    let mut fence: Option<(char, usize)> = None;
    let mut offset = 0;
    for line in text.split_inclusive('\n') {
        let start = offset;
        offset += line.len();
        let line = line.trim_end_matches(['\n', '\r']);
        let trimmed = line.trim_start_matches(' ');
        let marker = trimmed.chars().next().filter(|c| *c == '`' || *c == '~');
        let run = marker.map_or(0, |c| trimmed.len() - trimmed.trim_start_matches(c).len());
        match (fence, marker) {
            (None, Some(c)) if run >= 3 && line.len() - trimmed.len() <= 3 => {
                fence = Some((c, run));
                continue;
            }
            (Some((c, n)), Some(m))
                if m == c && run >= n && trimmed.trim_start_matches(c).trim().is_empty() =>
            {
                fence = None;
                continue;
            }
            (Some(_), _) => continue,
            _ => {}
        }
        if let Some((level, text)) = heading(line) {
            found.push(Heading {
                offset: start,
                level,
                text,
            });
        }
    }
    found
}

/// The first section whose heading contains `query`, case-insensitively:
/// from its heading to the next heading of the same or a higher level.
pub fn section<'a>(text: &'a str, query: &str) -> Option<(String, &'a str)> {
    let all = headings(text);
    let query = query.to_lowercase();
    let at = all
        .iter()
        .position(|h| h.text.to_lowercase().contains(&query))?;
    let found = &all[at];
    let end = all[at + 1..]
        .iter()
        .find(|h| h.level <= found.level)
        .map_or(text.len(), |h| h.offset);
    Some((found.text.clone(), &text[found.offset..end]))
}

/// The `get_guide` tool.
pub fn get(args: &Value) -> Result<Value, Fail> {
    let query = match &args["section"] {
        Value::Null => {
            return Ok(json!({"guide":NAME,"base_url":BASE_URL,"content":GUIDE}));
        }
        Value::String(query) if !query.trim().is_empty() => query.trim(),
        _ => {
            return Err(tools::fail(
                "invalid_arguments",
                "section must be a non-empty string",
            ));
        }
    };
    match section(GUIDE, query) {
        Some((heading, content)) => Ok(json!({
            "guide": NAME,
            "base_url": BASE_URL,
            "section": heading,
            "content": content.trim_end().to_owned() + "\n",
        })),
        None => {
            let list: Vec<String> = headings(GUIDE)
                .iter()
                .map(|h| format!("{} {}", "#".repeat(h.level), h.text))
                .collect();
            Err(tools::fail(
                "invalid_arguments",
                format!(
                    "no heading of the guide contains {query:?}; its headings are {}",
                    json!(list)
                ),
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The crate's copy of the guide must equal ai-context.md at the root of
    /// the repository (absent outside it, as in a package).
    #[test]
    fn embedded_guide_matches_the_repository_one() {
        let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        if let Ok(published) = std::fs::read_to_string(manifest.join("../../ai-context.md")) {
            assert!(
                published == GUIDE,
                "copy ai-context.md to crates/optimization-runner/guide/ai-context.md"
            );
        }
    }

    const TEXT: &str = "# Title\nintro\n## One\nfirst\n```sh\n# a comment\n## not a heading\n```\n### One A\ndeep\n## Two ##\n~~~\n# also code\n~~~\nsecond\n    # indented code\n#hashtag\n";

    #[test]
    fn headings_skip_code() {
        let found = headings(TEXT);
        let levels: Vec<(usize, &str)> = found.iter().map(|h| (h.level, h.text.as_str())).collect();
        assert_eq!(levels, [(1, "Title"), (2, "One"), (3, "One A"), (2, "Two")]);
        assert_eq!(found[1].offset, TEXT.find("## One").unwrap());
    }

    #[test]
    fn sections() {
        let (heading, content) = section(TEXT, "one").unwrap();
        assert_eq!(heading, "One");
        assert!(content.starts_with("## One\n") && content.ends_with("deep\n"));
        assert!(content.contains("## not a heading"));
        let (_, content) = section(TEXT, "ONE a").unwrap();
        assert_eq!(content, "### One A\ndeep\n");
        let (heading, content) = section(TEXT, "two").unwrap();
        assert_eq!(heading, "Two");
        assert!(content.ends_with("#hashtag\n"));
        assert_eq!(section(TEXT, "title").unwrap().1, TEXT);
        assert_eq!(section(TEXT, "absent"), None);
    }

    #[test]
    fn the_tool() {
        assert_eq!(get(&json!({})).ok().unwrap()["content"], GUIDE);
        let first = &headings(GUIDE)[1];
        let part = get(&json!({"section": first.text.to_uppercase()}))
            .ok()
            .unwrap();
        assert_eq!(part["section"], first.text.as_str());
        assert!(part["content"].as_str().unwrap().starts_with("## "));
        for bad in [
            json!({"section": ""}),
            json!({"section": 3}),
            json!({"section": "no such heading text"}),
        ] {
            let Err(Fail::Tool(e)) = get(&bad) else {
                panic!("{bad} was accepted")
            };
            assert_eq!(e.code, "invalid_arguments");
        }
        let Err(Fail::Tool(e)) = get(&json!({"section": "no such heading text"})) else {
            panic!()
        };
        assert!(e.message.contains(&first.text));
    }
}
