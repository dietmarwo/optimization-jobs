//! Experimental out-of-band uploads over MCP. A transfer endpoint publishes
//! a staged file for a grant. The MCP retry verifies and publishes the input.
use super::{INVALID_PARAMS, MISSING_CAPABILITY, Reply, Server, inputs, tasks, tools};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use optimization_job_api::{
    MAX_INPUT_BYTES,
    storage::{lock, write_atomic_json},
};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Value, json};
use sha2::Sha256;
use std::{
    fs::{self, File},
    io::{self, Read, Write},
    net::IpAddr,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use url::Url;

pub(super) const EXTENSION: &str = "io.modelcontextprotocol/files";
pub(super) const TOOL: &str = "upload_input";
const TARGET_SECONDS: u64 = 300;
const STATE_SECONDS: u64 = 900;

pub(super) struct Uploads {
    origin: Url,
    staging: PathBuf,
    key: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Arguments {
    file: Input,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Input {
    id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    name: Option<String>,
    mime_type: String,
    #[serde(deserialize_with = "size")]
    size: u64,
    digest: Digest,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    data: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Digest {
    algorithm: String,
    value: String,
}

#[derive(Deserialize, Serialize)]
struct Grant {
    size: u64,
    target_expires_at: u64,
    expires_at: u64,
}

fn size<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
    let number = serde_json::Number::deserialize(deserializer)?;
    // JSON Schema regards 12 and 12.0 as equal. Normalizing the forms also
    // lets an equivalent request verify the same requestState.
    number
        .as_u64()
        .or_else(|| {
            number
                .as_f64()
                .filter(|n| *n >= 0.0 && *n <= MAX_INPUT_BYTES as f64 && n.fract() == 0.0)
                .map(|n| n as u64)
        })
        .ok_or_else(|| serde::de::Error::custom("size must be a non-negative integer"))
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn bad_config(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

fn valid_token(token: &str) -> bool {
    token.len() == 32
        && token
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn load_key(directory: &Path) -> io::Result<[u8; 32]> {
    let path = directory.join("files.key");
    let mut key = [0u8; 32];
    let _guard = lock(&directory.join("files.lock"))?;
    match fs::symlink_metadata(&path) {
        Ok(meta) => {
            if !meta.is_file() || meta.permissions().mode() & 0o077 != 0 || meta.len() != 32 {
                return Err(bad_config(
                    "the Files key must be a private 32-byte regular file",
                ));
            }
            File::open(&path)?.read_exact(&mut key)?;
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            File::open("/dev/urandom")?.read_exact(&mut key)?;
            let mut file = tempfile::NamedTempFile::new_in(directory)?;
            file.write_all(&key)?;
            file.as_file().sync_all()?;
            file.persist_noclobber(path).map_err(|e| e.error)?;
            File::open(directory)?.sync_all()?;
        }
        Err(error) => return Err(error),
    }
    Ok(key)
}

impl Uploads {
    pub fn new(root: &Path, endpoint: &str) -> io::Result<Self> {
        let origin =
            Url::parse(endpoint).map_err(|_| bad_config("invalid Files endpoint origin"))?;
        let loopback = origin.host_str().is_some_and(|host| {
            host == "localhost"
                || host
                    .trim_matches(['[', ']'])
                    .parse::<IpAddr>()
                    .is_ok_and(|address| address.is_loopback())
        });
        if origin.host().is_none()
            || !(origin.scheme() == "https" || (origin.scheme() == "http" && loopback))
            || origin.path() != "/"
            || origin.query().is_some()
            || origin.fragment().is_some()
            || !origin.username().is_empty()
            || origin.password().is_some()
        {
            return Err(bad_config(
                "Files endpoint must be an HTTPS origin or an HTTP loopback origin",
            ));
        }
        let directory = root.join("mcp");
        fs::create_dir_all(&directory)?;
        let staging = directory.join("uploads");
        match fs::DirBuilder::new().mode(0o700).create(&staging) {
            Ok(()) => (),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => (),
            Err(error) => return Err(error),
        }
        let metadata = fs::symlink_metadata(&staging)?;
        if !metadata.is_dir() || metadata.permissions().mode() & 0o077 != 0 {
            return Err(bad_config("the Files staging directory must be private"));
        }
        let uploads = Self {
            origin,
            staging,
            key: load_key(&directory)?,
        };
        uploads.clean();
        Ok(uploads)
    }

    fn mac(&self, token: &str, expires_at: u64, args: &Arguments) -> Hmac<Sha256> {
        let mut mac = Hmac::new_from_slice(&self.key).expect("32-byte HMAC key");
        // Bind the signed state to the complete validated arguments and target.
        let bound = serde_json::to_vec(&(TOOL, self.origin.as_str(), token, expires_at, args))
            .expect("serializable upload state");
        mac.update(&bound);
        mac
    }

    fn verified_token<'a>(&self, state: &'a str, args: &Arguments) -> Option<&'a str> {
        let mut parts = state.split('.');
        let token = parts.next()?;
        let expires_at: u64 = parts.next()?.parse().ok()?;
        let signature = parts.next()?;
        if state.len() > 110 || parts.next().is_some() || !valid_token(token) || now() >= expires_at
        {
            return None;
        }
        let signature = URL_SAFE_NO_PAD.decode(signature).ok()?;
        self.mac(token, expires_at, args)
            .verify_slice(&signature)
            .ok()?;
        Some(token)
    }

    fn grant(&self, args: &Arguments) -> io::Result<Value> {
        let now = now();
        let grant = Grant {
            size: args.file.size,
            target_expires_at: now + TARGET_SECONDS,
            expires_at: now + STATE_SECONDS,
        };
        let token = tools::task_token()?;
        let target = self
            .origin
            .join(&format!("uploads/{token}"))
            .expect("valid Files target from an HTTP origin");
        let signature = URL_SAFE_NO_PAD.encode(
            self.mac(&token, grant.expires_at, args)
                .finalize()
                .into_bytes(),
        );
        write_atomic_json(&self.staging.join(format!("{token}.json")), &grant)?;
        Ok(json!({
            "resultType": "upload_required",
            "uploads": [{
                "fileId": args.file.id, "url": target.as_str(), "method": "PUT",
                "credentials": "omit", "expiresAt": tasks::iso(grant.target_expires_at as f64),
            }],
            "requestState": format!("{token}.{}.{signature}", grant.expires_at),
        }))
    }

    fn clean(&self) {
        let now = now();
        for entry in fs::read_dir(&self.staging).into_iter().flatten().flatten() {
            let path = entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json")
                || !path
                    .file_stem()
                    .and_then(|stem| stem.to_str())
                    .is_some_and(valid_token)
                || !entry.file_type().is_ok_and(|kind| kind.is_file())
            {
                continue;
            }
            let grant = fs::read(&path)
                .ok()
                .and_then(|bytes| serde_json::from_slice::<Grant>(&bytes).ok());
            if grant.is_some_and(|grant| grant.expires_at <= now) {
                let _ = fs::remove_file(path.with_extension("upload"));
                let _ = fs::remove_file(path);
            }
        }
    }
}

fn bad_state() -> Reply {
    Reply::Err(
        INVALID_PARAMS,
        "invalid, expired or mismatched upload requestState".into(),
        None,
    )
}

fn completion(result: Result<Value, tools::Fail>) -> Reply {
    match result {
        Ok(value) => Reply::Ok(tools::tool_result(value, false)),
        Err(tools::Fail::Tool(error)) => Reply::Ok(tools::tool_result(error.value(), true)),
        Err(tools::Fail::Cancelled) => Reply::Silent,
    }
}

pub(super) fn call(
    server: &Server,
    uploads: &Uploads,
    arguments: Value,
    state: Option<&Value>,
    supported: bool,
) -> Reply {
    let invalid_arguments = || {
        completion(Err(tools::fail(
            "invalid_arguments",
            "expected valid file metadata, up to 64 MiB, with a SHA-256 digest and no inline data",
        )))
    };
    // A null optional member is invalid on the wire. Reject it before Serde
    // maps null and absent to the same value for Option.
    if arguments["file"].get("name").is_some_and(Value::is_null)
        || arguments["file"].get("data").is_some_and(Value::is_null)
    {
        return if state.is_some() {
            bad_state()
        } else {
            invalid_arguments()
        };
    }
    let Ok(args) = serde_json::from_value::<Arguments>(arguments) else {
        return if state.is_some() {
            bad_state()
        } else {
            invalid_arguments()
        };
    };
    let file = &args.file;
    if !(1..=128).contains(&file.id.chars().count())
        || file.mime_type.is_empty()
        || file.size > MAX_INPUT_BYTES
        || file.digest.algorithm != "sha-256"
        || file
            .data
            .as_ref()
            .is_some_and(|s| file.size != 0 || !s.is_empty())
    {
        return if state.is_some() {
            bad_state()
        } else {
            invalid_arguments()
        };
    }
    let Ok(hash) = URL_SAFE_NO_PAD.decode(&file.digest.value) else {
        return if state.is_some() {
            bad_state()
        } else {
            invalid_arguments()
        };
    };
    if hash.len() != 32 {
        return if state.is_some() {
            bad_state()
        } else {
            invalid_arguments()
        };
    }
    let mut sha256 = String::with_capacity(64);
    for byte in hash {
        use std::fmt::Write as _;
        write!(sha256, "{byte:02x}").expect("writing to a string");
    }
    let token = match state {
        Some(value) => match value
            .as_str()
            .and_then(|state| uploads.verified_token(state, &args))
        {
            Some(token) => Some(token),
            None => return bad_state(),
        },
        None => None,
    };
    if file.size == 0 {
        return completion(inputs::store_empty(server, &sha256));
    }
    if !supported {
        return Reply::Err(
            MISSING_CAPABILITY,
            "Missing required client capability".into(),
            Some(json!({"requiredCapabilities":{"extensions":{EXTENSION:{"upload":{}}}}})),
        );
    }
    if let Some(token) = token {
        let staged = uploads.staging.join(format!("{token}.upload"));
        return completion(inputs::store_upload(server, &staged, &sha256, file.size));
    }
    if let Err(error) = inputs::check_upload(server, &sha256, file.size) {
        return completion(Err(error));
    }
    match uploads.grant(&args) {
        Ok(result) => Reply::Ok(result),
        Err(_) => completion(Err(tools::fail(
            "runner_error",
            "could not issue an upload grant",
        ))),
    }
}

pub(super) fn definition() -> Value {
    json!({
        "name": TOOL,
        "title": "Upload an input file",
        "description": "Store a job input through the experimental Files extension. Pass a SHA-256 digest; use the returned input_dir when you validate and submit the job.",
        "annotations":{"readOnlyHint":false,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},
        "inputSchema":{
            "type":"object","required":["file"],"additionalProperties":false,
            "properties":{"file":{
                "type":"object","required":["id","mimeType","size","digest"],"additionalProperties":false,
                "x-mcp-file":{"maxSize":MAX_INPUT_BYTES},
                "properties":{
                    "id":{"type":"string","minLength":1,"maxLength":128},
                    "name":{"type":"string"},
                    "mimeType":{"type":"string","minLength":1},
                    "size":{"type":"integer","minimum":0,"maximum":MAX_INPUT_BYTES},
                    "digest":{"type":"object","required":["algorithm","value"],"additionalProperties":false,
                        "properties":{"algorithm":{"const":"sha-256"},"value":{"type":"string","pattern":"^[A-Za-z0-9_-]{43}$"}}},
                    "data":{"const":""},
                },
            }},
        },
        "outputSchema": tools::output_schema(TOOL).expect("upload output schema"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_correctly_signed_state_cannot_be_used_after_expiry() {
        let root = tempfile::tempdir().unwrap();
        let uploads = Uploads::new(root.path(), "http://127.0.0.1:8000").unwrap();
        let arguments: Arguments = serde_json::from_value(json!({
            "file":{"id":"model","mimeType":"application/octet-stream","size":1,
                "digest":{"algorithm":"sha-256","value":"ignored for this signature test"}}
        }))
        .unwrap();
        let token = tools::task_token().unwrap();
        let expiry = now().saturating_sub(1);
        let signed = URL_SAFE_NO_PAD.encode(
            uploads
                .mac(&token, expiry, &arguments)
                .finalize()
                .into_bytes(),
        );
        assert_eq!(
            uploads.verified_token(&format!("{token}.{expiry}.{signed}"), &arguments),
            None
        );
    }
}
