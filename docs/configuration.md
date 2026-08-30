# Configuration

[简体中文](zh-CN/configuration.md) · [Documentation index](README.md)

Lingshu Gate reads runtime configuration from `LINGSHU_GATE_*` environment variables. Native package launchers provide package-local directories; Docker Compose provides container paths and safe network defaults.

## Common settings

| Variable | Native default | Docker value | Notes |
|---|---|---|---|
| `LINGSHU_GATE_HOST` | `127.0.0.1` | `0.0.0.0` inside the container | Docker publishes the port on host loopback by default |
| `LINGSHU_GATE_PORT` | `8000` | `8000` | HTTP port for Console, API, probes, and `/mcp` |
| `LINGSHU_GATE_DATA_DIR` | Platform application-data directory | `/data` | Database, encrypted credentials, uploads, builds, and operation state |
| `LINGSHU_GATE_CONFIG_DIR` | Platform application-config directory | `/config/mcp.d` | YAML and JSON downstream manifests |
| `LINGSHU_GATE_ALLOWED_ROOT` | Launcher `workspace` directory | `/workspace` | Boundary for trusted local file and project paths |
| `LINGSHU_GATE_DB_URL` | SQLite database under the data directory | `sqlite:////data/gate.db` | One Gate process per SQLite file |
| `LINGSHU_GATE_AUTH_ENABLED` | `true` | `true` | Disable only for isolated local debugging |
| `LINGSHU_GATE_AUTH_COOKIE_SECURE` | `false` | `false` in local Compose | Set `true` when the public origin is HTTPS |
| `LINGSHU_GATE_TRUSTED_PROXY_IPS` | `127.0.0.1` | `127.0.0.1` | Exact proxy addresses/CIDRs trusted for forwarded headers; never use `*` on an uncontrolled network |
| `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` | Loopback origins on the configured port | Same | Comma-separated browser Origin allowlist for `/mcp`; non-browser clients normally omit `Origin` |
| `LINGSHU_GATE_LOG_LEVEL` | `INFO` | `INFO` | Standard Python log level |
| `LINGSHU_GATE_LOG_PAYLOADS` | `false` | `false` | Payloads can contain sensitive data; leave disabled |
| `LINGSHU_GATE_REQUEST_TIMEOUT_SECONDS` | `30` | `30` | Bound for downstream requests |
| `LINGSHU_GATE_STARTUP_TIMEOUT_SECONDS` | `30` | `30` | Bound for downstream startup and discovery |
| `LINGSHU_GATE_MCP_GATEWAY_ENABLED` | `true` | `true` | Controls the `/mcp` route |

Protocol version `2026-07-28` is fixed by the release. It is not a runtime tuning option.

Boolean values accept the forms implemented by the application (`true`/`false` are recommended). Invalid numeric values or unsupported deployment-role values stop startup instead of being ignored.

## Native directory layout

The release launcher creates writable directories beside the extracted package:

```text
lingshu-gate/
  config/
    mcp.d/
  data/
  workspace/
  start.sh          # Unix packages
  start.cmd         # Windows package
```

Running `lingshu-gate` directly uses platform application directories unless you override them. For predictable service operation, set absolute `DATA_DIR`, `CONFIG_DIR`, and `ALLOWED_ROOT` values explicitly.

Never place the data directory inside a web root or source checkout. Restrict it to the Gate service account because credential key material and audit state live there.

## Initial administrator

When authentication is enabled and the database has no users, Gate creates a one-time `admin` password in:

```text
<data-dir>/initial-admin-credentials.json
```

The file is local, is created with restrictive permissions where supported, and is not returned by the API or written to logs. The administrator must change the password on first login; Gate then removes the file.

For unattended provisioning, configure an administrator username and inject the initial password from a protected absolute file through the deployment's bootstrap-password setting. The password file must be a regular UTF-8 file containing exactly one non-empty line, must not be group/world writable on POSIX systems, and must not be stored in the repository.

## Downstream manifests

Manifests are YAML or JSON objects stored in `mcp.d`. The file name is not the identity; `id` is. IDs must match `^[A-Za-z0-9_.-]+$` and remain stable because grants, credentials, runtime state, and audits reference them.

### External Streamable HTTP

```yaml
id: example-http
name: Example HTTP server
enabled: true
launch:
  type: external
transport:
  type: streamable_http
  endpoint: https://service.example/mcp
  protocol_version: "2026-07-28"
  headers:
    Authorization: "Bearer ${credential:discovery-token}"
timeout_seconds: 30
auto_start: false
```

