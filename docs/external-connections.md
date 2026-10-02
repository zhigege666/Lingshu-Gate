# External OAuth resource access

[简体中文](zh-CN/external-connections.md)

Gate implements a **default-disabled JWT resource server for `/mcp`**. Administrators can configure trusted issuers, public signing-key locations, client IDs, resource mappings and identity links; users can enable narrowly scoped local delegations. Enabling those records does not issue an OAuth token, complete provider consent, start a tunnel, or prove a ChatGPT connection. `connected=false`, `provider_verified=false` and `oauth_authorized=false` retain those distinctions.

Only `/mcp` accepts external JWTs. `/v1/*`, including personal summaries, token creation and these management APIs, continues to require a Gate session or Gate API token. An invalid or malformed Authorization header never falls back to a valid session cookie. Opaque external access tokens and introspection are not supported.

## Choosing the network path

Gate has exactly two enabled external connection types: `secure_mcp_tunnel` and `direct` HTTPS; `disabled` is the off state. Cloudflare, frp, Nginx Proxy Manager and ngrok are **operator-managed network choices**, not additional Gate modes. Gate does not install, configure, supervise or rotate credentials for their daemons. The examples below are topology/configuration placeholders, not commands to execute. Keep external access disabled until the network and identity checks below have been completed.

| Network choice | Gate mode | Reachability and ownership |
|---|---|---|
| Secure MCP Tunnel | `secure_mcp_tunnel` | Official client beside the private Gate HTTP listener; outbound control-plane connection. Operator owns the client and tunnel lifecycle. |
| Cloudflare named tunnel | `direct` | Operator-managed `cloudflared` publishes a stable HTTPS hostname backed by a private origin. |
| frp plus public Nginx Proxy Manager | `direct` | Private `frpc` reaches public `frps`; the public TLS proxy forwards only approved paths to the restricted forwarded port. |
| Your existing public reverse proxy | `direct` | Public HTTPS proxy already has a private route, VPN or deliberately configured forwarding path to Gate. |
| ngrok, optional | `direct` | An operator-managed endpoint relays to the private Gate origin; use a stable HTTPS address suitable for the registered resource and OAuth configuration. |

### Private tunnel with the official client

Use the [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) and [official client repository](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md). A suitable topology is `ChatGPT → hosted tunnel → official client sidecar → Gate HTTP /mcp`. The client host needs outbound HTTPS on port 443 to the API host listed in the official guide, or its documented mTLS endpoint when control-plane mTLS is configured. Gate does not need a public inbound listener for this path.

For a same-host sidecar, a target such as `http://127.0.0.1:<GATE_PORT>/mcp` is a **local target placeholder**, not Gate's public resource URL. Separate containers have separate loopback interfaces: supply the actual private service address, restrict its network, and use TLS if that hop crosses an untrusted boundary. Obtain the tunnel ID and endpoint from the real management page; choose and pin a reviewed compatible client build rather than copying an old release number. Do not expose the client's admin UI. The [client configuration reference](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) documents HTTP targets, sidecar startup waiting, secret references and separately trusted OAuth discovery origins.

The tunnel runtime API key authenticates the shared machine channel, **not a ChatGPT user**. Keep it in operator-managed secret storage, separate from Gate personal API tokens and downstream credentials. Gate stores only the configured references. Tunnel rewriting of protected-resource URLs requires explicit `resource_mappings` from the actual advertised audience to `canonical_resource_url`; never disable audience validation. Provider browser authorization remains a separately reachable provider endpoint. Do not assume discovery carries the user's bearer or that tunnel readiness proves user consent. Consult the [configuration contract](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) for the selected client version.

### Direct HTTPS choices

