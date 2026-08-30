# Security policy

[简体中文](SECURITY.zh-CN.md)

Lingshu Gate sits between authenticated users and executable downstream services. Treat its configuration, data directory, project-delivery inputs, and operator accounts as security-sensitive.

## Reporting a vulnerability

Use the repository's **Security** tab and **Report a vulnerability** to send a private advisory. Do not disclose exploit details, credentials, private logs, or an unpatched vulnerability in a public issue or pull request.

Include, when available:

- affected version, commit, operating system, and deployment mode;
- the smallest reproducible request or configuration with all secrets removed;
- expected and observed authorization boundaries;
- impact, required privileges, and whether code execution or secret exposure occurred;
- suggested mitigations or a patch.

If private reporting is unavailable, open a detail-free issue asking the maintainers to provide a private channel. Maintainers will acknowledge a complete report, investigate it, coordinate a fix, and publish an advisory when users have an actionable remediation.

## Supported code

Security fixes target the latest published release and the `main` branch. Older releases may require upgrading to receive a fix. Release archives and container images should be obtained from the repository's official Releases and package pages and verified by digest.

## Deployment boundary

- Bind directly to loopback. Put remote access behind an HTTPS reverse proxy and expose only required routes.
- Keep authentication enabled. Change the one-time administrator password immediately and use separate least-privilege accounts.
- Set `LINGSHU_GATE_AUTH_COOKIE_SECURE=true` when the public origin uses HTTPS.
- Set `LINGSHU_GATE_TRUSTED_PROXY_IPS` to the exact proxy address or minimal internal CIDR. Never use `*` on an uncontrolled network. The proxy must replace client-supplied forwarding headers.
- Set `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` to the exact browser origins permitted to call `/mcp`; Gate rejects every other supplied `Origin` with HTTP 403.
- Keep `/data` and `/config` private, backed up, and writable only by the Gate service account. Credential ciphertext and its local key must be protected together.
- Keep the workspace read-only unless a documented operation requires a narrower writable path.
- Run one Core replica per SQLite database. Do not share the SQLite volume between concurrent Gate instances.
- Keep payload logging disabled. Review logs and audit exports before sharing them.
- Pin production container images by digest and verify release checksums, SBOM, and build metadata.

## Execution boundary

Project builds and managed local processes execute code with the privileges of the Gate process. They are not a sandbox for untrusted source code.

- Build and launch only projects whose complete source and dependency behavior you trust.
- Review the deterministic bundle file list before upload.
- Review the exact build plan and network-dependent installation steps before confirmation.
- Do not pass secrets in project archives, manifests, tool arguments, logs, or build commands.
- Treat deployment, overwrite, startup, cancellation, and session abandonment as distinct writes.
- Do not mount a container-engine socket into the Core service.
- A native managed-container target may use a local container engine only after the operator reviews the image digest, mounts, network, and resource limits.

The Docker Core image intentionally does not launch local stdio processes or execute project builds. Use a separately controlled native environment for those operations.

## Access-control boundary

Effective tool access is the intersection of authentication state, control permission, resource grant, published read/write classification, and API-token scope. Tool annotations and discovered schemas are untrusted hints; they never grant access by themselves.

Administrators should:

- classify and publish tools only after human review;
- grant the smallest server and tool resource scope;
- use short-lived, narrowly scoped API tokens where practical;
- review invocation audits and authorization denials;
- re-review new, changed, missing, or reappearing tools after refresh.

## Credential boundary

System credentials and user downstream bindings are encrypted at rest and masked in API responses. Encryption does not replace host access control: anyone who can read both the encrypted store and key material can recover values.

Use `${credential:<id>}` references in manifests instead of plaintext. Per-user downstream values are injected only into that user's isolated HTTP request context. Gate rejects downstream HTTP redirects so those headers cannot be forwarded to another endpoint. Do not configure user-specific secrets for shared stdio processes.

Back up key material with the encrypted data, protect the backup with equivalent controls, and test restoration without printing secrets.

## Out of scope

Reports about a downstream server should go to that server's maintainer unless the issue demonstrates that Gate violates its documented isolation, authorization, redaction, or lifecycle boundary.
