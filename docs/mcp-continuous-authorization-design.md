# My authorizations and continuous MCP authorization design

[简体中文](zh-CN/mcp-continuous-authorization-design.md)

Status: frontend and backend implemented after selection of the first in-table concept. My authorizations unifies tokens and connections; new business authorizations default to editable 6000/100 limits without persistent introductory copy. Validated on 2026-10-15 in the `main`, version 0.4.7 working tree; not committed or published. Prior Token and network edits are preserved. The baseline below describes the pre-change source; see the execution record below and the [user guide](my-authorizations.md).

Revised concepts use demonstration data and were generated with built-in Image Gen:

- [My authorizations table](images/console/continuous-authorization/my-authorizations-concept-zh-CN-v2.png)
- [MCP scope editor with editable call limits](images/console/continuous-authorization/mcp-scope-editor-concept-zh-CN-v2.png)

Prompt summary: preserve Gate's light surfaces, blue actions, and compact table; use My authorizations without subtitles, repeated headings, or permanent explanatory banners; use accessible fixed radio choices, left labels/right controls, editable 6000/100 limits, and separate functional scopes from MCP range. Exclude invented OAuth scopes, secrets, and multi-concept montages. Earlier images remain iteration history, not the current implementation target. Example users/names are fictional; this document governs actual copy and semantics.

## Problem and verified baseline

The user wants to authorize an entire MCP once and automatically include tools added by subsequent updates after publication.

Account resource grants already support an entire server: see `web/src/pages/access-grants-page.tsx` and `src/lingshu_gate/access_control.py::_effective_access_map`. User tool grants override user server grants; roles resolve tool overrides within each role before taking the highest level.

Built-in OAuth grants instead store selected tool snapshots. `src/lingshu_gate/oauth_server.py::_grant_tools` restricts resolution to saved tools and requires a matching current snapshot. Existing MCP group selection selects current tools, not future tools. See `web/src/features/external-connections/oauth-api.ts` and `docs/builtin-oauth.md`. External-issuer grants separately require both server and tool allowlists in `src/lingshu_gate/external_connection.py::UserExternalGrant.allows`.

Discovery, classification review, and publication are separate. Contract changes invalidate classification; the implementation stage ran relevant access-control regression tests.

The identified gap was a persistent connection-level server policy. This is now implemented in storage and runtime checks. The following sections retain design targets; executed verification is recorded below.

## Unified management

Keep one navigation entry, My authorizations. An access authorization describes a client accessing Gate through a particular authentication method, resource policy, and lifetime. Gate API token, Gate OAuth, and External OAuth become row attributes and filters. Unify the experience and policy semantics without merging token storage, OAuth grants/families, or protocol implementations.

Source evidence: `web/src/routing/console-routes.ts` requires authentication and `credentials.manage.self` for both existing entries. `personal-workspace-page.tsx` delegates connections to `ExternalGrantsPage`, whereas `App.tsx` renders `PersonalTokensPage` separately. `PersonalToken` in `web/src/api/identity-access.ts` includes name, prefix, scopes, expiry/revocation, last use, and creation time. Creation currently accepts no MCP policy. `auth.py::_principal_from_api_token` builds an account principal with token scopes, not an independent per-token MCP allowlist.

| Authentication method | Creation | Distinct behavior |
| --- | --- | --- |
| Gate API token | Owner creates in Gate | Secret displayed only once; subsequent views identify it by prefix and cannot recover it |
| Gate OAuth | Client initiates owner consent | Shows registered client and exact resource; missing scopes require another OAuth authorization |
| External OAuth | External authentication plus Gate identity/grant configuration | Preserves issuer/mapping constraints; revoking the Gate grant does not revoke the provider token |

Business and management resources remain separate rows even for one client. Management rows use their existing exact-target editor and cannot subscribe to business MCPs. Downstream credentials remain separate because they authenticate Gate to downstream systems.

The unified table shows Authorization name, Authentication method, Access scope, Call limits, Status, Expiry, Actions. Limits compactly show 6000 / min and 100 concurrent, using actual stored values. Names show a token prefix or client/short grant ID. Full identifiers stay in details. Scope summaries distinguish 3 MCPs · 2 continuous from Follows account resource permissions; scope counts are not tool counts. Search names/client/IDs, filter method/resource/status, and default to active records. Do not invent last-use data for OAuth or infer use from creation time.

