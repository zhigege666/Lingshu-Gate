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

The tool catalog's `metadata.gate_access` is an output-only, request-local display snapshot of the existing access decision. It is not a capability or an authorization input. Gate replaces downstream values for visible tools, preserves registry definitions, and reevaluates policy for every invocation.

## Execution boundary

The development external-configuration workflow is administrator-only, with current Console-session/API-token, role-permission and delegation checks. Console REST writes require strict Origin and a live-session/action/body-bound single-use CSRF ticket; API bearer authentication remains separate. Ordinary OAuth cannot configure endpoints; [administrator OAuth is still a design](docs/oauth-external-management-design.md). Its plans bind target/configuration/credential digests, actor and management connection, actions and expiry; apply and cancel require explicit confirmation/idempotency. Unknown execution fields and literal header secrets are denied; existing private HTTP trust cannot be created through this workflow. Connect/refresh reuse one strict discovery and classification gate before registry replacement, preserving first new/changed counts without publication or grants. Cleanup checks operation ownership even without a client, cancellation rereads terminal state under the writer lock, and interrupted runtime application retains unknown state. Interrupted/unknown completion requires operator reconciliation, with no automatic write replay or claim that a remote process stopped. See [the external configuration contract](docs/external-mcp-configuration.md) for cooperative deadline and one-target limitations.

Project builds and managed local processes execute code with the privileges of the Gate process. They are not a sandbox for untrusted source code.

Manifest validation is read-only and never executes its command or a version probe. Pinned manager startup uses only service-administrator registered Node/JS CLI paths outside project/data/manifest directories; project command paths or PATH cannot select a probe. Protect the deployment registry and installed tools against unauthorized writes. Metadata checks and timeout/download restrictions do not prove tool integrity. Exact version probes occur only inside the existing authorized startup lifecycle; legacy unpinned manifests retain their explicit execution boundary.

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

Expired external HTTP sessions may be re-established during an authorized call. Automatic replay is limited to one attempt for a published read-only classification with unchanged tool metadata. Writes, unpublished classifications, and changed definitions are not replayed; reconnection never publishes classifications or changes grants. Per-user session recovery retains that user's credentials and does not reuse the shared discovery session.

Incoming MCP handshake compatibility does not create an authenticated session or cache permissions from `initialize`. Both protocol paths authenticate every HTTP request, enforce the same Origin allowlist, and recheck access for discovery and invocation. Requests carrying current-protocol metadata must pass current header validation; they cannot silently downgrade to legacy framing.

Tool-discovery classification and grant snapshots are scoped to one request and are not shared between principals or retained for later calls. The next discovery or invocation reads current grants, expiration, and classification state again. Sectioned server-detail reads keep the existing `operations.manage` boundary and return only the requested diagnostic data; selecting a section does not bypass authorization or manifest credential masking.

Administrators should:

- classify and publish tools only after human review;
- grant the smallest server and tool resource scope;
- use short-lived, narrowly scoped API tokens where practical;
- review invocation audits and authorization denials;
- re-review new, changed, missing, or reappearing tools after refresh.

## Credential boundary

System credentials and user downstream bindings are encrypted at rest and masked in API responses. Encryption does not replace host access control: anyone who can read both the encrypted store and key material can recover values.

Use `${credential:<id>}` references in manifests instead of plaintext. Per-user downstream values are injected only into that user's isolated HTTP request context. Gate rejects downstream HTTP redirects so those headers cannot be forwarded to another endpoint. Do not configure user-specific secrets for shared stdio processes.

Downstream auto negotiation is restricted to the startup discovery phase and recognized JSON-RPC protocol rejections. Pinned versions never fall back. Legacy HTTP sessions belong to one client and credential context, and session identifiers are redacted from diagnostics. Authentication errors and timeouts do not trigger fallback; expired sessions and business errors never cause automatic replay. Replacing an executable must preserve the external configuration, credential key material, and database together; keep a stopped-instance backup and the previous package for rollback.

Back up key material with the encrypted data, protect the backup with equivalent controls, and test restoration without printing secrets.

## Out of scope

Reports about a downstream server should go to that server's maintainer unless the issue demonstrates that Gate violates its documented isolation, authorization, redaction, or lifecycle boundary.

## External OAuth boundary

External JWT verification is default-disabled and can be configured through authenticated management APIs. The RS256 resource-server verifier accepts external tokens only at `/mcp`; Console `/v1/*` APIs still require a Gate session or Gate API token. Invalid Authorization never falls back to a cookie. Opaque-token introspection is unsupported.

Exact issuer/JWKS, audience/canonical-resource and client bindings precede current subject-link, active-user and personal-grant lookup. Ordinary role/resource access, published classification, JWT scopes and local delegation all constrain tool access, including administrators. Grant rate/concurrency enforcement is single-process and resets on restart. See [external access](docs/external-connections.md) for the full configuration, verification and revocation contract.

Enabling a local record does not complete external consent or prove a provider/ChatGPT connection. In external IdP mode, Gate does not issue provider tokens, host the provider's authorization/PKCE flow or register clients with that provider. The separate opt-in built-in mode hosts Gate's own authorization server and static client registry. Neither mode starts a tunnel. Synthetic JWT/HTTP tests do not certify a production TLS trust chain or real provider integration.

Shared service credential CRUD requires `credentials.manage.system`, assigned only to the built-in administrator by default. The built-in operator does not inherit shared credential CRUD through `operations.manage`. Personal tokens and downstream credentials retain `credentials.manage.self`. External trust/subject-link management separately requires `external_connections.manage`; personal delegations are always owner-bound. Inbound JWTs, personal downstream credentials and tunnel runtime secrets remain separate.

