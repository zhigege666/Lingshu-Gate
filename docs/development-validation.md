# 0.4.3 candidate validation

[简体中文](zh-CN/development-validation.md) · [Configuration](configuration.md) · [Built-in OAuth](builtin-oauth.md)

This record covers the 0.4.3 candidate on `recovery/config-after-v042`, based on main `247ffb4a9a9477af66cf03a08082e7d76fb76f71`. It includes the retained configuration/startup/origin work and the enabled defaults, apply feedback, scope dialogs, HTTP negotiation and owner-confirmed live grant updates. The exact review commit and CI results are reported with the PR. A candidate and green local checks do not establish formal publication.

## Executed checks

| Check | Observed result | Scope |
|---|---|---|
| Full Python tests | 1,264 passed in 303.07 seconds | All backend tests at version 0.4.3, with the fixed Playwright peer supplied |
| Live grant and existing OAuth regressions | 151 passed in 109.66 seconds | 44 new live-scope/upgrade cases plus 107 existing OAuth cases |
| Frontend unit tests | 422 passed in 69 files | All existing adapters/presentation checks and scope-difference behavior |
| TypeScript and static UX contract | Passed | Source checks, separate from browser or independent visual acceptance |
| Console and independent OAuth builds | Passed | Existing large-chunk warnings retained |
| Relevant browser scenarios | All 137 passed across the full run and targeted corrections | Configuration, HTTP trust, enabled defaults/apply, public consent, personal grants and built-in tool origins/review |
| Ruff and mypy | Passed; 107 source files | Final production source and tests |
| Repository identity, source version and Compose syntax | Passed | Identity policy, existing version checker with `v0.4.3`, static Compose configuration and whitespace |
| Candidate payload and Markdown checks | Passed | No database/archive/image/key/log payloads staged; secret-pattern audit clean; changed local document links resolve |

The main browser run passed 132 and failed five locators: two public-consent MCP choices still expected displayed names rather than the specified single-line IDs, two quota-confirmation cases used the previous dialog/button names, and one pending-mode check did not include the dialog-hidden background tab. Corrections retained filtering, selection, no-write-before-confirmation, quota, revocation and pending assertions. Three then passed together; the remaining selector cases first exposed AntD's duplicate hidden accessibility option, and passed after targeting the visible option content. This is not a single all-green 137-case run. Original failures remain locally. The first unit run passed 421 and failed an obsolete claim that broader tools always require another OAuth flow; its assertion now requires explicit Gate confirmation, existing scopes and no repeated client OAuth flow. Historical optional UI failures and their budgets/assertions were not changed.

Two initial backend fixtures incorrectly assumed that changing a writer to viewer removes read permission. They now actually revoke personal credential-management permission, preserving the denial assertion; all 34 first live cases then passed. Subsequent expanded and full runs include write access, classification/resource reconfirmation and bounded confirmation state. Earlier draft implementation, source and failure evidence are preserved outside the candidate; that user-facing workflow is excluded from this release.

## Same-bearer execution and boundaries

Synthetic HTTP tests obtain a real signed access token through `/oauth/token`, discover only MCP A and deny MCP B, then use the owner's private Console session to read options, preview A+B and explicitly confirm the update. **The exact same bearer then lists and successfully calls B through `/mcp`.** Normal HTTP refresh preserves B. Another grant for the same owner/client remains A-only and cannot call B. These cases cover read and write tools under both 2025-11-25 and 2026-07-28 inbound protocols, using an isolated safe synthetic downstream that records actual dispatch.

Preview alone grants nothing. JWTs and families are not re-signed or widened. Separate cases retain a narrower read-only family, reject missing grant scopes, preserve the existing `tools.invoke` ceiling after removing its last write tool, and reject quota/expiry increases. Owner/session/Origin/CSRF, wrong identity/resource, current permission/classification loss, revisions, bound target, expiry, replacement, replay, capacity and concurrency fail closed. An injected audit failure rolls back grant mutation and confirmation consumption; retry after recovery commits one update and one audit.

## Upgrade, UI and integration limits

The nonempty upgrade fixture constructs the published 0.4.2 schema with unchanged `0006_builtin_oauth`, `0008_oauth_interaction_capacity` and `0009_mcp_http_trust` registrations. Actual `create_app()` upgrades and starts twice: 17 old identity/policy/OAuth/trust tables and old migration timestamps remain unchanged, with only `0009_oauth_scope_confirmations` newly recorded. A pending confirmation digest survives restart; old sessions/API/access tokens, an outstanding authorization code and a bounded refresh remain usable. The earlier draft migration was never published and is not registered here. No real data was removed; this is a synthetic upgrade, not a user's deployment/backup validation.

Scope editing/details were exercised at 1600×900, 1920×1080, 2560×1080 and 2560×1440, in English/Simplified Chinese and light/dark themes. Fixtures cover 100 MCPs, 5,000 tools and 1,000 owner grants. Checks retain fixed controls/actions, one main tools scroll, full-set search/pagination, ID-only choices with name search, explicit differences, failure recovery, duplicate/pending protection, keyboard close/focus and late-response isolation. Screenshots are local engineering evidence and were inspected; independent root visual acceptance remains separate. Mocked screenshot health metadata uses a synthetic older version to demonstrate backend-derived display rather than a hardcoded frontend release value.

The fixed test-only peer is `@playwright/mcp@0.0.83` with `playwright-core@1.64.0-alpha-1790635538000`. Three actual loopback handshake/list cases are included in the full run, covering precise initial HTTP rejection, automatic legacy negotiation and explicit-modern failure. No browser tools, real profile or new product dependency are used.

All credentials, accounts, clients and keys are synthetic fixtures in temporary databases. No production grant/trust/service or NX2 deployment was changed, and no screenshot/archive export was performed. Gate rechecks live scope on the next discovery/call; it advertises `listChanged=false` without a push stream. Actual ChatGPT cached-tool refresh and external callbacks/TLS remain separate integration checks. Formal native/Compose/offline packages, checksums, SBOM, provenance and published body must still be verified by the existing release workflow after exact-head review and merge. The production safe Git executor remains unavailable.