One Add authorization menu offers Create API token, OAuth setup instructions, and Configure external identity authorization according to actual capabilities. Use the global compact page identity without a duplicate large heading, subtitle, or introduction. OAuth instructions send the owner to the client; Gate cannot fabricate an already-connected OAuth client. Shared operations are details, adjust authorization, and revoke. Unsupported pause, renew, rotate, and rename actions are absent. Historical records are read-only.

Aggregate with `kind + source_id`; never deduplicate by name/client ID. Dispatch mutations to the exact source. A source read failure remains visible without hiding other results or treating the failed source as empty. Counts describe loaded records until all requested sources are available. Sorting/pagination initially operate on the loaded owner dataset; a future backend aggregate requires a separately defined total-count contract.

## Shared editor and API token migration

Retain the selected first concept: MCP rows choose No access, Continuous, or Selected tools using accessible radio controls, with read-only/read-write where appropriate. An unchecked row cannot simultaneously imply an authorized mode. Batch-selection checkboxes, if used, must be distinct from authorization state. Authorization name/method appear above; server-computed differences precede confirmation. No permanent explanatory strips or paragraphs accompany the table.

Functional permissions and MCP resource range are distinct. API tokens retain the existing grouped control-scope picker and identity-specific defaults in a Functional permissions disclosure. MCP selection never auto-enables operations.manage, classifications.manage, or other controls. OAuth does not inherit the entire API-token control-scope catalog.

New API token flow: name/expiry/limits → explicit functional scopes and MCP selection → preview → atomic token/policy creation → once-only secret and client setup. MCP selection starts empty without changing existing functional-scope defaults. A control-only credential explicitly selects no business MCP access; empty business range never means all servers. Preserve secret-close protection; never persist the value in list state, browser storage, or logs. Lost creation responses require readback and explicit handling of unrecoverable secret values, not an automatic second creation.

Legacy API tokens show Follows account resource permissions (existing mode), retaining their existing behavior, including any account-level inheritance of new services. Do not turn them into snapshots or mislabel them as explicit subscriptions. An owner can explicitly convert to an independent MCP range, selecting continuous/selected policies and confirming scope changes. The first version has no switch back to account-following mode; any future such expansion needs explicit preview and confirmation.

Per-token MCP policies require new backend contracts, versions, confirmation, and runtime enforcement. They are not available merely by merging pages. New independent policies constrain business MCP tools while control interfaces keep their own scopes and targets. Existing administrator API tokens may bypass classification; the proposed independent policy requires published classifications and discloses access removed by conversion. Legacy tokens are unchanged by navigation migration.

Remove the duplicate sidebar entry. Explicitly navigate old `#/personalTokens` links to My authorizations with the API-token filter; `#/myConnections` opens the unified list while retaining the existing route ID. Do not rename API/cookie/database/tool identities. Preserve owner authentication and `credentials.manage.self`. Bind editors and late responses to `kind + source_id`, protect unsaved edits, and use each source's actual revision. New API policy CAS/confirmation must be implemented; no invented shared revision replaces existing source versions.

## Editable call limits

The user explicitly requests new business authorization defaults of 6000 calls/minute and 100 concurrent calls, with both fields editable upward or downward. This replaces the earlier design's quota-only-narrowing restriction; expiry restrictions are unchanged.

Current source defaults are 30/1 in `oauth-consent-page.tsx`, external `newGrant`, and the OAuth decision request model, not a confirmed runtime value of 300. The owner editor loads actual values but caps inputs at those values; `_scope_target` and `narrow_grant` also prohibit increases. Existing consent/request ranges are 1–10000 calls/minute and 1–100 concurrent, so the requested defaults fit those bounds. This is source evidence, not a deployed change.

| Scenario | Initial value | Proposed behavior |
| --- | --- | --- |
| New business API token/OAuth/external grant | 6000/100 | User can choose valid positive integers; frontend and omitted-field backend defaults match |
| Existing OAuth, e.g. 300/1 | Actual stored limits | Can explicitly confirm an increase to 6000/100 or a decrease; opening the editor does not change values |
| Legacy API token with no independent quota | Not configured | Do not pretend it already has 6000/100; configuring limits starts a new 6000/100 draft and requires saving |
| Quota-only edit | Existing tools/scopes unchanged | Save without reselecting tools or changing scopes |
| Revoked/expired/non-owner record | Historical values | Read-only; quota updates cannot reactivate it |
| Blank/fraction/zero/negative/out of range | Invalid draft retained | Field validation; no silent fallback to 1, defaults, or prior valid values |
| Read/refresh failure | Unknown current values | Preserve draft; never replace an existing record with creation defaults |

