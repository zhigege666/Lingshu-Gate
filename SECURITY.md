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

The source on-demand catalog uses the existing authorization policy before ranking/paging and never grants access during discovery. Selected invocation rechecks the current credential, complete principal, real instance, schema revision and ACL at dispatch and read-only recovery; read scopes cannot gain write access through the adapter. Signed cursors bind identity and current catalog/policy, and every page rechecks authorization. Remote schema-reference retrieval is disabled. The separate management OAuth resource cannot use normal catalog adapters. See [on-demand tools](docs/on-demand-tools.md) for bounds and remaining synthetic versus real-client validation limits.

Schema evaluation has finite structural/expansion budgets and runs after original invocation admission against effective arguments, in a deadline-bound subprocess that is killed and reaped on timeout/cancellation. Current authority, contract and argument policy are rechecked after dispatch-lock waits and before each permitted recovery retry. Rejection before any dispatch produces one original physical `not_invoked` audit with zero attempts. Rejection before a recovery retry preserves prior actual attempts and records `error` without argument/result values; unresolved references produce only a hash/correlation event without names or argument values. Public describe rejects concurrent policy/catalog changes. Grouped calls retain explicit instance/session selection and no read replay. Built-in OAuth verification and in-process proof refresh resolve bounded saved snapshots or explicitly confirmed continuous MCP policies, retaining current owner/client/family/publication and service-lifecycle checks. New tools cannot join selected snapshots; continuous policies include only later eligible published tools. These source checks do not certify real-provider or production deployment behavior.

Invocation identity comparison treats authority collections as sets, while proof fields, reduced authority and numeric ceilings remain strict. The final grouped dispatch guard repeats the existing bounded session/instance/configuration/generation check after private-client initialization; a closed or expired session produces zero business calls and one `not_invoked` audit.

Security fixes target the latest published release and the `main` branch. Older releases may require upgrading to receive a fix. Release archives and container images should be obtained from the repository's official Releases and package pages and verified by digest.

certifi must be 2026.10.19 or later to address [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2). Source installs enforce this floor and locked releases include the updated CA bundle; rebuild old images and packages rather than disabling TLS verification. MCP message budgets default to 32 MiB and remain bounded by administrator configuration; see [configuration](docs/configuration.md).

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
- Memory snapshots collect process names and resource metrics, never command-line arguments or environment values; unknown parameter names can carry credentials too.
- Pin production container images by digest and verify release checksums, SBOM, and build metadata.

The tool catalog's `metadata.gate_access` is an output-only, request-local display snapshot of the existing access decision. It is not a capability or an authorization input. Gate replaces downstream values for visible tools, preserves registry definitions, and reevaluates policy for every invocation.

## Execution boundary

External HTTP management is administrator-only and rechecks current identity, role permissions, token/family scopes and delegation ceilings. The legacy external-config REST adapter retains strict Origin and live-session/action/body-bound CSRF. Both legacy and new management MCP tools reject Console sessions through generic registry entry points. Ordinary business OAuth cannot configure endpoints; the separate default-off [management resource](docs/oauth-external-management-design.md) requires explicit tools, scopes and targets. New `gate_http_mcp_*` tools share the existing operation engine and journal without changing legacy tool fingerprints. Offline plans bind configuration, lifecycle identity, trust and credential revisions; apply/cancel require confirmation and idempotency. Authorized create/update can save exact private-origin permission together with configuration. Delete/revoke/restore are explicit modes. Unknown execution fields and literal header secrets remain denied. Connection/discovery does not publish tools or grant access. Partial or interrupted file/trust/runtime changes are reported for reconciliation; no remote process is installed, restarted or uninstalled. See [the contract](docs/external-mcp-configuration.md).

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

The pinned Bookworm Python base contains `perl-base` 5.36.0-7+deb12u3. Core installs Debian's exact signed security revision 5.36.0-7+deb12u4 for CVE-2026-13221, CVE-2026-42496 and CVE-2026-8376; Critical scan failures remain release blockers. No vulnerability exclusion or lowered scan threshold is used.

