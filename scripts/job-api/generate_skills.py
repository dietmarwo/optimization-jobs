#!/usr/bin/env python3
"""Generate the standalone crate's MCP skill files from the embedded guide."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_markdown_links import links, without_fences

CRATE = ROOT / "crates/optimization-runner"
BASE = "https://github.com/dietmarwo/optimization-jobs/blob/main/ai-context.md"
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
DESTINATION = re.compile(
    r"(?P<prefix>\]\(\s*<?|^ {0,3}\[[^]\n]+\]:\s*<?|\b(?:href|src)=[\"'])"
    r"(?P<url>[^ \t\r\n)>\"']+)"
)

SKILLS = {
    "choose-optimization-solver": (
        "Choose an optimization solver and worker profile from the objective, constraints, derivatives and required result.",
        """1. Write the problem card: variables, objective, constraints, available
   derivatives, work budget and what the answer must establish.
2. Match the card to a solver. Choose LP-IP-craft for a sparse linear model,
   SQP-craft for a smooth constrained model with derivatives, MODE for a
   Pareto front, or MAP-Elites for diverse high-quality solutions. Use a
   registered scalar fcmaes model for a boxed black-box objective.
3. Call describe_node and describe_worker. Check that the selected profile and
   the model are installed and use the returned payload schema and examples.
4. Choose budgets and decide what evidence you will need before you run.

Read [the problem card](references/problem-card.md) and
[solver selection](references/solver-selection.md) for the complete criteria.
""",
        {
            "problem-card": "1. Write a short problem card",
            "solver-selection": "2. Choose the solver",
        },
    ),
    "interpret-optimization-result": (
        "Read optimization results, compare feasible candidates and report their termination, claims, evidence and resource accounting.",
        """1. Read get_job. Once it is terminal, call get_result. For a specific task,
   request that task's full record. Inspect artifact_index for large outputs.
2. Report the reason the task stopped, its claim and the evidence separately.
   A cancellation or deadline can still leave completed records. State how much
   work is known if accounting is incomplete.
3. For LP or MIP, report the incumbent and any bound or gap. For SQP, read the
   reported feasibility and optimality residuals. For MODE, name the source
   of the front and the reference point used for hypervolume. For MAP-Elites,
   read the archive's occupancy, coverage and QD score.
4. Treat a best-found point as a candidate. A proof of optimality requires
   an appropriate certificate. Distinguish feasibility for the declared model
   from raw constraints that were modeled only as penalties.

See [results, claims and evidence](references/results.md) and
[common pitfalls](references/pitfalls.md).
""",
        {"results": "Results, claims and evidence", "pitfalls": "Pitfalls"},
    ),
    "run-optimization-job": (
        "Stage input files, validate, submit, reconnect to, and cancel durable optimization jobs over MCP.",
        """1. Call describe_node and describe_worker for capacity, profiles, payload
   schemas and examples. On a node with eight free slots, an eligible profile
   can use eight single-threaded outer retries or one outer task with eight
   evaluation threads. The latter needs a worker that supports inner
   parallelism for the selected profile.
2. Use put_input for model files. Put the returned file name and SHA-256 in
   the job inputs and pass the returned input_dir. Build the job envelope
   and call validate_job.
3. Submit with a stable request_key. Persist the task reference if the client
   supports Tasks, or save the job_id. When recovering from a lost reply,
   reuse the exact request and key to identify the same job.
4. After reconnecting, poll the saved task or call get_job. Use tasks/cancel
   or cancel_job for a cooperative stop. Then read committed work with
   get_result.

Read [the job API](references/job-api.md), [the MCP tools](references/mcp.md)
and [CPU budgeting](references/cpu-budget.md) as needed.
""",
        {
            "job-api": "5. The job API",
            "mcp": "6. The MCP server",
            "cpu-budget": "7. Resources on a large machine",
        },
    ),
}


def section(text: str, title: str) -> str:
    source = text.splitlines()
    headings = []
    for index, line in enumerate(without_fences(text).split("\n")):
        if match := HEADING.fullmatch(line):
            headings.append((index, len(match[1]), match[2].strip()))
    found = [i for i, (_, _, heading) in enumerate(headings) if heading == title]
    if len(found) != 1:
        raise ValueError(f"expected one heading {title!r}, found {len(found)}")
    at = found[0]
    start, level, _ = headings[at]
    end = next((line for line, depth, _ in headings[at + 1:] if depth <= level), len(source))
    return "\n".join(source[start:end]).rstrip() + "\n"


def absolute_links(text: str) -> str:
    def destination(match):
        url = match["url"]
        if urlsplit(url).scheme or url.startswith("//"):
            return match[0]
        return match["prefix"] + urljoin(BASE, url)

    prose_lines = without_fences(text).split("\n")
    result = "\n".join(
        DESTINATION.sub(destination, line) if prose_lines[index] else line
        for index, line in enumerate(text.splitlines())
    ) + "\n"
    relative = [url for url in links(result) if not urlsplit(url).scheme and not url.startswith("//")]
    if relative:
        raise ValueError(f"inherited relative links in generated reference: {relative}")
    return result


def generate() -> dict[str, bytes]:
    guide = (CRATE / "guide/ai-context.md").read_text()
    generated = {}
    catalog = ["// Generated by scripts/job-api/generate_skills.py.", "static CATALOG: &[Skill] = &["]
    for name, (description, body, references) in SKILLS.items():
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
            raise ValueError(f"invalid Agent Skills name: {name}")
        if not 1 <= len(description) <= 1024 or "\n" in description:
            raise ValueError(f"invalid Agent Skills description: {name}")
        desc = json.dumps(description, ensure_ascii=False)
        files = {"SKILL.md": f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}"}
        for filename, title in references.items():
            files[f"references/{filename}.md"] = absolute_links(section(guide, title))
        files = {file: text.encode("utf-8") for file, text in files.items()}
        if len(files) > 512 or sum(map(len, files.values())) > 16 * 1024 * 1024:
            raise ValueError(f"skill exceeds the published wire limits: {name}")
        if set(links(body)) != set(files) - {"SKILL.md"}:
            raise ValueError(f"workflow links do not match references: {name}")
        catalog.append(f"    skill!({json.dumps(name)}, {desc}, [")
        for file in sorted(files):
            catalog.append(f"        {json.dumps(file)},")
            generated[f"{name}/{file}"] = files[file]
        catalog.append("    ]),")
    catalog.append("];")
    generated["catalog.rs"] = ("\n".join(catalog) + "\n").encode()
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare to the committed files")
    args = parser.parse_args()
    folder = CRATE / "skills"
    generated = generate()
    if args.check:
        present = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        drift = sorted(present ^ generated.keys())
        drift.extend(file for file in present & generated.keys()
                     if (folder / file).read_bytes() != generated[file])
        if drift:
            parser.exit(1, f"Regenerate MCP skills. Files differ: {', '.join(sorted(drift))}\n")
        print(f"Verified {len(SKILLS)} skills and {len(generated) - 1} resource files")
    else:
        for file, contents in generated.items():
            path = folder / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)


if __name__ == "__main__":
    main()
