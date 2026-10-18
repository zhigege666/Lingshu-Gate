# Production Docker deployment

[简体中文](DEPLOYMENT.zh-CN.md) · [Package start page](README.md)

This bundle runs the unprivileged Lingshu Gate Core image without mounting a
container-engine socket.

1. For an online deployment, copy `.env.example` to `.env`. For a loaded
   offline image, copy the matching `.env.offline-amd64.example` or
   `.env.offline-arm64.example`; these set `LINGSHU_GATE_PULL_POLICY=never`.
2. Set `LINGSHU_GATE_IMAGE` to the published digest before production use.
3. Set `LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE` to an absolute path for the
   one-time bootstrap password file. It must be readable by container UID
   `10001`; a root-owned `0600` file is not readable by that account.
4. If a browser reaches `/mcp` through a reverse proxy, set
   `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` to its comma-separated exact origins.
   An empty value permits only loopback origins on the service port.
5. Prepare permissions as below, validate with `docker compose config --quiet`,
   then run `docker compose up -d --no-build --wait --wait-timeout 120 core`.
6. Verify readiness at `http://127.0.0.1:8000/readyz` and retrieve the initial
   administrator username from your configured environment.

## Prepare a Linux host with rootful Docker

From this extracted package directory, create the workspace and a new random
bootstrap password. These commands require OpenSSL and `sudo`:

```bash
install -d -m 0700 ./secrets
(umask 077; openssl rand -base64 48 > ./secrets/bootstrap-admin-password)
sudo chown 10001:10001 ./secrets/bootstrap-admin-password
sudo chmod 0400 ./secrets/bootstrap-admin-password
sudo install -d -o 10001 -g 10001 -m 0750 ./workspace
```

In `.env`, replace the example workspace/password paths with the absolute paths
to these two locations. Select a bootstrap username, the published image digest,
your exact proxy address and any required browser origins. Before starting, check
the actual container user can read the secret without printing it:

```bash
docker compose config --quiet
docker compose run --rm --no-deps --entrypoint sh core -c 'test -r /run/secrets/lingshu_gate_bootstrap_admin_password'
docker compose up -d --no-build --wait --wait-timeout 120 core
```

Rootless Docker and Docker Desktop have different host/VM UID mappings; use the
equivalent protected mapping for that engine and run the same readability check.
Do not solve an unreadable secret by making it readable by everyone.

Open the Console through your configured HTTPS entry. Read the password locally
with `sudo cat ./secrets/bootstrap-admin-password`, sign in with the configured
username, change the password and sign in again. The old password/session stops
working. Keep the bootstrap file protected while Compose references it; the
externally provisioned file is not deleted by Gate. The generated
`initial-admin-credentials.json` procedure belongs to the local quickstart.

Keep the service bound to localhost unless a TLS reverse proxy and an explicit
trusted-proxy policy are configured. Set `LINGSHU_GATE_TRUSTED_PROXY_IPS` to
the actual reverse-proxy container or address; never trust an unrestricted
network range.

`LINGSHU_GATE_MCP_ALLOWED_ORIGINS` applies to browser requests carrying an
`Origin` header. Non-browser requests normally omit that header and are not
affected by the browser-origin allowlist.

`SBOM.spdx.json` inventories the Python application runtime dependency closure
and bundled Console production dependencies represented by this release. It is
an application dependency inventory, not an operating-system or container-layer
inventory. Verify it and this archive through the release-level `SHA256SUMS` and
artifact attestation.

## Included guides and optional services

The archive includes paired READMEs, `docs/`, `examples/`, security/release notes and the Project Delivery Skill. See [First authorized call](../../docs/first-call.md) or [首次授权调用](../../docs/zh-CN/first-call.md). Follow the archive's Compose startup instructions before the optional demo override. Packaged deployments use the selected image and do not build from source.

`LINGSHU_GATE_TELEMETRY` is passed to Core and defaults off. Metrics alone needs no exporter credential. Tracing token/CA files need explicit read-only mounts and documented owner permissions. See [Standard telemetry](../../docs/telemetry.md).
