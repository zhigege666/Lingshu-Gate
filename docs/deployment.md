# Deployment

[简体中文](zh-CN/deployment.md) · [Documentation index](README.md)

Choose Docker Core for an isolated control plane and external Streamable HTTP gateway. Choose a native package when Gate must launch trusted local stdio processes or execute trusted project builds.

## Deployment matrix

| Mode | Recommended use | Local execution | Persistence |
|---|---|---|---|
| Docker Compose Core | Single-host gateway behind a reverse proxy | No managed stdio or project builds | Named `config` and `data` volumes; read-only workspace bind |
| Native release package | Trusted workstation or dedicated service host | Managed stdio, explicit local managed containers, and project builds | Explicit platform directories |
| Source checkout | Development and verification | Same as native | Developer-selected directories |

All modes use SQLite and support one Gate process per database.

## Released Docker trial

For a local evaluation without a source checkout, use the verified Compose archive and its explicit `compose.quickstart.yaml` / `.env.quickstart.example` path in [getting started](getting-started.md). The trial uses local HTTP, authentication, independent volumes and the released image. Its empty workspace is read-only. The default archive `compose.yaml` remains the HTTPS production configuration.

## Source Docker Compose

From a source checkout:

```bash
mkdir -p runtime/workspace
docker compose up -d --build --wait --wait-timeout 120 core
docker compose ps
curl --fail http://127.0.0.1:8000/readyz
```

The service publishes `8000` only on host loopback by default. It runs as UID/GID `10001`, uses a read-only root filesystem, drops all Linux capabilities, prevents privilege escalation, mounts the workspace read-only, and has bounded temporary storage and resources.

Retrieve the one-time administrator credentials from the private data volume, sign in, and change the password immediately:

```bash
docker compose exec core sh -c 'cat /data/initial-admin-credentials.json'
```

The file is deleted after the password change.

### Compose release bundle

The release asset `lingshu-gate-v<version>-docker-compose.tar.gz` contains package-specific English/Chinese READMEs, both quickstart files and paired `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md`. For production, after verifying and extracting it:

```bash
cp .env.example .env
```

Review every value, select a digest-pinned image, prepare the workspace and bootstrap password file, validate with `docker compose config --quiet`, and only then start the service. The bundled deployment guide is authoritative for the exact files in that release.

## Production Compose

`compose.prod.yaml` requires an explicit image, initial administrator, and password file. A minimal Linux preparation flow is:

```bash
export LINGSHU_GATE_IMAGE='ghcr.io/zhigege666/lingshu-gate@sha256:<digest>'
export LINGSHU_GATE_BOOTSTRAP_ADMIN_USERNAME='bootstrap-admin'
export LINGSHU_GATE_WORKSPACE_ROOT='/srv/lingshu-gate/workspace'
export LINGSHU_GATE_TRUSTED_PROXY_IPS='127.0.0.1'
export LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE="$PWD/secrets/bootstrap-admin-password"

sudo install -d -o 10001 -g 10001 -m 0750 "$LINGSHU_GATE_WORKSPACE_ROOT"
install -d -m 0700 ./secrets
python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"
sudo chown 10001:10001 "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"
sudo chmod 0400 "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"

docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml run --rm --no-deps --entrypoint sh core -c 'test -r /run/secrets/lingshu_gate_bootstrap_admin_password'
docker compose -f compose.prod.yaml up -d --no-build --wait --wait-timeout 120 core
curl --fail http://127.0.0.1:8000/readyz
```

This ownership sequence is for Linux rootful Docker and keeps the file readable only by UID `10001`. Rootless container engines and desktop virtualization use different UID mappings; use the equivalent protected mapping and run the readability check under the actual service account. If validation or readability fails, fix it before starting. Sign in through the configured HTTPS entry; a successful loopback readiness probe does not prove Secure-cookie login works over HTTP.

After first login, change the administrator password and rotate the provisioning secret. Keep the bootstrap file protected while the Compose definition references it.

### Reverse proxy requirements

- Terminate TLS and redirect cleartext HTTP to HTTPS.
- Publish Gate only on a private address reachable by the proxy.
- Set `LINGSHU_GATE_AUTH_COOKIE_SECURE=true` in the service environment.
- Set `LINGSHU_GATE_TRUSTED_PROXY_IPS` to the exact proxy address or minimal internal CIDR; never set it to `*` on an uncontrolled network.
- Replace client-supplied forwarding headers with proxy-generated values.
- Preserve streaming behavior for `/mcp` and event-stream endpoints.
- Apply upload-size, header-size, idle-timeout, and rate limits without truncating legitimate bounded operations.
- Restrict `/docs` if API discovery should not be public.

## Offline Docker image

Tagged releases provide:

```text
lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz
lingshu-gate-v<version>-docker-core-linux-arm64.tar.gz
```

After checksum and attestation verification, load the matching archive:

```bash
gunzip -c lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz | docker load
```

The loaded image is tagged:

```text
ghcr.io/zhigege666/lingshu-gate:<version>-amd64-offline
```

Use `arm64` in both names on an ARM64 host. Set the Compose image variable to that exact local tag. Keep the compressed asset and `SHA256SUMS` as deployment evidence.

## Native package

Verify and extract the archive for the host architecture, then run `start.sh` or `start.cmd`. The launcher uses directories inside the extracted package, which is convenient for a single-user installation.

For a system service:

1. place the package under a root-owned application directory;
2. create a non-login `lingshu-gate` service account;
3. create separate writable data, config, and workspace directories;
4. set absolute `LINGSHU_GATE_DATA_DIR`, `LINGSHU_GATE_CONFIG_DIR`, and `LINGSHU_GATE_ALLOWED_ROOT` values;
5. bind to loopback or a private proxy-facing address;
6. run the executable directly under the service manager;
7. grant write access only to the required directories;
8. configure restart limits and use `/healthz`, `/startupz`, and `/readyz` for monitoring.

Do not run Gate as an administrator or root merely to make a downstream command work. Fix ownership or use a narrower dedicated execution account.

## Custom host directories

The supplied Compose files use named volumes for `/data` and `/config`. If you use host bind mounts, including an Unraid template, the final host paths are your deployment's responsibility. A bind mount hides the image's prepared directory tree: the image's build-time ownership and `/config/mcp.d`, `/data/home` and `/data/cache` directories do not initialize a replacement host path.

Review the actual mount sources and targets after editing a template or changing an instance directory. A container name or a template's default path does not prove that the selected host path was prepared.

| Container path | Host preparation for the default Core user |
|---|---|
| `/data` | UID/GID `10001:10001` must be able to enter and write the data directory and access the existing database and its parent directory. |
| `/data/home`, `/data/cache` | Prepare writable home and cache directories when binding `/data`. |
| `/config/mcp.d` | Prepare this directory under the actual `/config` host source; the service needs read, write and traversal access. |
| `/workspace` | Keep the mount read-only; provide read and traversal access only for the intended workspace. |

For a **new, empty installation** on Linux rootful Docker, choose the final host root first. This example stops if the root already exists:

```bash
gate_root=/srv/lingshu-gate-instance
(
  set -eu
  if sudo test -e "$gate_root" || sudo test -L "$gate_root"; then
    printf '%s\n' 'Inspect the existing installation before changing ownership or modes.' >&2
    exit 1
  fi
  sudo install -d -o 10001 -g 10001 -m 0750 \
    "$gate_root" "$gate_root/data" "$gate_root/data/home" "$gate_root/data/cache" \
    "$gate_root/config" "$gate_root/config/mcp.d" "$gate_root/workspace"
)
```

For existing data, inspect the selected paths, existing owners, modes and any ACLs before making a targeted change. Preserve existing file modes and protected credential files; do not apply unconditional recursive `chmod` or `chown`. Rootless Docker and Docker Desktop require their actual UID mapping. An optional SSH-directory bind is a separate path to review; its presence does not enable local process execution in Core.

Check the same image, identity and mounts that the final service will use. This command inspects directory metadata and access without starting Gate, reading secrets or creating probe files:

```bash
gate_image='ghcr.io/zhigege666/lingshu-gate@sha256:<digest>'
docker run --rm --network none --read-only --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --mount "type=bind,src=$gate_root/data,dst=/data" \
  --mount "type=bind,src=$gate_root/config,dst=/config" \
  --entrypoint sh "$gate_image" -ec '
    id
    for path in /data /data/home /data/cache /config/mcp.d; do
      stat -c "%n uid=%u gid=%g mode=%a" "$path"
      test -d "$path"
      test -r "$path"
      test -w "$path"
      test -x "$path"
    done
  '
```

Replace the example image digest and host paths with the selected deployment values, and include any additional mounts or database-parent path you actually use. These access checks do not prove a database transaction can succeed. A successful `--version` only tests the executable's version path; it does not initialize storage, load configurations or start HTTP.