Place two editable InputNumber controls above the MCP table, with left-aligned fixed labels and controls to their right. Related fields may share a row; narrow screens split them into separate left-label/right-control rows. Each limit participates independently in dirty detection, preview, and save.

Preview includes exact before/after quotas; owner confirmation commits with CAS, a single-use ticket, and atomic audit. Extend the explicit live-update operation to allow bounded increases/decreases instead of treating the saved value as a maximum. Preserve the legacy narrow-only PATCH contract, rather than broadening every `narrow_grant` caller. New API-token quotas need real per-token storage and invocation enforcement. Independent management-resource contracts and defaults are not implicitly expanded by this business change. Quota increases never expand scopes, tools, functional permissions, or expiry.

The proposed budget aggregates business tool calls across the authorization's MCPs: token ID for API tokens and grant ID for built-in/external OAuth, shared by families. Directory reads are not tool execution. Saving a quota must not reset consumed-rate counters. Lowering concurrency does not cancel executing calls; new admissions obey the new limit. Committed values apply at subsequent admission/dispatch rechecks, subject to implementation verification of the actual limiter synchronization. Preserve the current single-Core quota boundary. 6000/100 describes configuration, not demonstrated throughput.

## Global UI contract

Apply `web/AGENTS.md` and the paired [UI interaction contract](ui-interaction-contract.md), including UI-01/02/05/08/14 and the centered-dialog/direct-radio supplement. Remove the previous concepts' duplicate large heading, page subtitle, permanent footer guidance, and per-MCP explanatory banners.

Keep only global My authorizations identity, filters, table, meaningful states, and Add authorization. Existing mode/account-following labels are actual state, not explanatory prose. The editor keeps its action title, target, method, real field labels/values, MCP rows, and buttons. Remove generic functional-permission and save-difference paragraphs.

Put detailed inheritance/future-tool/client-cache rules behind contextual, keyboard-accessible help or read-only details; never hover-only. Confirmation still states the target, actual policy/quota changes, and future write consequences. Persistent field errors, regional failures, permission denials, and unknown outcomes retain visible recovery. Short success feedback says Authorization updated. Reuse AntD themes and compact left-label/right-control forms; do not add decorative metrics, educational cards, empty surfaces, or extra workflow steps.

## Proposed policy

Each business connection can choose a different policy for each exact MCP identity:

| Mode | Meaning | Future tools |
| --- | --- | --- |
| Continuously authorize this MCP | Current and subsequently published tools | Included when eligible |
| Selected tools only | Existing exact tool and snapshot semantics | Require explicit selection and confirmation |
| No access | Do not expose this MCP through the connection | Excluded |

Continuous mode explicitly selects read-only or read/write. Read-only includes published read tools; read/write includes published read and write tools. The UI must disclose future write access. Existing selections never imply consent to continuous authorization. Future MCP servers are never subscribed automatically.

Proposed conceptual storage: `server_policies[{server_id, server_binding, mode, access}]`. A continuous policy stores intent; selected mode retains existing tool snapshots. `server_binding` represents a non-reusable lifecycle identity that must be implemented or verified in existing storage; it is not asserted to exist today. Modes are exclusive within a server. The first version has no continuous-mode per-tool exclusions; use selected mode for exceptions.

Effective access intersects current account resource permission, the exact server policy or saved snapshot, current published classification, business resource, client/grant/JWT/family scopes, expiry, and quotas. Explicit account tool denials still apply. OAuth administrators do not bypass classification. A read-only token family never gains write permission through a wider grant. Missing `tools.invoke` requires a new OAuth authorization with that scope; it cannot be manufactured by editing policy.

## Interaction

Use My authorizations → Record → Adjust authorization, with authentication method shown as a field. Initial business OAuth consent uses the same MCP semantics. Account resource grants retain their role as the account ceiling; contextual help explains the independent range.

1. Load existing grants as selected mode without silent migration.
2. Show MCP rows with name, exact ID, authorization mode, read/write ceiling, and current eligible tool count. Search and pagination change the view only.
3. Radio/state labels directly identify continuous mode; contextual help explains future published-tool inclusion. Save confirmation explicitly includes future write consequences. Counts describe current availability, not the permanent scope.
4. Selected mode opens the existing paged picker. Continuous mode opens read-only current-tool details, without misleading individual checkboxes.
5. Saving previews both policy changes and current tool differences, including future inclusion, future write access, and restrictions. A mode change with zero current tool differences still requires confirmation and can be saved.
6. Owner confirmation commits atomically. Short feedback says Authorization updated; cache-refresh instructions remain contextual, not permanent page copy. Existing sufficient OAuth scopes allow reuse of the same bearer.

