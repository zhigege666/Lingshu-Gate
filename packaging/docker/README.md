# Docker deployment bundle

This bundle runs the unprivileged Lingshu Gate Core image without mounting a
container-engine socket.

1. For an online deployment, copy `.env.example` to `.env`. For a loaded
   offline image, copy the matching `.env.offline-amd64.example` or
   `.env.offline-arm64.example`; these set `LINGSHU_GATE_PULL_POLICY=never`.
2. Set `LINGSHU_GATE_IMAGE` to the published digest before production use.
3. Set `LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE` to an absolute path for the
   one-time bootstrap password file and restrict that file to its owner.
4. If a browser reaches `/mcp` through a reverse proxy, set
   `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` to its comma-separated exact origins.
   An empty value permits only loopback origins on the service port.
5. Create the workspace directory, then run `docker compose up -d`.
6. Verify readiness at `http://127.0.0.1:8000/readyz` and retrieve the initial
   administrator username from your configured environment.

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