## Access-control boundary

MCP groups reference existing instance configurations and grant no access on creation or membership changes. Logical directory and routing reads intersect current identity/token/OAuth ceilings, logical service/tool grants and the exact original instance/tool policy. Complete contracts and advertised versions partition incompatible tools. Connection-bound routing sessions require explicit instance selection, invalidate on configuration/runtime drift, and never choose another peer or replay a write. The internal guard leaves dispatch and physical-tool audit with the existing invoker. Administrator group writes retain current `operations.manage`/`tools.invoke`, confirmation, CSRF for Console, revision CAS and transactional audit; the separate management OAuth resource exposes only explicitly consented configuration and credential administration tools, without group administration. See [the internal adapter contract](docs/mcp-group-routing-contract.md) for lifecycle and generation limits.

The `execution`/`data_source` purpose and existing instance names are administrator-supplied metadata. Public source labels are projected only from currently authorized members; they grant no access, verify no repository/data coverage and do not change tool classification. Legacy groups retain `unspecified`. Purpose changes use the same confirmed, body-bound CAS/audit write and invalidate the existing revision-bound routing sessions and directory cursors; they cannot silently move a query to another source.

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

The development [My authorizations](docs/my-authorizations.md) entry combines personal records without merging credential/protocol identities. Legacy API tokens retain account-following resource authority and unset quotas until explicitly configured. Independent tokens constrain business MCPs by selected snapshots or explicit continuous lifecycle-bound policies, including valid publication for administrators; control tools retain their own permission boundary. Secret creation, policy and redacted audit commit atomically, and the secret is returned once. External-provider grants do not gain continuous scope. Token creation currently has a 5,000-tool/100-MCP candidate limit; a larger owner's smaller existing token can use a bounded quota-only editor with `scope_editable=false`. Per-token quotas share one Core process budget across MCPs and editing does not reset consumed counts. Source/synthetic checks do not verify production capacity or real-client cache refresh.

System credentials and user downstream bindings are encrypted at rest and masked in API responses. Encryption does not replace host access control: anyone who can read both the encrypted store and key material can recover values.

Use `${credential:<id>}` references in manifests instead of plaintext. Per-user downstream values are injected only into that user's isolated HTTP request context. Gate rejects downstream HTTP redirects so those headers cannot be forwarded to another endpoint. Do not configure user-specific secrets for shared stdio processes.

Downstream auto negotiation is restricted to the startup discovery phase and recognized JSON-RPC protocol rejections. Pinned versions never fall back. Legacy HTTP sessions belong to one client and credential context, and session identifiers are redacted from diagnostics. Authentication errors and timeouts do not trigger fallback; business errors do not cause automatic replay. Session expiry allows only the bounded published-read-only recovery above, with unchanged contracts and current authority/policy checks; writes and grouped calls are not replayed. Replacing an executable must preserve the external configuration, credential key material, and database together; keep a stopped-instance backup and the previous package for rollback.

Back up key material with the encrypted data, protect the backup with equivalent controls, and test restoration without printing secrets.

## Out of scope

Reports about a downstream server should go to that server's maintainer unless the issue demonstrates that Gate violates its documented isolation, authorization, redaction, or lifecycle boundary.

## External OAuth boundary

External JWT verification is default-disabled and can be configured through authenticated management APIs. The RS256 resource-server verifier accepts external tokens only at `/mcp`; Console `/v1/*` APIs still require a Gate session or Gate API token. Invalid Authorization never falls back to a cookie. Opaque-token introspection is unsupported.

Exact issuer/JWKS, audience/canonical-resource and client bindings precede current subject-link, active-user and personal-grant lookup. Ordinary role/resource access, published classification, JWT scopes and local delegation all constrain tool access, including administrators. Grant rate/concurrency enforcement is single-process and resets on restart. See [external access](docs/external-connections.md) for the full configuration, verification and revocation contract.