- **Cloudflare named tunnel:** create a persistent tunnel and route a stable hostname to a restricted origin. The operator runs [cloudflared](https://github.com/cloudflare/cloudflared); its [outbound connector model](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/) avoids requiring a public origin IP. Configure [published-application routing](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/) and path restrictions explicitly. A separate edge login/interstitial must not silently replace Gate's MCP bearer contract; test client compatibility if adding edge authentication. Do not treat a temporary quick-tunnel address as a durable audience or callback.
- **frp → public Nginx Proxy Manager:** the private `frpc` reaches an operator-controlled public `frps`; an HTTPS host in [Nginx Proxy Manager](https://nginxproxymanager.com/) forwards to the resulting restricted upstream. The [frp repository](https://github.com/fatedier/frp) documents NAT traversal and transport TLS; that transport security is distinct from the browser/client-facing HTTPS certificate. Restrict the forwarded backend port to the proxy, keep both administration surfaces private, and provision the public hostname/certificate in the proxy. Follow the [NPM guide](https://nginxproxymanager.com/guide/) for its own setup. Exact listener/forward-port and container-network values are deployment-specific placeholders, not a Gate-supplied turnkey stack.
- **Your public proxy:** terminate verified HTTPS at an already reachable proxy and provide a route from it to Gate. A reverse proxy alone cannot traverse NAT; a public address, explicit port mapping, VPN or outbound tunnel must provide that reachability. A certificate alone does not provide a network path.
- **ngrok, optional:** its [HTTPS endpoint documentation](https://ngrok.com/docs/gateway/endpoints/http) describes agent endpoints and managed TLS termination. Confirm hostname stability, applicable limits, idle timeouts and any intermediary authentication before using that address as a trusted resource. Gate does not manage an ngrok account or agent.

### Public surface and proxy contract

Publish only the MCP resource and required discovery paths: `/mcp`, `/.well-known/oauth-protected-resource`, and `/.well-known/oauth-protected-resource/mcp`. Forward only methods supported by the deployed MCP transport. Do **not** publish the Console, `/v1/*` management APIs, `/docs`, `/openapi.json`, diagnostic endpoints or proxy/tunnel admin panels on this external MCP host. Apply an explicit deny/default-404 rule for other paths; keep Console access on a separate private administrative route. The authorization provider owns its own browser authorize/token/JWKS endpoints; do not expose Gate administration to make OAuth work.

For `direct`, set `endpoint` to the exact public HTTPS `/mcp` URL and map accepted audiences explicitly to Gate's canonical HTTPS resource. Preserve `Authorization`, MCP protocol/session headers when used, `WWW-Authenticate` and the discovery response body; do not inject a shared Gate API token into all requests. Discovery must resolve without borrowing a user's downstream credential. Configure `LINGSHU_GATE_TRUSTED_PROXY_IPS` to the actual immediate proxy address or minimal trusted CIDR, never an unrestricted `*`; the proxy must replace spoofable forwarding headers. See [deployment requirements](deployment.md#reverse-proxy-requirements).

Disable response buffering/caching where the negotiated transport streams; validate SSE delivery, disconnects and session cleanup rather than assuming an ordinary JSON request proves streaming works. Set bounded connect/read/idle limits that accommodate the intended operations. Do not blindly retry a timed-out write; inspect its recorded outcome first. Preserve normal TLS certificate verification on public and trusted-provider paths. Any edge limits and client-version compatibility require deployment testing; this guide does not assert that a third-party proxy has passed Gate integration tests.

### Staged acceptance, then enablement

1. Record the chosen topology, exact public resource, canonical/audience mapping, trusted issuer/JWKS and allowed OAuth client ID. Obtain callback/registration values from the current provider and client management pages, not an old example. Start with Gate's external configuration disabled.
2. Verify network/TLS, unauthenticated discovery and the authentication challenge. Check that management/Console paths remain inaccessible on the MCP hostname. Verify the provider's browser authorization path separately. Do not log real bearer tokens or secret headers as evidence.
3. Bind the verified provider `(issuer, subject)` to a dedicated Gate test user. Assign narrowly scoped Gate resources and a **read-only** personal external grant. Verify a permitted read call and filtered `tools/list`; guess an unauthorized tool ID and prove refusal with zero downstream calls.
4. Only after the read checks pass, enable a narrowly scoped write grant for a safe synthetic action. Confirm writes remain denied outside that exact Gate-resource/delegation/JWT-scope intersection, including for an administrator's delegated token. Verify that another user's grant or downstream credential cannot be used.
5. Disable/revoke/expire the test grant or remove its Gate resource permission. Reuse the old token/session and verify the **next** request is refused; do not promise cancellation of already dispatched work. Exercise quota rejection, timeout handling and streaming recovery without blindly replaying writes.
6. Record separate transport, real provider OAuth and real Gate authorization results. Local `enabled`/readiness flags are not evidence of provider consent or connectivity. Actual tunnel startup, public routing, provider registration and persistent credentials remain deployment actions requiring their own authorization; this documentation update performs none of them.

Official network references above were consulted on 2026-10-01. No client binaries were downloaded or run and no release is certified by this guide.

## Trust configuration

`external_connections.manage` controls `GET/PUT /v1/auth/external-connection/config` and subject-link management. The built-in administrator has this capability by default. The authenticated status endpoint `GET /v1/auth/external-connection` reports readiness without revealing shared runtime-secret references. Gate authentication must remain enabled.

Configuration is persisted in SQLite and changed through the authenticated API. `LINGSHU_GATE_EXTERNAL_CONNECTION_ENABLED=true` still fails startup: the environment flag is not an alternative enablement path. PUT requires `expected_revision` (initially `0`); stale writes return `409`. Unknown fields and raw secret/token fields are rejected. A disabled record may be incomplete; `enabled=true` requires the complete trust contract.

Example **disabled** direct-resource configuration, using documentation-only hosts:

```json
{
  "expected_revision": 0,
  "enabled": false,
  "mode": "direct",
  "endpoint": "https://gate.example.test/mcp",
  "canonical_resource_url": "https://gate.example.test/mcp",
  "trusted_issuers": ["https://identity.example.test"],
  "issuer_jwks": [["https://identity.example.test", "https://identity.example.test/jwks"]],
  "client_allowlist": ["example-client"],
  "resource_mappings": [["https://gate.example.test/mcp", "https://gate.example.test/mcp"]]
}
```

| Field | Meaning |
|---|---|
| `mode` | `disabled`, `direct`, or `secure_mcp_tunnel`; selecting tunnel mode does not run a tunnel |
| `endpoint` | Public HTTPS resource endpoint; required in direct mode |
| `canonical_resource_url` | Gate's canonical resource; defaults to `endpoint` when omitted |
| `trusted_issuers` / `issuer_jwks` | Exact issuer strings and one administrator-pinned HTTPS JWKS URL per issuer |
| `client_allowlist` | Exact accepted `client_id`/`azp` values |
| `resource_mappings` | Exact advertised-audience to canonical-resource pairs; every target must equal this deployment's canonical resource |
| `tunnel_reference` / `runtime_secret_reference` | `tunnel:ID` and `credential:ID` references required for tunnel-mode readiness; never raw runtime secrets |

Resource, issuer and JWKS URLs require HTTPS and cannot contain user information, query parameters or fragments. Duplicate/ambiguous resource mappings are rejected. Neither the Host header nor a URL supplied inside a token establishes trust. Configuration readiness validates the local contract; it is not a provider or network probe.

When the enabled configuration is valid, `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/mcp` publish the canonical resource, configured authorization servers and supported scopes. Disabled/unready metadata returns `404`. MCP authentication challenges reference the configured resource origin, not the request Host header.

## Identity links and personal delegations

Administrator APIs:

- `GET/POST /v1/auth/external-subject-links` list/create links containing `issuer`, `subject`, `user_id` and `enabled` (default `false`). The issuer must already be trusted and the Gate user active.

Binding lists support server-side `q`, `offset`, and `limit` search/pagination, including Gate display names, usernames and stable IDs. Each link includes a minimal `user` summary; unavailable users retain the linked ID without an inferred name. `GET /v1/auth/external-subject-links/user-options` uses the same `external_connections.manage` capability and returns only active-user labels for binding, not role or credential data. Creating or enabling a binding rechecks the target user’s active status. The Console shows the name/username first and a copyable ID below it. This does not change the existing user-deletion cascade.

- `PATCH /v1/auth/external-subject-links/{id}` changes `enabled` with `expected_revision`; it does not silently reassign an identity.
- `DELETE /v1/auth/external-subject-links/{id}` disables the link. Duplicate identity assignments, missing links and revision conflicts fail explicitly.

A verified exact `(iss, sub)` resolves through a current enabled link to an active Gate user. Token-supplied user IDs, email addresses or grant IDs cannot choose that identity.

`credentials.manage.self` controls personal `GET/POST /v1/auth/external-grants` and `GET/PATCH/DELETE /v1/auth/external-grants/{id}`. Every request is owner-bound, including administrators; guessed IDs owned by another user return `404`. The payload contains `enabled` (default `false`), `client_id`, exact `server_allowlist`/`tool_allowlist`, `access` (`read`/`write`), future timezone-aware `expires_at`, `rate_per_minute` and `concurrency`. Wildcard resource IDs are rejected.

Saving a scope intersects currently published tools with current Gate capabilities/resource grants and the caller's token/delegation ceiling. Unknown or unauthorized resources return `403` without disclosing names. Enabling also requires enabled complete trust configuration, an allowed client and an enabled subject link; missing activation prerequisites return `409`. Only one unexpired, non-revoked enabled grant can match a user/client pair. Explicitly linked identities from multiple trusted issuers may share that same user/client delegation; there is no automatic email-based identity merge. PATCH requires `expected_revision` and advances the policy version; a disable-only PATCH needs just `enabled=false` and the revision, so loss of resource access does not prevent disabling. DELETE revokes the grant; repeated revocation is idempotent and revoked records cannot be edited.

A later approved setup therefore configures trust, binds the provider subject to a Gate user, reviews/publishes tools and assigns ordinary Gate access, then enables the user's client-specific delegation. Provider consent and token issuance happen outside Gate. Use `activation_errors`, `scope_currently_authorized` and the record's `state` to diagnose local readiness; an enabled record is not evidence of an external login or live connection. `limits_enforced=true` describes an effectively enabled local grant, not provider consent; inactive records report it as false.

## JWT verification and authorization

The verifier uses [PyJWT's signature and claim validation](https://pyjwt.readthedocs.io/en/stable/api.html) with a fixed algorithm allowlist. This tree accepts only RS256 public RSA signing keys of at least 2048 bits. It requires `kid`, exact `iss`, nonempty `sub`, `aud` and `exp`; `nbf` and `iat` are checked when present. `typ` must identify an access token: `at+jwt` is accepted, while `JWT` (including an omitted header type) also requires the signed `token_use=access` claim. Explicit `token_use=id` or any other token purpose is rejected. Token headers containing `jku`, `x5u`, embedded `jwk` or `crit` are rejected.

Every audience in a token must have an exact trusted mapping to the configured canonical resource. `client_id` or `azp` must identify an allowed client; when both occur they must agree. `scope` must be a space-separated string. Discovery advertises `tools.read` and `tools.invoke`; the existing compatible `mcp.read`/`mcp.write` scope names retain their Gate semantics. No scope, including `*`, overrides the user's Gate permissions or the local delegation.

JWKS fetching uses only the pinned HTTPS URL, normal TLS verification, a five-second fetch deadline covering DNS/headers/body and a 256 KiB/64-key bound. Waiting for an issuer refresh lock is separately bounded to five seconds. At most two daemon fetch workers run, with no pending queue; exhausted slots fail closed. It sends no bearer token, follows no redirect and inherits no proxy configuration. Token URLs are never fetched. Keys are cached for 300 seconds; an unknown key can trigger a refresh no more often than every 30 seconds. Expired-cache refresh failures fail closed. These are key-cache limits, not a claim of immediate issuer-side key revocation.

Final tool authority is **current Gate role/resource access ∩ local delegation ∩ verified JWT scopes ∩ published tool policy**. `tools.read` permits authorized read-only calls; writes require `tools.invoke`. OAuth administrators cannot bypass delegation limits or unpublished classifications. Discovery filters unauthorized tools before returning names/counts; a guessed call target is rejected before downstream dispatch. Links, active users and grants are reread for each request, so disablement, expiry and revocation affect the next request; already dispatched work is not retroactively cancelled.

OAuth invocation quotas apply per grant before downstream dispatch: admitted invocation attempts use a sliding 60-second rate window, and a concurrency slot is released in `finally`. Exceeding either limit returns a protocol tool error without a downstream call. Counters are in-process, single-Core limits; they do not survive restart or coordinate multiple processes. Ordinary role/resource authorization and quota checks must both succeed.

## External integration boundary

The [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) describes a private-network transport. Its runtime API key is not the end-user identity. Keep that runtime secret, personal Gate API tokens and individual downstream credentials separate. The user's Authorization is for the MCP main path; tunnel discovery is a separate channel. Tunnel resource-URL rewriting requires an explicit trusted audience/canonical mapping. It does not automatically host the provider's browser authorization page. A shared downstream connection does not prove an individual user's downstream credential works.

This implementation does not operate an authorization server, issue provider tokens, implement opaque-token introspection, host a provider authorization/PKCE flow, perform CIMD/DCR/client registration, or download/start a tunnel client. Actual provider discovery, callback/client settings, external HTTPS/TLS deployment and a ChatGPT/Tunnel connection still require separate integration validation. Use actual provider/client-management values; no example callback is certified here. Jobs, file references, results and audit paths require their own user-isolation checks when introduced; no new OAuth job/file API is claimed. Do not blindly retry a timed-out write.

## Repeatable verification

```bash
timeout 120 uv run pytest -q tests/test_external_connection.py tests/test_external_connection_management.py tests/test_delegated_access_scope.py tests/test_external_jwt_verifier.py tests/test_external_oauth_http.py
```

Policy/management tests cover disabled defaults, revisions, scope intersections, identity/grant ownership and revocation. `tests/test_external_jwt_verifier.py` separately checks RSA/JWT verification and the bounded production JWKS fetch path. `tests/test_external_oauth_http.py` exercises signed synthetic JWTs against a real local Gate HTTP server, local JWKS HTTP service and downstream HTTP peer with dispatch counters and personal credentials. Its injected JWKS fetcher maps one fixed trusted HTTPS fixture URL to the local HTTP peer; it does **not** validate a production HTTPS certificate chain, real OAuth provider, browser authorization-code exchange or tunnel. Report actual test results separately from implemented coverage; mock Console tests and earlier navigation screenshots do not establish OAuth acceptance.

Further references: [ChatGPT authentication](https://developers.openai.com/plugins/build/auth), [tunnel-client configuration](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md), [connectors](https://github.com/openai/tunnel-client/blob/master/docs/connectors.md), and [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization). A later deployment must pin and validate client compatibility; no release is certified by this source change.

## Console setup guide

Open **Connection infrastructure → Setup guide**. The four steps keep instructions next to the fields: network path, token verification, users/grants, and verification. **Save configuration and continue** explicitly saves the disabled draft; enabling verification still requires its own confirmation. The saved configuration is authoritative. Only the step number is kept in browser session storage; unsaved form input is guarded when leaving and is not silently persisted as a secret. Existing deployments can use **Edit verification configuration** directly.

Where to obtain values:

- **Cloudflare:** Dashboard → Networking → Tunnels → your tunnel → Routes → Add route → Published application. Service URL is the private Gate origin. Use the public hostname with `/mcp` as the external endpoint. Follow the [current dashboard guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/) and restrict exposed paths.
- **Issuer/JWKS:** Read `issuer` and `jwks_uri` from the identity provider's discovery document. Keycloak documents `/realms/{realm-name}/.well-known/openid-configuration` in its [endpoint guide](https://www.keycloak.org/securing-apps/oidc-layers). Client ID comes from the registered integration, not its client secret; verify the JWT's `client_id`/`azp`. Gate requires RS256 and a fixed trusted HTTPS JWKS mapping.
- **Tunnel:** Use the actual tunnel ID from [Platform tunnel settings via the official guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Associate the target workspace and check organization-level Read + Use permission. Runtime secrets stay in operator-managed secret storage; Gate receives references only.
- **ChatGPT:** As checked on 2026-10-01, developer mode is under Settings → Security and login. Use ChatGPT Plugins to add a developer app; choose a URL or Tunnel as applicable. Follow the [current connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt) when account or workspace policy changes the available UI.

The final step checks saved configuration only. It never probes the provider, starts a tunnel, issues tokens or declares OAuth connected. Verify discovery and a read-only tool call separately, then correlate the audit record. A 401 suggests token/trust validation; a 403 requires checking identity links, delegation, current tool publication and effective user access. Those are investigation starting points, not proof of the particular failure cause.
