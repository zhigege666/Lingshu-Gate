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

## Docker Compose quick start

From a source checkout:

```bash
mkdir -p runtime/workspace
docker compose up -d --build core
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

The release asset `lingshu-gate-v<version>-docker-compose.tar.gz` contains a deployment-specific `DEPLOYMENT.md` and `.env.example`. After verifying and extracting it:

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
chmod 0600 "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"

docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d
curl --fail http://127.0.0.1:8000/readyz
```

Adjust ownership of the password file so container UID `10001` can read it without making it group/world writable. Rootless container engines and desktop virtualization use different UID mappings; test readability under the actual service account.

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