Removing a server policy stops its inclusion; no implicit retained snapshot is created. Converting to selected mode explicitly previews a complete current authorized snapshot, including off-page tools. Rename destructive draft clearing to Clear authorization scope and confirm the saved difference. Refresh preserves draft policies and recomputes results. Connection summaries distinguish Continuous · Read/write · Currently 24 tools from Selected · 24 tools.

## State and lifecycle rules

| Event | Continuous mode | Selected mode |
| --- | --- | --- |
| Same server upgrade, unchanged tool | Remains available | Available while snapshot matches |
| New tool discovered, classification unpublished | Denied with a publication reason | Unavailable |
| Newly published read tool | Automatically included by read and read/write policies | Owner must select and confirm |
| Newly published write tool | Included only by read/write policy with sufficient token scopes | Explicit selection and sufficient scopes required |
| Schema/classification change | Denied while stale; reevaluate automatically after review/publication | Existing snapshot reconfirmation remains required |
| Read tool becomes write | Excluded by read-only policy; read/write can include after republication | Previous snapshot becomes invalid |
| Account/client disabled, permission removed, grant/family revoked or expired | Deny on subsequent requests and queued dispatch rechecks | Preserve existing denial |
| Explicit tool denial | Account policy still denies | Same |
| Display name changes | Preserve policy when identity is unchanged | Preserve existing behavior |
| Delete/recreate or replace trusted service identity | Invalidate binding and require new confirmation | Do not revive old snapshot authority |
| Read-only family under a write-capable grant | Read-only family remains read-only | Same |
| Offline or zero eligible tools | Retain policy and show the condition | Retain historical details |
| Client caches an old catalog | Gate resolves on next request; explain client refresh | No automatic client refresh promise |
| Catalog/classification unavailable | Fail closed with structured reasons | Same |
| Save response lost | Preserve draft, show unknown outcome, read back before another write | Reuse existing recovery |
| Publication/policy changes during editing | Invalidate preview/confirmation and preserve draft | Same |

Before implementation, verify the actual manifest update, deployment overwrite, and delete/recreate identity lifecycle. Ordinary upgrades and display-name changes retain authorization; changing trust targets must not inherit it merely by reusing a string ID.

## Implementation boundaries

Extend the existing catalog, preview, save, and grant resolution paths. Reuse owner Console sessions, Origin/CSRF checks, short-lived one-use confirmation, CAS, transaction-time permission rechecks, atomic audit, and unknown-outcome readback.

Catalog responses add saved per-MCP mode/access, current effective counts, and exclusion reasons. Previously subscribed servers remain visible when they have no eligible tools. Preview/save use versioned policy fields and bind confirmation to service identity, mode, access, catalog revision, and policy differences. Legacy requests retain snapshot semantics; unknown versions fail closed.

Business `_grant_tools` resolves continuous candidates and intersects current policy and token ceilings. Listing, direct invocation, search/forwarding, and queued dispatch rechecks must share the authority. Do not batch-copy tool grants to every user on publication or use an expanded ID snapshot as the continuous policy.

Initially retain the existing 100-MCP/5,000-tool grant budget. Overflow fails closed with an actionable range-limit reason; never silently truncate, select an arbitrary first page, or downgrade to snapshot mode. Bounded queries are required. The connection-availability tradeoff on future overflow needs explicit implementation review.

Policy changes audit the actor, connection, before/after modes, identity, and access. Later publication is not a fabricated new user-consent event. Invocation audit records policy and classification versions without credentials. Revocation cannot undo downstream effects already executed.

Existing snapshot grants keep their meaning. The revised scope includes the unified list, independent ranges for new API tokens, explicit legacy-token conversion, and built-in business OAuth consent/editing. Account resource grants reuse existing capability; API Token control scopes remain distinct. External-issuer grants can appear in the unified list with their existing editor, but continuous mode requires a separately implemented storage, `allows`, and confirmation extension; an empty tool allowlist is not continuous authorization. Independent `/mcp/manage` keeps its fixed four-tool and exact-target contract and is excluded from business subscription.

## Acceptance and delivery boundary