Enabling a local record does not complete external consent or prove a provider/ChatGPT connection. In external IdP mode, Gate does not issue provider tokens, host the provider's authorization/PKCE flow or register clients with that provider. The separate opt-in built-in mode hosts Gate's own authorization server and static client registry. Neither mode starts a tunnel. Synthetic JWT/HTTP tests do not certify a production TLS trust chain or real provider integration.

Shared service credential CRUD requires `credentials.manage.system`, assigned only to the built-in administrator by default. The built-in operator does not inherit shared credential CRUD through `operations.manage`. Personal tokens and downstream credentials retain `credentials.manage.self`. External trust/subject-link management separately requires `external_connections.manage`; personal delegations are always owner-bound. Inbound JWTs, personal downstream credentials and tunnel runtime secrets remain separate.

## Git and delivery network settings

Named network profiles require `system_settings.manage`; network invocation additionally requires `network.use` and the existing operation/tool/token permissions. Proxy endpoints are write-only encrypted values; authentication uses credential references. Profiles and defaults use optimistic revision checks; queued work pins immutable revisions and never falls back to direct networking. Referenced profiles cannot be silently deleted. This development branch adds an optional Native/Linux rootless Podman adapter with actual readiness; missing prerequisites fail closed. It defaults to disabled, uses preloaded digest-pinned images, trusted pinned HTTPS acquisition and secret-free offline project execution, and records persistent phase/container/cgroup outcomes before dispatch. Unknown completion blocks replay/deletion; entire-group termination precedes frozen output validation. Registry-only npm, pnpm 8/9 and Yarn Classic frozen cache installs are implemented. pnpm 10/11 package-ID stores, Berry and Python sandbox caches are explicitly refused; Python retains only its existing upload/direct legacy flow. Host subprocess environment filtering is not isolation, and Core execution remains disabled.

HTTPS source plans pin a full commit, digest, exact host policy and bounded snapshot. SSH, hooks, remote helpers, redirect credential forwarding, automatic submodules/LFS, host global configuration and Docker sockets remain unsupported. Tool preparation is an explicit confirmed stage using official integrity-verified fixed versions in executor-owned caches; it never installs globally. A reviewed adapter must enforce dependency-origin/DNS/egress/resource/cancellation policy and artifact secret scanning, including through proxies. See [Git/network design](docs/git-import-network.md) and [Native provisioning/support](docs/native-executor.md).

## Built-in OAuth boundary

Development source stores tool discovery per business authorization. New and legacy API tokens, built-in OAuth and external local grants default to on-demand; explicit direct mode is isolated by authorization kind and ID. Legacy URL/header mode hints are ignored, including duplicate, unknown or conflicting values; they cannot change the saved mode. Owner-session-only preview/confirmation uses Origin, session-bound single-use tickets, revision checks and transactional audit; dispatch rechecks mode after admission. This presentation setting neither reapproves snapshots nor changes scopes, quotas or management-resource tools. Clients needing full listing select it on the authorization and refresh/reconnect; old mode hints do not cause connection errors. Host plugin selection and global agent rules are outside this setting.

The default-disabled built-in server uses existing Gate password/RBAC identity, explicit per-user tool consent, confidential static clients, S256 PKCE and local RS256 verification. Authorization-server tokens authenticate business `/mcp` or the separately enabled, exact-audience `/mcp/manage`; they never authenticate private Console `/v1` APIs. Each request reloads user, client, grant and refresh-family state and intersects saved snapshots or explicit continuous MCP policies with current permissions/publication and lifecycle identity. Existing snapshot grants are not silently converted; only explicitly continuous policies can include later eligible published tools. SQLite transactions serialize single-use codes and refresh rotation; spent refresh reuse revokes the family, and revocation persists even when returning an error. Access tokens last at most 10 minutes, codes 60 seconds, refresh families an absolute 30 days, all constrained by grant expiry.