The manifest field is explicit self-documentation. Its only accepted value is `2026-07-28`; it cannot select another protocol mode.

Static headers may contain `${credential:<id>}` references. Gate resolves them only for the downstream request and masks values in API responses and logs.

### Managed local stdio

Managed stdio is available only in native mode and runs as the Gate operating-system account:

```yaml
id: example-stdio
name: Example stdio server
enabled: true
launch:
  type: managed_process
  command: python
  args:
    - server.py
  cwd: /absolute/path/inside/the/allowed/root
  env:
    SERVICE_TOKEN: "${credential:runtime-token}"
transport:
  type: stdio
  protocol_version: "2026-07-28"
timeout_seconds: 30
auto_start: false
```

The stdio manifest likewise accepts only `2026-07-28`.

Use an absolute, reviewed `cwd` inside the allowed root. Avoid shell wrappers; configure the executable and argument list directly. Auto-start should remain off until the command, credentials, and tool definitions have been reviewed.

### Explicit native managed container

A native Gate installation can launch a reviewed container through the local container engine:

```yaml
id: example-container
name: Example container server
enabled: true
launch:
  type: managed_container
  image: registry.example/server@sha256:<digest>
  mounts:
    - source: /absolute/allowed/input
      target: /workspace
      read_only: true
  environment:
    SERVICE_TOKEN: "${credential:container-token}"
  resources:
    memory: 512m
    cpus: "1.0"
    pids_limit: 128
transport:
  type: stdio
  protocol_version: "2026-07-28"
auto_start: false
```

The image must use a lowercase SHA-256 digest. `mounts` is the only accepted bind schema: every source must be an existing regular file or directory inside `LINGSHU_GATE_ALLOWED_ROOT`, every target must be a non-root absolute container path outside the protected `/dev`, `/proc`, `/run`, `/sys`, and `/tmp` trees, and `read_only` cannot be disabled. Gate resolves the source again immediately before execution.

Every launch forces `--network none`, a read-only root filesystem, all-capability removal, no-new-privileges, and protected `/tmp` and `/run` tmpfs mounts. Resource limits always apply; omitted values default to `512m`, `1.0` CPU, and 128 PIDs, with hard maxima of `4g`, 4 CPUs, and 512 PIDs. Manifest environment variables cannot override `LINGSHU_GATE_*` values or Docker process controls. This mode is unavailable in Docker Core and must never be enabled by mounting a container-engine socket into the Core service.

### Per-user HTTP credentials

An external HTTP manifest may declare secret-free user slots:

```yaml
user_credentials:
  - id: personal-token
    name: Personal access token
    description: Used only for this user's downstream calls
    required: true
    injection:
      type: http_header
      name: Authorization
      template: "Bearer {value}"
```

Users bind a value through the authenticated credential API or Console. Gate encrypts it separately, injects it into the authenticated user's isolated HTTP request context, and never writes it back to the manifest. Protected MCP headers cannot be overridden. Per-user secrets are not supported for shared stdio processes.

## Credentials

System credentials are managed through the Console or `/v1/credentials`. API responses expose IDs and masked state, never plaintext. Reference a saved value from `launch.env`, `launch.environment`, or `transport.headers` with:

```text
${credential:credential-id}
```

Back up encrypted stores and their key files together. Encryption protects accidental disclosure in manifests and API output; it does not protect against a host account that can read the entire data directory.

## Reverse proxy

For remote access:

1. Keep Gate bound to a private or loopback interface.
2. Terminate TLS at a trusted reverse proxy.
3. Set `LINGSHU_GATE_AUTH_COOKIE_SECURE=true`.
4. Set `LINGSHU_GATE_TRUSTED_PROXY_IPS` to the actual proxy IP or smallest internal CIDR. Its default is `127.0.0.1`.
5. Make the proxy replace, not append to, client-provided `Forwarded` and `X-Forwarded-*` headers.
6. Apply request-size limits and timeouts appropriate for upload and streaming endpoints.

Do not set the trusted source to `*` on an uncontrolled network, and do not expose the private Gate port beside the proxy.

## Validation

Use the Console or `POST /v1/mcp/configs/validate` before saving a manifest. Validation covers schema and local policy; a successful validation does not prove that a remote endpoint is trusted or healthy. After saving, inspect server status, discovered tools, classifications, and grants before enabling invocation.
