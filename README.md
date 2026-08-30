# Lingshu Gate

Self-hosted MCP gateway and control plane for operating downstream servers with explicit access, audit, and delivery boundaries.

[简体中文](README.zh-CN.md) · [Documentation](docs/README.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

Lingshu Gate provides one authenticated MCP endpoint, a Web Console, configuration and runtime management, encrypted credentials, tool classification, invocation audit, diagnostics, and a controlled project upload/build/deploy/start workflow.

## What it provides

- One Streamable HTTP MCP gateway at `POST /mcp`.
- Generic downstream Streamable HTTP and stdio transports using protocol version `2026-07-28`.
- Web Console and REST control API for server configuration and runtime state.
- Authentication, RBAC, resource grants, API-token scopes, tool classification, and invocation audit.
- Encrypted system credentials and isolated per-user downstream request bindings.
- Logs, events, health probes, diagnostics, and bounded runtime-cache management.
- Project upload, preflight, deterministic build planning, build, deploy, start, and tool-refresh operations.
- A repository-owned Delivery Skill at `.agents/skills/lingshu-gate-upload-build-start/` for confirmation-bound automation through the `gate_*` delivery tools.

## Quick start

### Docker Compose

Docker Compose is the shortest path to an isolated Gate control plane and HTTP gateway:

```bash
mkdir -p runtime/workspace
docker compose up -d --build core
docker compose ps
```

Open <http://127.0.0.1:8000/console>. On an empty data volume, Gate creates a one-time administrator password in `/data/initial-admin-credentials.json`:

```bash
docker compose exec core sh -c 'cat /data/initial-admin-credentials.json'
```

Sign in, change the password immediately, and create narrowly scoped users or API tokens. The one-time credentials file is removed after the password is changed.

The default Compose service binds to `127.0.0.1`, runs as UID/GID `10001`, uses a read-only root filesystem, and keeps authentication enabled. The Core image connects to external Streamable HTTP servers; use a native installation when Gate must launch local stdio processes or execute project builds.

### Prebuilt native package

Download the archive for your platform and `SHA256SUMS` from [GitHub Releases](https://github.com/zhigege666/Lingshu-Gate/releases), verify the archive, extract it, then run:

```bash
./start.sh
```

On Windows:

```powershell
.\start.cmd
```

The launcher creates package-local `data`, `config`, and `workspace` directories. You can also run `lingshu-gate` (`lingshu-gate.exe` on Windows) directly when you provide the required paths through `LINGSHU_GATE_*` environment variables.

### From source

Requirements: Python 3.11, 3.12, or 3.13; Node.js 22; npm; and `uv`.

```bash
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run lingshu-gate
```

Gate listens on `127.0.0.1:8000` by default. The Web Console is at `/console`, OpenAPI documentation at `/docs`, and readiness probe at `/readyz`.

## First server

Create a vendor-neutral manifest in the configured `mcp.d` directory or use the Console. An external Streamable HTTP server looks like this:

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
auto_start: false
```

`protocol_version` is explicit self-documentation; only `2026-07-28` is accepted and it is not a version-selection switch.

Validate and save the manifest, inspect discovered tools, classify them as read or write, review the result, and publish only the classifications that should be callable. Access is the intersection of control permission, resource grant, published classification, and API-token scope.

For local stdio configuration, credential references, lifecycle behavior, and gateway requests, see [MCP gateway and downstream servers](docs/mcp-gateway.md).

## Project delivery

Gate exposes confirmation-bound `gate_*` tools for resumable upload, preflight, build planning, build execution, deployment, startup, and post-start tool reconciliation. Each write is idempotency-bound; source, plan, configuration, credential, and tool-snapshot digests prevent silent drift.

The bundled [Delivery Skill](.agents/skills/lingshu-gate-upload-build-start/SKILL.md) adds deterministic local packaging and an operator workflow around those tools. It never removes the requirement for explicit confirmation before upload, code execution, deployment, overwrite, startup, cancellation, or abandonment.

See [Project delivery](docs/project-delivery.md) for the complete boundary and tool list.

## Security defaults

- Authentication is enabled, and initial credentials are random and local to the data directory.
- Network binding defaults to loopback; remote access belongs behind an HTTPS reverse proxy.
- Session cookies are `HttpOnly` and `SameSite=Lax`; enable `LINGSHU_GATE_AUTH_COOKIE_SECURE=true` behind HTTPS.
- MCP payload logging is disabled by default.
- Secrets are encrypted at rest and returned only as masked metadata; manifests should use `${credential:<id>}` references.
- Tool annotations are hints. Human-reviewed, published classifications and explicit grants determine effective access.
- The Docker Core service drops Linux capabilities, prevents privilege escalation, and mounts the workspace read-only.

Read [SECURITY.md](SECURITY.md) before exposing Gate outside a single trusted host.

## Release downloads

Release automation builds the following archives:

| Target | Archive |
|---|---|
| Linux x86-64 | `lingshu-gate-v<version>-linux-x86_64.tar.gz` |
| Linux ARM64 | `lingshu-gate-v<version>-linux-aarch64.tar.gz` |
| Windows x86-64 | `lingshu-gate-v<version>-windows-x86_64.zip` |
| macOS x86-64 | `lingshu-gate-v<version>-macos-x86_64.tar.gz` |
| macOS ARM64 | `lingshu-gate-v<version>-macos-arm64.tar.gz` |
| Docker Compose | `lingshu-gate-v<version>-docker-compose.tar.gz` |

Tagged releases also provide offline Linux Core images for `amd64` and `arm64` plus an application SPDX SBOM. Every native archive contains `SBOM.spdx.json`, `BUILD-INFO.json`, `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and this README. Verify the selected archive against `SHA256SUMS` before extraction; see [Release artifacts](docs/releases.md).

## Support matrix

| Capability | Linux native | Windows native | macOS native | Docker Core |
|---|:---:|:---:|:---:|:---:|
| Console, REST API, `/mcp` gateway | Yes | Yes | Yes | Yes |
| External Streamable HTTP downstream | Yes | Yes | Yes | Yes |
| Managed local stdio downstream | Yes | Yes | Yes | No |
| Explicit managed-container downstream | When a local engine is available | When a local engine is available | When a local engine is available | No |
| Local project build execution | With required host toolchain | With required host toolchain | With required host toolchain | No |
| SQLite persistence | Yes | Yes | Yes | Yes, single Core replica |
| Release architecture | x86-64, ARM64 | x86-64 | x86-64, ARM64 | Linux amd64, arm64 |

Native archives bundle Gate, not every project runtime. Downstream launch and build portability still depends on the project's own toolchain, commands, paths, and dependencies; preflight reports missing requirements before execution.

## Documentation

- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [MCP gateway and downstream servers](docs/mcp-gateway.md)
- [Project delivery](docs/project-delivery.md)
- [Deployment](docs/deployment.md)
- [Operations](docs/operations.md)
- [Local development](docs/local-development.md)
- [Release artifacts](docs/releases.md)

## License

Lingshu Gate is distributed under the Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party components remain subject to their respective licenses; packaged notices are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