Owner-confirmed live tool updates require the actual owner Console session, strict Origin/session-bound CSRF, current permissions and revision/catalog/target-bound confirmation. Preview does not grant access. The writer transaction revalidates dependencies, changes only the specified grant by CAS, consumes the latest confirmation digest and records its redacted audit atomically; failures roll back together. JWT signatures, issuer/resource/client/family bindings, scope intersections, expiry, revocation and quota checks remain. Same-grant tokens follow explicitly updated tools or continuous policies within their individual OAuth scope ceilings; other grants do not expand. Owner-confirmed business quotas default to 6000/min and concurrent 100, and are editable within 1–10000/1–100 in either direction. Quota-only changes preserve stale authority and consumed counters; legacy shrink-only operations and management-resource limits keep their original contracts. Confirmation digests expire within ten minutes, have bounded global/user capacity and contain no tools or secrets. These private APIs must never be exposed by the public proxy.

Private business OAuth candidate pages and selection resolution share the incremental catalog index. Every query applies current owner authority, publication and grant/client ceilings before paging/counting; saved grant IDs do not limit candidate browsing. Pages carry no schemas, have bounded JSON/metadata and are explicitly incomplete. Only explicit, bounded tool selections or continuous service policies reach confirmation/save; global choices exceeding 5,000 tools or 100 MCPs fail without a partial selection. Refresh retains drafts and never adds future services. Cursors/tickets bind the session and current registry/policy generation; post-sync registry changes and current authority changes fail closed. Owner-visible exclusions do not expose hidden services. Administrator API-token invocation does not bypass OAuth publication. See the [candidate contract and evidence](docs/oauth-catalog-scaling.md).

The management resource is default-disabled and accepts only the built-in issuer, an active administrator with live permissions, consented tool fingerprints and exact target/action policies. Credential tools additionally require explicit `credentials.manage.system`; credential actions are distinct from same-ID service actions. Existing grants, JWTs and refresh families do not expand when new tools or client scopes are added. Route-selected trusted audiences reject cross-resource tokens, codes and refreshes without fallback. Dispatch/worker/cached-result checks bind issuer/resource/client/grant/family/expiry and current targets. Target edits retain owner Console session, strict Origin/CSRF, single-use confirmation, CAS and atomic redacted audit. Disabling management revokes only its families. Classification publication and remote execution are not granted. See the [management contract](docs/oauth-external-management-design.md).

Only secret digests and encrypted private keys are stored. Protect and back up `data_dir/oauth-signing.key` with the database. The dedicated browser cookies are Secure/HttpOnly/SameSite=Lax with `/oauth` scope; browser POSTs enforce exact Origin and per-request CSRF. The public UI has an independent asset bundle and does not require Console or `/v1` exposure. Bound requests, admission limits, TTLs and safe errors are documented in [built-in OAuth](docs/builtin-oauth.md). Gate filters OAuth access-log queries; edge/proxy/tracing systems must separately exclude request secrets. Executed synthetic security and browser evidence is recorded in [release validation](docs/release-validation.md); it does not certify real TLS, provider or ChatGPT integration. CIMD, anonymous DCR, multi-tenancy and tunnel management are excluded.

SQLite session purposes enforce the Console/public-consent boundary even if cookie values are copied between names. Existing published-version sessions migrate as Console sessions; public sign-in issues only consent sessions. Missing usernames use the same PBKDF2 verification work as wrong passwords. Anonymous browser requests use bounded, encrypted, short-lived tickets rather than occupying the authenticated pending pool. Authenticated admission has per-user/client/global ceilings, completions release slots, and anonymous/authenticated/protocol rate budgets are separate. Distributed abuse of public sign-in or protocol endpoints still requires edge controls; these bounds do not guarantee availability.