Complete acceptance by starting Gate with the reviewed configuration, checking stable running/health state and `/readyz`, and reviewing startup storage diagnostics and the last configuration scan. Confirm expected downstream configurations separately; an empty new instance is allowed. HTTP asset checks and a rendered sign-in page provide additional evidence for the Console, while login and downstream calls need their own authorized checks. See [configuration-directory and scan state](operations.md#configuration-directory-and-scan-state).

## Health probes

| Endpoint | Meaning | Orchestrator action |
|---|---|---|
| `/healthz` | Process and HTTP stack respond | Restart only after repeated failure |
| `/startupz` | Initialization completed | Hold traffic until successful |
| `/readyz` | Core storage and request path can serve | Remove from routing while failing |

A single unhealthy downstream server should not make the entire gateway unready. Monitor downstream state separately through server status and diagnostics.

## Backup

Back up `data` and `config` as one consistent, encrypted unit. Workspace backup policy depends on the managed projects.

For SQLite deployments:

1. stop Gate cleanly;
2. copy the entire data and config directories, including credential key files;
3. record application version, image digest or build metadata, backup time, and file hashes;
4. restart Gate and verify readiness;
5. test restoration in an isolated host without printing credentials.

Do not copy a live SQLite file as the only backup. Do not back up ciphertext without its key material, and do not store the backup with weaker permissions than the live service.

## Upgrade

1. Read the release notes and verify `SHA256SUMS`, artifact attestation, SBOM, and `BUILD-INFO.json`.
2. Record the running version and image digest.
3. Stop Gate and take a consistent backup.
4. Install the new native package or set the new digest-pinned container image.
5. Start one Gate instance.
6. Check startup and readiness, sign in, inspect database and configuration load, list downstream state, and execute one authorized read-only tool.
7. Review audit writes and error logs before ending the maintenance window.

Never start old and new binaries concurrently against the same SQLite database.

## Rollback

If the previous release can still read the persistent data, restore the previous executable or image digest and restart one instance. Otherwise, stop Gate, preserve the failed state for investigation, and restore the matching pre-upgrade data and config backup before starting the previous version.

Rollback is a destructive operational decision. Resolve exact backup paths and versions first; do not automate deletion of an unknown volume or data directory.

## Public built-in OAuth paths

The optional [built-in authorization server](builtin-oauth.md#public-proxy-allowlist) adds a dedicated `/oauth/consent` UI and independent `/oauth/assets/` bundle. Follow its exact route/method allowlist; keep the Console root `/`, `/assets/`, its icons, legacy `/console`, `/v1`, OpenAPI and administration private. The issuer is a fixed HTTPS origin, the resource ends in `/mcp`, and authorization browser/API requests share that issuer origin. No callback or discovery URL is inferred from Host. Enable Secure Console cookies when the private Console also uses TLS, and allow forwarded headers only from explicitly trusted proxy IPs. Backup SQLite and protected `data_dir/oauth-signing.key` together. Strip OAuth query/body values from edge logs and enforce size/rate limits there. Deployment compatibility and real TLS/browser/OAuth acceptance have not been verified by static compilation.

The schema upgrade preserves published-version Console sessions with an explicit Console purpose; public consent sessions have a distinct persisted purpose. Anonymous authorization tickets do not occupy the authenticated interaction pool, whose global/user/client limits and completion budgets are documented in the guide. Public and authenticated admission budgets are separate, but distributed login/protocol abuse still needs proxy connection/rate/body limits and trusted IP handling. Keep a single Core process; these controls and per-grant invocation counters do not constitute a distributed availability guarantee.

Older binaries ignore the new session purpose column. An OAuth-enabled installation must not roll back against a database retaining public consent sessions. Restore the matching pre-upgrade backup, or separately review a migration to remove those sessions before running the older binary. Schema readability alone is insufficient to preserve this authorization boundary.

The session-purpose migration supports published Console-only source versions. In-place upgrades from early unpublished OAuth candidates are unsupported: their old sessions must all be invalidated offline before starting this version, or use a fresh/matching published-version database. Never preserve an old candidate consent session as a Console session; the migration cannot infer its provenance.

Token/revoke ingress is source-limited before body parsing; read-only client validation precedes authenticated operation budgets (exchange 180, refresh 300, revoke 120 per minute globally; 30/60/30 per client). Unauthenticated failures cannot spend these budgets. Ingress/failure source tracking is bounded with eviction, so edge enforcement remains necessary for rotating IPs, shared proxies, connection/body floods and audit/storage load. Restrict trusted forwarded IP handling and apply separate endpoint/failed-authentication edge limits; do not treat the reserved operation budgets as an availability guarantee.

## 0.5.0 upgrade and optional services

Migrations `0022_tool_preferences` and `0023_tool_argument_policy` add persistent preferences and rules. Stop the writer and consistently back up database, configuration and credential keys before upgrading. A previous binary does not enforce argument policies; rollback requires its matching backup and reconciliation of subsequent changes.

Native and Compose bundles include paired guides and `examples/`. The [first-call guide](first-call.md) uses a separate demo process or a sidecar sharing Core's loopback network. Connector and OpenAPI adapter also run separately. Core remains unprivileged with a read-only root and no engine socket. [Telemetry](telemetry.md) defaults off.
