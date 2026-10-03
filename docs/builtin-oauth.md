# Built-in OAuth authorization

[简体中文](zh-CN/builtin-oauth.md) · [External identity provider](external-connections.md)

The built-in authorization server is **disabled by default**. It uses existing Gate users, roles, resource grants, published tool classifications, invocation quotas and audit records. API tokens and the external RS256 identity-provider mode remain available. A client secret authenticates the registered application; each person still signs in with their own Gate account and consents to an explicit tool scope.

## Configure without enabling

In **Connection infrastructure → Gate built-in OAuth**, save an HTTPS issuer origin such as `https://gate.example.com`, without a path or trailing slash, and the fixed resource `https://gate.example.com/mcp`. Issuer and resource are trusted administrator configuration; request Host and forwarded Host never determine them. Resource paths other than `/mcp` are not supported in this version. The issuer must route to this Gate instance, and the browser page and its APIs must share that issuer origin.

The page derives authorization, token, discovery and JWKS URLs from the saved issuer. Merely saving configuration does not create a signing key, enable OAuth, start a network service or verify a connection. Initializers create only schema. Use **Generate / rotate signing key** explicitly when preparing a deployment; the private key is encrypted with Fernet in SQLite, using a protected `data_dir/oauth-signing.key` encryption key. Back up this file and the database together, separately from public configuration. Loss of that key fails closed; existing encrypted private keys cannot be recovered by generating a replacement encryption key. On POSIX the encryption key requires mode `0600`; Windows operators must restrict its ACL to the service account.

Register a static client with its display name, **exact HTTPS callback URI(s)** and allowed `tools.read` / `tools.invoke` scopes. No wildcards, fragments, userinfo or reserved OAuth response query parameters are permitted. Existing unrelated query parameters are preserved. Gate generates the client ID and shows the client secret once, only in the creation or rotation response. Save it in the client's secret configuration. Listing clients never returns secrets. Rotating a client secret invalidates the old secret, outstanding codes and existing token families; reconnect the client. Disabling a client denies its next request, and re-enabling does not revive revoked token families.

The one-time secret dialog requires an explicit **Saved, close** acknowledgement, or a confirmation when using its close icon or Escape. Copying to the clipboard does not acknowledge safe storage. A client search with no matches offers **Clear filter**; an empty client registry has its own message.

Client administration and signing-key operations require `external_connections.manage`. Personal grant reads and reductions require `credentials.manage.self`. The management APIs remain under private `/v1/auth/oauth/*`; authorization-server credentials never authenticate those APIs. Gate authentication must remain enabled. The existing external mode may coexist only with the same canonical MCP resource and distinct issuers.

## Enable and connect

Enable only after reviewing TLS, exact callbacks, signing-key backup, user permissions and the proxy allowlist below. Changing issuer/resource requires disabling first. Disabling revokes all token families and pending requests/codes; enabling again requires new user authorization. Old grants remain visible for review or revocation.

Use the client setup that accepts a **predefined Client ID and client secret**, with `client_secret_basic` or `client_secret_post`. This version does not advertise CIMD, dynamic registration or `private_key_jwt`; it cannot be used through a client setup that requires one of those methods. Copy the exact callback currently shown in the ChatGPT connection management page, rather than guessing or substituting an old callback. Consult the current ChatGPT authentication and connection guidance for platform discovery and setup requirements. Compatibility with a real ChatGPT connection must be verified separately.

The client sends `response_type=code`, its exact registered `redirect_uri`, `resource` equal to the configured MCP resource, and PKCE `code_challenge_method=S256`. Requested scopes must be allowed by that client. `tools.read` selects read tools; `tools.invoke` selects write tools. Request both to select both kinds. Gate does not implement implicit, password, client-credentials or anonymous grant flows.

The dedicated `/oauth/consent` page shows the real registered client, fixed resource, requested permissions and authenticated Gate account. The user searches/filter tools across up to 100 MCPs and 5,000 eligible tools, selects explicitly across 50-row pages, chooses a 1–30 day expiry and invocation quotas, and allows or cancels. No tools are preselected. Only currently authorized, published tools appear. A separate Secure, HttpOnly, SameSite=Lax cookie scoped to `/oauth` carries the sign-in; it does not log the user into Console. This session lasts at most 30 minutes and uses existing Gate password verification. Users required to change an initial password must first do so in the private Console.

Session purpose is enforced in SQLite, not only by cookie names or paths. Migration `0007_auth_session_purpose` labels existing published-version sessions as `console`; public login creates only `oauth_consent` sessions. Copying either cookie value to the other cookie name cannot change its purpose. Logout also respects that purpose. A missing username uses a fixed dummy hash through the same 200,000-round PBKDF2 verification path; public login returns the same error and admission limit for missing users and wrong passwords. This equalizes password work, not every observable response time.

This migration assumes a published, Console-only source version. In-place upgrades from earlier **unpublished OAuth candidates are unsupported**: invalidate all their old sessions, including consent and Console sessions, through a separately reviewed offline migration before using the new version, or start from a fresh/matching published-version database. Old candidate consent sessions must never be relabeled as Console sessions. The migration does not identify their provenance or perform this invalidation automatically; do not start the new binary first and clean up afterward.