The stateless MCP gateway authenticates every HTTP request for both current and legacy protocols. Tools authenticate again in the dispatch thread after body parsing and queue admission, then intersect current RBAC, published scope, delegation and quotas before calling the downstream runtime with the immutable user ID. Neither handshake nor downstream HTTP/stdio sessions cache the inbound OAuth principal or bearer. Revocation prevents subsequent calls; it does not cancel downstream work already dispatched.

Token/revoke requests have separate low-cost source ingress and credential-failure limits. Only read-only-validated client credentials spend authenticated exchange/refresh/revoke budgets; mutation transactions validate the client again. The shared operation ceilings reserve 180/300/120 requests per minute (600 total), with 30/60/30 per client. Source tracking evicts within its bound; rotating-source/shared-resource abuse still needs edge limits. The session-purpose migration assumes a published Console-only source; unpublished OAuth candidate upgrades are unsupported unless all old sessions are first invalidated offline or a fresh/matching published-version database is used. Old consent sessions must not be migrated as Console sessions.

## Private HTTP MCP trust

HTTP carries unencrypted traffic. Non-loopback HTTP remains limited to canonical RFC1918 IPv4 literals and exact service/IP/port permission, now also bound to the service lifecycle identity. An authorized administrator save or explicitly consented HTTP-management apply creates the reviewed permission; a manifest or offline precheck cannot self-authorize. Direct trust administration retains revision CAS and audit. Revocation survives ordinary save/reconnect; restore must be explicit. Only matching existing configurations receive a one-time legacy migration, and deletion/recreation cannot inherit an old permission. Current policy is checked before connection and dispatch; revoked or unreadable state denies use. Public, link-local, metadata, DNS and noncanonical HTTP targets remain rejected; redirects stay blocked and HTTPS keeps normal TLS verification. See [configuration](docs/configuration.md#private-http-trust).

Shared credential administration uses masked metadata, revision-checked writes, keyed idempotency and explicit sensitive-field redaction for logs and invocation payloads. HTTP usage additionally binds service/origin/lifecycle; live dispatch resolves current authorized headers after rotation. A saved value does not certify downstream authentication. Referenced credentials cannot be deleted and MCP/REST never expose plaintext recovery. See [shared credentials](docs/shared-system-credentials.md).

The independent `gate_http_mcp_test` action is an explicit, ephemeral administrator network test. It requires the separately consented management tool and exact `test` target action for OAuth. For an unsaved private-HTTP draft it permits only that test's validated target without creating reusable permission; revoked or needs-review records remain denied. Every send rechecks current authority, configuration/trust snapshots and target-scoped credential revisions. It never uses personal credential slots, follows redirects, invokes business tools or publishes the discovered catalog. Results contain finite diagnostics rather than upstream bodies or resolved secrets. Console testing requires same-origin, one-use, full-body-bound CSRF; returning a ticket does not authorize a later stale or revoked request. See [connection testing](docs/http-mcp-connection-testing.md).

## Argument policies, integration services and telemetry

Current bounded rules intersect authority at final dispatch. Policy writes require `grants.manage`, exact-body confirmation, revision checks and atomic audit. Pure examples execute nothing; a previous binary does not enforce these policies. Pins grant no access. Result references are credential-bound, process-local and expire in five minutes; every read rechecks authority, contract and any group session.

Connector and OpenAPI adapter use fixed targets, bounded messages and explicit TLS/credential configuration without automatic business replay. Connector, adapter and telemetry credentials are protected plaintext files separate from Core's encrypted store; protect their owner/ACL and backups.

Metrics and traces default off. Telemetry reads require current authentication plus `operations.manage` and `observability.read.all`; these are not globally read-only scopes. Export excludes arguments, outputs, credentials, tool names and target addresses. The private exporter fixes its destination, rejects redirects and ambient proxy/credential settings, bounds memory and shutdown, and adds no business retry. Metrics belong inside the private control plane. See [telemetry](docs/telemetry.md).
