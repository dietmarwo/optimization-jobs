"""Checks of the discovery convention (docs/job-api.md#discovery-for-agents):
the `payload_schemas`, `input_schemas` and runnable `examples` that a
worker's `describe` lists, so that a client can build and validate one job
per profile from `describe_worker` alone.

Shared by test_integration.py (the real workers), test_review.py (the
protocol fixture) and test_mcp.py (the MCP-only flow). The JSON Schema
checks need the `jsonschema` package (Draft 2020-12, version 4.18 or newer);
without it they are skipped, unless JOB_API_REQUIRE_SCHEMA=1 (as in CI).
"""
import copy
import hashlib
import json
import os

try:
    import jsonschema
except ImportError:
    jsonschema = None

DIALECT = "https://json-schema.org/draft/2020-12/schema"
EXAMPLE_KEYS = ("profile", "payload", "resources", "limits", "inputs")
UNKNOWN_FIELD = "an_unknown_field_of_the_discovery_check"


def schema_checks_required():
    return os.environ.get("JOB_API_REQUIRE_SCHEMA") == "1"


def completeness(description):
    """What the discovery keys of a `describe` output lack: a payload schema
    and an example for every profile, examples of known profiles with every
    key, inputs with content and known formats. Empty when complete."""
    problems = []
    profiles = description.get("profiles") or []
    schemas = description.get("payload_schemas")
    formats = description.get("input_schemas", {})
    examples = description.get("examples")
    if not isinstance(schemas, dict):
        problems.append("describe lists no payload_schemas object")
        schemas = {}
    if not isinstance(formats, dict):
        problems.append("input_schemas is not an object")
        formats = {}
    if not isinstance(examples, list):
        problems.append("describe lists no examples")
        examples = []
    for profile in profiles:
        if not isinstance(schemas.get(profile), dict):
            problems.append(f"{profile}: no payload schema")
        if not any(isinstance(e, dict) and e.get("profile") == profile for e in examples):
            problems.append(f"{profile}: no example")
    for profile in schemas:
        if profile not in profiles:
            problems.append(f"payload_schemas has {profile}, which is not a profile")
    for k, example in enumerate(examples):
        if not isinstance(example, dict):
            problems.append(f"example {k} is not an object")
            continue
        where = f"example {k} ({example.get('profile')})"
        if example.get("profile") not in profiles:
            problems.append(f"{where}: not a profile of the worker")
        problems += [f"{where}: no {key}" for key in EXAMPLE_KEYS if key not in example]
        if not isinstance(example.get("payload", {}), dict):
            problems.append(f"{where}: the payload is not an object")
        inputs = example.get("inputs", [])
        if not isinstance(inputs, list):
            problems.append(f"{where}: inputs is not a list")
            continue
        for spec in inputs:
            if not isinstance(spec, dict) or not all(isinstance(spec.get(k), str) for k in ("name", "file")):
                problems.append(f"{where}: an input without name and file")
                continue
            name = spec["name"]
            parts = spec["file"].replace("\\", "/").split("/")
            if spec["file"].startswith("/") or ".." in parts or not any(p not in ("", ".") for p in parts):
                problems.append(f"{where}: input {name}: file {spec['file']!r} is not a relative path inside the job's directory")
            if ("content" in spec) == ("content_text" in spec):
                problems.append(f"{where}: input {name} needs exactly one of content and content_text")
            elif "content_text" in spec and not isinstance(spec["content_text"], str):
                problems.append(f"{where}: input {name}: content_text is not a string")
            if "format" in spec and spec["format"] not in formats:
                problems.append(f"{where}: input {name}: format {spec['format']} is not in input_schemas")
    return problems


def input_bytes(spec):
    """The bytes a client writes for an example input: the JSON value of
    `content` as any serializer writes it, or the UTF-8 of `content_text`."""
    if "content_text" in spec:
        return spec["content_text"].encode()
    return json.dumps(spec["content"]).encode()


def envelope(example, worker, request_key, inputs):
    """The job of an example, given its inputs as `{name, file, sha256}`."""
    return {
        "schema_version": "optimization.job/0.1", "request_key": request_key, "worker": worker,
        "payload_schema": example["profile"], "payload": copy.deepcopy(example["payload"]),
        "resources": copy.deepcopy(example["resources"]), "limits": copy.deepcopy(example["limits"]),
        "inputs": inputs,
    }


