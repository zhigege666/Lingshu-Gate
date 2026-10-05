# 0.4.4 validation record

[简体中文](zh-CN/release-validation-0.4.4.md) · [Release overview](../packaging/release-notes.md)

This release branch starts from main `5fc3aaba94955e243598783166479136797733e4` (immutable 0.4.3). It selects only external HTTP configuration, separate management OAuth, exact target authorization, Console/consent controls and the bundled Delivery Skill contract. Account-menu cleanup, group routing, catalog caching and large-catalog search from other development commits are excluded. The backend health version remains the single source for sign-in and Console.

## Executed validation

Frozen Python/frontend dependencies installed successfully. Ruff, mypy (116 source files), repository identity, source-version/tag comparison, Compose configuration, frontend type/UX source checks, all 426 frontend tests (70 files), and Console/OAuth builds passed. Wheel and sdist were built as 0.4.4. The four external-tool Skill input tables match the application models, including forbidden unknown arguments.

The complete backend run recorded 1,359 passed, 10 failed and 3 skipped. Nine failures returned 503 while public assets had not yet been built; the other failure was checkout mode 700 on two tracked 100755 release scripts. After building the assets and restoring local executable modes, all 10 failed tests passed with unchanged assertions. A separate complete built-in OAuth run passed 107 tests. The existing pinned Playwright MCP peer was then supplied: all three previously skipped interoperability tests passed. These are separate runs, not a claimed single all-green invocation.

Browser and local release-bundle validation are in progress. Existing historical validation records describe their own source trees, not this branch. Mocked consent/management browser tests do not verify a real OAuth client or peer.

## Real HTTP service acceptance

Use a separately approved nonproduction target on the operator's nx5 deployment. Do not change production credentials or infer authority from a successful business connection.

1. Confirm the running backend reports 0.4.4 after deployment, trusted HTTPS issuer/resource URLs are saved, an active signing key exists, and the current user is an administrator with `operations.manage` and `tools.invoke`. Enable the default-off management resource explicitly. Keep Console and `/v1` private; expose only the required OAuth/discovery/MCP routes.
2. Register or explicitly edit a confidential client's management-resource allowlist and allowed scopes. Preserve its one-time secret acknowledgement without copying the secret into screenshots or notes. Create a separate client connection to the exact `https://gate.example.test/mcp/manage` resource. Verify the actual client requests the required management scopes and the consent screen displays that exact resource, selected tools and exact target/create-update actions.
3. Consent only a disposable exact server ID such as `acceptance-http`. Discover the selected subset of the four `gate_mcp_config_*` tools. A business `/mcp` bearer must fail at `/mcp/manage`; management discovery must contain no business or unrelated built-in tools. This remains real-client acceptance, not synthetic test evidence.
4. Use the already approved external HTTPS service and existing managed credential references. If the service uses private HTTP, its exact service/IP/port trust must already exist through a separately approved administrator action. Plan with `mode=create`, `connect=false`, `refresh_tools=false` and `probe=false`; verify no peer request or persistence occurred. Show the actual caller-known endpoint and redacted returned digests/actions before confirmation.
5. If authorized, create a new plan with `probe=true,probe_confirmed=true` and a bounded timeout. Confirm the temporary probe closes without registering tools. To connect, create a plan with `connect=true,refresh_tools=true`; apply the reviewed plan with its unchanged ID/digest/actions, a fresh idempotency key and `confirmed=true` within five minutes. Poll its `operation_id` until terminal. Retain persistence/connection/discovery/cleanup states, current config digest and classification-review counts. Saved or queued does not establish success.
6. Verify the current service connection and discovered tool snapshot independently. New/changed tools must still require classification review; no access grant or classification publication is implied. Retry an interrupted response only with identical business inputs/key; an uncertain terminal write requires operator reconciliation. Update requires the raw saved configuration digest from `gate_mcp_config_status`, not a canonical delivery digest.
7. Explicitly test owner target changes, token/grant revocation and queued-operation authority loss on this disposable target. A removed target or revoked grant must fail before later persistence/connection/discovery. Old plans become stale; narrower JWT/family scopes cannot expand. Cancellation and any cleanup/delete remain separately authorized writes.

Record redacted IDs, digests, state transitions, actual client scope request and service observations. Do not retain bearer tokens, client secrets, credential values or private endpoint details in public release evidence.

## Acceptance still required

Independent root review, real-client management scopes, real-peer/socket/DNS behavior and deployment acceptance remain pending. File persistence, runtime state and SQLite are not one transaction; deadlines remain cooperative. The safe Git/proxy executor, group invocation/routing and large-catalog search are not implemented by this release.

No tag, main merge or publication is performed by this branch's author. After review and merge, the existing formal workflow must produce and verify all five native targets, Compose, two offline Core images, application SBOM, image digests and SHA256SUMS (11 assets), including provenance and published title/body readback. Local builds do not establish cross-platform release acceptance.