## Git and delivery network settings

Named network profiles require `system_settings.manage`; network invocation additionally requires `network.use` and the existing operation/tool/token permissions. Proxy endpoints are write-only encrypted values; authentication uses credential references. Profiles and defaults use optimistic revision checks; queued work pins immutable revisions and never falls back to direct networking. Referenced profiles cannot be silently deleted. Git/import/proxy-test/configured-install execution has no production isolated adapter and fails closed. Host subprocess environment filtering is not isolation, and Core execution remains disabled.

HTTPS source plans pin a full commit, digest, exact host policy and bounded snapshot. SSH, hooks, remote helpers, redirect credential forwarding, automatic submodules/LFS, host global configuration and Docker sockets remain unsupported. Tool preparation is an explicit confirmed stage using official integrity-verified fixed versions in executor-owned caches; it never installs globally. A reviewed adapter must enforce dependency-origin/DNS/egress/resource/cancellation policy and artifact secret scanning, including through proxies. See [Git/network design](docs/git-import-network.md).

## Built-in OAuth boundary

The default-disabled built-in server uses existing Gate password/RBAC identity, explicit per-user tool consent, confidential static clients, S256 PKCE and local RS256 verification. Authorization-server tokens authenticate only `/mcp`. Each request reloads user, client, grant and refresh-family state and intersects saved tool snapshots with current permissions/publication; widening a classification or discovering tools cannot widen an existing grant. SQLite transactions serialize single-use codes and refresh rotation; spent refresh reuse revokes the family, and revocation persists even when returning an error. Access tokens last at most 10 minutes, codes 60 seconds, refresh families an absolute 30 days, all constrained by grant expiry.

Owner-confirmed live tool updates require the actual owner Console session, strict Origin/session-bound CSRF, current permissions and revision/catalog/target-bound confirmation. Preview does not grant access. The writer transaction revalidates dependencies, changes only the specified grant by CAS, consumes the latest confirmation digest and records its redacted audit atomically; failures roll back together. JWT signatures, issuer/resource/client/family bindings, scope intersections, expiry, revocation and quota checks remain. Same-grant tokens follow explicitly updated tools within their individual OAuth scope ceilings; other grants do not expand. Confirmation digests expire within ten minutes, have bounded global/user capacity and contain no tools or secrets. These private APIs must never be exposed by the public proxy.

Only secret digests and encrypted private keys are stored. Protect and back up `data_dir/oauth-signing.key` with the database. The dedicated browser cookies are Secure/HttpOnly/SameSite=Lax with `/oauth` scope; browser POSTs enforce exact Origin and per-request CSRF. The public UI has an independent asset bundle and does not require Console or `/v1` exposure. Bound requests, admission limits, TTLs and safe errors are documented in [built-in OAuth](docs/builtin-oauth.md). Gate filters OAuth access-log queries; edge/proxy/tracing systems must separately exclude request secrets. Executed synthetic security and browser evidence is recorded in [release validation](docs/release-validation.md); it does not certify real TLS, provider or ChatGPT integration. CIMD, anonymous DCR, multi-tenancy and tunnel management are excluded.

SQLite session purposes enforce the Console/public-consent boundary even if cookie values are copied between names. Existing published-version sessions migrate as Console sessions; public sign-in issues only consent sessions. Missing usernames use the same PBKDF2 verification work as wrong passwords. Anonymous browser requests use bounded, encrypted, short-lived tickets rather than occupying the authenticated pending pool. Authenticated admission has per-user/client/global ceilings, completions release slots, and anonymous/authenticated/protocol rate budgets are separate. Distributed abuse of public sign-in or protocol endpoints still requires edge controls; these bounds do not guarantee availability.

The stateless MCP gateway authenticates every HTTP request for both current and legacy protocols. Tools authenticate again in the dispatch thread after body parsing and queue admission, then intersect current RBAC, published scope, delegation and quotas before calling the downstream runtime with the immutable user ID. Neither handshake nor downstream HTTP/stdio sessions cache the inbound OAuth principal or bearer. Revocation prevents subsequent calls; it does not cancel downstream work already dispatched.

Token/revoke requests have separate low-cost source ingress and credential-failure limits. Only read-only-validated client credentials spend authenticated exchange/refresh/revoke budgets; mutation transactions validate the client again. The shared operation ceilings reserve 180/300/120 requests per minute (600 total), with 30/60/30 per client. Source tracking evicts within its bound; rotating-source/shared-resource abuse still needs edge limits. The session-purpose migration assumes a published Console-only source; unpublished OAuth candidate upgrades are unsupported unless all old sessions are first invalidated offline or a fresh/matching published-version database is used. Old consent sessions must not be migrated as Console sessions.

## Private HTTP MCP trust

HTTP carries unencrypted traffic. Non-loopback HTTP is allowed only for canonical IPv4 literals in the three RFC1918 ranges after a real active administrator with `operations.manage` explicitly confirms the exact service/IP/port. The service-owned SQLite policy defaults to empty; manifests cannot self-authorize and OAuth/operator identities cannot approve it. Policy changes use revision CAS and audit events. Precheck, save, apply, connect, reconnect and requests read current trust; revoked or unreadable policy denies the operation. Public, link-local, metadata, DNS and noncanonical HTTP targets remain rejected. Redirects are blocked and HTTPS keeps normal TLS verification. Protect the database from direct unauthorized writes. See [configuration](docs/configuration.md#private-http-trust).