An older binary does not enforce this new purpose column. Do not roll back against a database that retains public consent sessions; use the matching pre-upgrade backup or a separately reviewed migration that removes those sessions before starting the older version. This development task does not perform a rollback or data deletion.

MCP names come from the actual service manifest; IDs appear secondarily, and missing names are identified explicitly. Search covers tool names, IDs and MCP names/IDs. **All / Read / Write** is a direct selector that defaults to All. **Reset filters** restores search, MCP, access and page defaults while preserving checked tools; **Clear selection** is a separate action.

A request expires after 10 minutes. CSRF/browser mismatch, expired login, changed client settings, changed permissions and repeated submission have explicit error states and recovery actions. Refreshing details recalculates the offered scope. A completed approval cannot return the authorization code a second time: return to the client or start a new authorization. Successful and denied authorization responses preserve state and return the exact fixed `iss`.

## Token and policy contract

| Item | Boundaries |
|---|---|
| Authorization code | Random secret, digest at rest, 60 seconds, single atomic exchange; binds user/grant, client, exact callback, resource, scopes and S256 challenge. Correctly bound reuse also revokes token families for that grant while its digest record is retained. |
| Access token | RS256 with immutable Gate user `sub`, `client_id`, `gid`, `fid`, `aud`, scopes, `jti`, `iat`, `nbf`, `exp`; up to 10 minutes and never beyond grant/family expiry. Local public-key verification makes no network request. |
| Refresh token | Random secret, digest at rest, rotation on every successful refresh. One family has an absolute 30-day ceiling, shortened by grant expiry. Used-token replay commits family revocation before returning `invalid_grant`, including a replay with invalid scope. |
| Scope reduction | Refresh scopes can only narrow. **My connections → Gate built-in OAuth** can remove tools, shorten expiry, lower quotas or revoke. Increasing scope requires a fresh consent. |
| Current policy | Every MCP HTTP request reloads active user, client, grant and family, for both current and legacy handshake protocols. Tool calls authenticate again in the dispatch thread after parsing and queue admission. Handshakes and downstream sessions do not cache the inbound principal or bearer. Current role/resource permission, published classification, JWT scopes and saved tool snapshot all intersect. Reclassified, changed or newly discovered tools do not silently join an old grant. Display-only MCP renames do not change its tool scope. |
| Signing-key rotation | A new encrypted RSA key signs new tokens. Previous public keys remain for 10 minutes; retired keys fail validation. No private key is published in JWKS or returned by management APIs. |
| Quotas | Same per-grant rate/concurrency boundary as external OAuth. Single Core process only; counters reset on restart. SQLite requires a single writer/Core deployment. |

`POST /oauth/revoke` accepts client-authenticated access or refresh tokens and revokes the corresponding family. Unknown or another client's token returns the same success response. A user revoking their grant revokes every family for that grant. Disabled/revoked credentials fail on the next request; in-flight downstream work is not cancelled by revocation.

Spent refresh-token digests survive until the family expires. Expired authorization-code records become eligible for cleanup after a further 10 minutes. Each family permits at most 10,000 rotations, after which a new authorization is required. There are at most 100 registered clients, 10 callbacks/client and 1,000 retained grants/user. Selected tool scope is bounded to 5,000 tools and 100 MCPs. Expired interactions, families and codes are cleaned during authenticated admission or completion; grant history is not automatically deleted.

Anonymous authorize/context traffic uses a browser-bound encrypted ticket with a 10-minute TTL and 16 KiB limit, without creating a pending database row. The ticket key uses standard HKDF-SHA256 with a separate purpose from private-key encryption. It binds the request, browser, CSRF and configuration/client revisions; disabling and re-enabling invalidates old tickets. Migration `0008_oauth_interaction_capacity` restarts any older short-lived interactions. Authenticated pending capacity remains 200 globally, with 5/user and 50/client regardless of IP/cookie rotation. Completion immediately frees that slot and discards the large catalog/request. Small replay tombstones have separate ceilings of 3,072 authenticated, 64/user and 1,024 anonymous completions until ticket expiry. Anonymous cancellation cannot consume the authenticated completion budget. Logout and expired login release pending capacity; expiry cleanup recovers abandoned slots.

## Public proxy allowlist

Expose only these paths with their stated methods. Block all other paths, including `/console`, `/v1`, `/docs`, `/openapi.json` and service-management routes, on the public listener. Internal Console access can use a separate private listener/origin. Do not proxy a catch-all location to Gate.

| Path | Public methods | Purpose |
|---|---|---|
| `/mcp` | Existing MCP methods | Protected MCP protocol, normal bearer/policy checks |
| `/.well-known/oauth-protected-resource`, `/.well-known/oauth-protected-resource/mcp` | GET | Fixed resource metadata and configured issuers |
| `/.well-known/oauth-authorization-server` | GET | Built-in authorization-server metadata |
| `/oauth/jwks` | GET | Public signing keys |
| `/oauth/authorize` | GET | Validate authorization request and open dedicated page |
| `/oauth/consent`, `/oauth/assets/*` | GET | Dedicated UI and its independent compiled assets |
| `/oauth/context` | GET | Browser-bound request/account/tool details and CSRF token |
| `/oauth/login`, `/oauth/logout`, `/oauth/decision` | POST | Same-origin JSON, browser cookie and CSRF required |
| `/oauth/token`, `/oauth/revoke` | POST | Form-encoded, authenticated static-client protocol endpoints |