def write_example(example, worker, request_key, directory):
    """Writes the inputs of an example into `directory`, a fresh one per
    example, and returns its job, whose inputs carry their real SHA-256."""
    inputs = []
    for spec in example.get("inputs", []):
        data = input_bytes(spec)
        path = directory / spec["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        inputs.append({"name": spec["name"], "file": spec["file"],
                       "sha256": hashlib.sha256(data).hexdigest()})
    return envelope(example, worker, request_key, inputs)


def _schema_problems(where, schema):
    if not isinstance(schema, dict):
        return [f"{where}: the schema is not an object"]
    problems = []
    if schema.get("$schema") != DIALECT:
        problems.append(f"{where}: $schema is not {DIALECT}")
    if not isinstance(schema.get("$id"), str):
        problems.append(f"{where}: no $id")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.exceptions.SchemaError as e:
        problems.append(f"{where}: not a valid JSON Schema: {e.message}")
    return problems


def _errors(where, schema, value):
    found = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value), key=str)
    return [f"{where}: {e.message} at {'/'.join(map(str, e.absolute_path)) or 'the root'}"
            for e in found[:3]]


def schema_problems(description, unknown_fields_rejected=True):
    """What the JSON Schema checks find: every schema a valid Draft 2020-12
    schema with `$schema` and `$id`; every example payload valid against
    its profile's schema, and every example input with a format against
    `input_schemas`. With `unknown_fields_rejected` (the real workers reject
    unknown payload fields), a payload with an unknown top-level field must
    not validate. Needs `jsonschema`; run `completeness` first."""
    problems = []
    schemas = description.get("payload_schemas") or {}
    formats = description.get("input_schemas") or {}
    for profile, schema in schemas.items():
        problems += _schema_problems(f"payload schema {profile}", schema)
    for name, schema in formats.items():
        problems += _schema_problems(f"input schema {name}", schema)
    if problems:
        return problems
    for k, example in enumerate(description.get("examples") or []):
        where = f"example {k} ({example.get('profile')})"
        schema = schemas.get(example.get("profile"))
        if schema is None:
            continue
        problems += _errors(f"{where}: payload", schema, example.get("payload"))
        if unknown_fields_rejected and isinstance(example.get("payload"), dict):
            extended = {**example["payload"], UNKNOWN_FIELD: True}
            if jsonschema.Draft202012Validator(schema).is_valid(extended):
                problems.append(f"{where}: the payload schema accepts an unknown field, which the worker rejects")
        for spec in example.get("inputs") or []:
            if "format" in spec and spec["format"] in formats:
                value = spec["content"] if "content" in spec else spec.get("content_text")
                problems += _errors(f"{where}: input {spec.get('name')}", formats[spec["format"]], value)
    return problems


def payload_problems(description, profile, payload):
    """Why `payload` does not validate against the worker's schema of
    `profile`; nothing when the worker lists no schema for it, which
    `completeness` reports. Needs `jsonschema`."""
    schema = (description.get("payload_schemas") or {}).get(profile)
    if not isinstance(schema, dict):
        return []
    return _errors(f"{profile} payload", schema, payload)


def null_variants(description, example):
    """The example's payload with each optional top-level field set to
    `null`: `(field, payload)` pairs. A worker whose field deserializes as an
    optional value treats `null` as absent and its schema must allow it; a
    worker that rejects `null` there must have a schema that rejects it too.
    Either way, the schema and the worker must agree, which a caller checks
    by validating each variant with both."""
    schema = (description.get("payload_schemas") or {}).get(example.get("profile"))
    payload = example.get("payload")
    if not isinstance(schema, dict) or not isinstance(payload, dict):
        return []
    required = set(schema.get("required") or [])
    variants = []
    for field in schema.get("properties") or {}:
        if field not in required:
            variant = copy.deepcopy(payload)
            variant[field] = None
            variants.append((field, variant))
    return variants


def schema_accepts(description, profile, payload):
    """Whether the worker's payload schema of `profile` accepts `payload`.
    Needs `jsonschema`."""
    schema = description["payload_schemas"][profile]
    return jsonschema.Draft202012Validator(schema).is_valid(payload)