Implementation tests must use real production types and synthetic HTTP downstreams: same bearer lists/calls newly published tools after initial continuous consent; unpublished tools denied; read/write and JWT/family matrix; reclassification; revocation and queued dispatch; delete/recreate identity isolation; unchanged legacy snapshots; mixed modes and pagination; zero-tool-difference policy confirmation; CSRF/CAS/replay/audit rollback; unknown outcomes; overflow without truncation; business/management isolation.

Unified-management acceptance adds: both old routes reach the correct view; duplicate names/types/grants cannot cross-mutate; partial source failure cannot imply complete totals; absent last-use remains absent; revocation targets only its source record; new token and policy commit atomically; secrets cannot be reread; empty range is not all; legacy tokens remain unchanged; explicit conversion constrains listing and direct invocation; control scopes remain distinct; unified OAuth editing cannot manufacture missing scopes.

This revision additionally requires consistent My authorizations naming, no duplicate intros or permanent explanatory banners, left-label/right-control forms, keyboard-operable radios, matching 6000/100 creation defaults, existing 300/1 readback and confirmed increase to 6000/100, quota-only saves, invalid-draft preservation, quota CAS/audit/unknown-outcome recovery, truthful unconfigured legacy-token limits, and no implicit scope/expiry/management-resource expansion.

UI verification covers both languages, themes, keyboard use, and existing 1600×900, 1920×1080, 2560×1080, and 2560×1440 viewports. Counts come from one backend snapshot; absent counts remain unknown. Concept images use demonstration data.

The initial delivery provided concepts; the confirmed direction was subsequently implemented in production source. Concepts are not runtime evidence. Business OAuth uses tools.read and tools.invoke. API tokens and built-in business OAuth support continuous policies; external issuers retain their existing scope editor and management retains its fixed-tool contract.

Executed validation: 113 focused frontend tests across 15 files, both TypeScript checks, the UI source contract check and both complete Vite builds passed. Build outputs were isolated from packaged resources. OAuth continuous/live/catalog/management regression passed 76 tests, followed by 4 focused lifecycle/consent/paged-confirmation tests. Gateway and continuous-policy regression passed 27 tests and 2 subtests; a subsequently added same-API-bearer ASGI list/invocation test passed separately. Real stores cover compatibility, publication/authority intersections, service recreation, quotas and confirmation boundaries. Downstream peers are synthetic, not external integration acceptance.

The local real-backend browser used synthetic accounts and isolated SQLite at 1600×900: Chinese UI, light/dark switching, unified list, centered table editor, invalid quota rejection, API quota increases/decreases and write-to-read restriction, and OAuth 300/1 to 6000/100. Quota-only confirmation reported zero additions/reconfirmations and read back correctly after saving. The full viewport matrix, English browser, real-client OAuth and client-cache refresh remain unverified; no deployment was performed.

The final token/continuous-policy regression passed 21 tests, and Ruff passed for the relevant Python files. Independent read-only review covered the latest lifecycle confirmation chain and actual screenshots without finding remaining blockers. The temporary service was stopped, its local acceptance port no longer listens, and the temporary viewport was reset. Test groups overlap and their counts are not summed into an overall total.

- [Actual list with synthetic data](images/console/continuous-authorization/runtime-my-authorizations-light.png)
- [Actual MCP editor with synthetic data](images/console/continuous-authorization/runtime-mcp-editor-light.png)

## Subsequent implementation: authorization-level discovery

The subsequent explicit request moves On demand/Full tool list from client settings to each business authorization, with both new and existing authorizations defaulting to on-demand. API tokens, built-in business OAuth and external local grants persist settings isolated by kind and ID. Separate revisions, owner sessions, single-use preview/confirmation and transactional audit protect updates without rewriting scope, snapshots or quotas. URL/header overrides cannot change the authorization mode; generated client configuration omits mode parameters. Global rules and Codex plugin configuration remain unchanged. See the [user guide](my-authorizations.md) for compatibility requirements.

This iteration passed 196 authorization regressions, 42 external-connection/real-JWT/HTTP tests, and 51 gateway/catalog tests with 2 subtests. The final 7 discovery-focused tests passed and overlap the earlier groups; counts are not summed. The 23 focused frontend tests, TypeScript, Ruff, relevant Mypy checks and both full Vite builds passed; documentation links resolve. The isolated real-backend browser at 1600×900 verified independent legacy API/OAuth switching, readback and removal of the duplicate client choice. The temporary service is stopped and its port no longer listens. No commit, push, deployment or real Codex client-cache acceptance was performed.