TLS is mandatory for this mode. Browser POSTs must use the exact issuer Origin; there is no cross-origin API access. Management session writes require their private Console Origin. Public assets include only the independent OAuth bundle; `npm --prefix web run build` builds Console and OAuth separately. Python package data and Docker copy both asset trees. No public path requires Console assets or `/v1/auth/login`.

Bodies have a 5-second read deadline: most endpoints accept at most 32 KiB, consent and reduction accept at most 2 MiB; authorization queries accept at most 8 KiB, context queries 32 KiB, at most 20 fields, and duplicate fields are rejected. Login is limited to 10 attempts/minute/source; authorization and consent to 30; context to 60. Authenticated browser operations use the immutable user ID as the rate identity; anonymous traffic uses the resolved client IP. Source tracking is bounded separately per lane.

Browser/discovery minute ceilings are separate: anonymous authorize 150, sign-in 120, public context/logout 300, anonymous cancellation 60, discovery 240 and authenticated browser operations 400.

Protocol endpoints first enforce inexpensive ingress admission of 60 requests/minute/resolved source **for each endpoint**, before reading a body. They have no shared unauthenticated global protocol budget. Malformed requests stop there; credential syntax/unknown/disabled/wrong-secret failures return the same `invalid_client`, with 10 failures/source/endpoint before `rate_limit_exceeded`. Failure tracking uses the resolved source, never an unverified client ID. Valid credentials can still pass after earlier failed authentication at that source, while the ingress limit has capacity. Classifying credential failures still performs a bounded, cheap read-only client check; it does not take the OAuth writer transaction, sign JWTs or look up/revoke token families.

Only validated client credentials consume the separate operation budgets below. Their global ceilings sum to the original **600/minute**, reserving capacity rather than increasing it. Exchange/refresh/revoke transactions authenticate again against current client state after admission; a concurrent disable or rotation cannot authorize a mutation.

| Protocol operation | Per authenticated client/minute | Shared authenticated operation/minute |
|---|---:|---:|
| Code exchange (also unsupported token grant attempts after client validation) | 30 | 180 |
| Refresh | 60 | 300 |
| Revoke | 30 | 120 |

Protocol ingress and failure tracking each retain at most 4,096 sources per endpoint, with one-minute expiry and least-recently-used eviction; filling this table does not reject every new source. Source limits are best effort under eviction/rotating IPs. Multiple clients behind one resolved proxy source still share that endpoint's ingress limit, and distributed floods still share CPU, sockets, audit/storage and body-reading resources. Compromised authenticated clients can spend their own limits and multiple valid clients can exhaust one operation's shared ceiling. Apply trusted-proxy IP configuration, TLS, connection/body/rate limits and abuse controls at the public edge, including limits on malformed and failed authentication traffic. Arbitrary forwarded headers never determine Gate's identity. These bounds do not guarantee availability or replace edge protection.

OAuth responses use `no-store`. The page denies framing and uses a restrictive CSP and `no-referrer`; request secrets are never sent to third-party assets. Gate's Uvicorn access filter omits queries and masks unknown OAuth paths. Configure proxy, CDN, tracing and WAF logs to exclude all OAuth query/body values, passwords, authorization codes, tokens, PKCE verifiers and client secrets; Gate cannot control their logs. Do not enable request body capture on these paths.

## Review and verification status

This implementation was checked statically, without starting Gate or running OAuth/network/browser acceptance. Automated test code covers exact callbacks, PKCE errors, code expiry/reuse, concurrent code/refresh exchanges, replay-family revocation, scope ceilings, ownership, live disable/revoke, signing rotation, CSRF, cookie-value purpose copying in both directions, legacy migration, dummy password work, anonymous floods, layered capacity, admission separation, secret storage, Host independence, API-token regression and external-JWT regression. Full MCP route tests cover current/legacy discovery followed by repeated calls and revocation, plus revocation between body parsing and dispatch. Browser test code uses synthetic mocked APIs for both languages at 1600×900, 1920×1080, 2560×1080 and 2560×1440, with 100 MCPs / 5,000 tools, filter reset/selection retention, client empty states and one-time secret close protection. Test presence and successful compilation are not executed test results.

Before acceptance, run `uv run pytest -q tests/test_builtin_oauth.py`, the existing external/API-token suites, `npm --prefix web test`, and the new browser tests after building assets. Then exercise real TLS/proxy cookies, metadata, callback registration, discovery, authorized read/write calls, denied scope, concurrent refresh, disable/revoke and signing rotation with a non-production client. No real credentials, accounts, tunnels or connection were configured by this development task. CIMD, DCR, multi-tenancy and tunnel lifecycle management are outside this version.
