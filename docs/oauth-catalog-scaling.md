# OAuth catalog scaling — development candidate

[简体中文](zh-CN/oauth-catalog-scaling.md) · [Built-in OAuth](builtin-oauth.md)

This candidate uses `test/oauth-catalog-paged-20261005`. It combines the accepted scope-selection UI, saved-grant verification and the shared on-demand catalog through public integration input `d99be556ff48e018792268abeb7c5a22c5517476`. The original UI and Stage A branches remain unchanged. This is source integration, without release publication or real-client acceptance.

## Stage A: saved-grant authentication

Previously, token verification projected every tool available to the owner and enforced the 5,000-tool catalog ceiling before intersecting the saved grant. The regression reproduces HTTP 401 for an otherwise valid one-tool grant after its owner gains more than 5,000 candidates.

Verification now uses the database grant's explicit IDs. One atomic registry lookup returns only those definitions; current owner permission, published classification, resource, client/grant/family/JWT scope ceilings and saved snapshots remain authoritative. Missing, unpublished, changed or withdrawn targets do not appear in the principal. Signed JWT `tools`/`tool_ids` claims cannot add targets. Stored grants beyond 5,000 tools or 100 MCPs fail before registry lookup. The existing refresh and expiry rules remain; a refreshed bearer undergoes the same bounded verification.

The single-tool invocation path also synchronizes only that definition instead of discarding a return value containing the entire classification table. Other classification-list APIs keep their existing response contract. `OAuthServer._grant_tools` is the shared bounded projection seam for verification, verified-principal refresh and management authority. Atomic lookups return copies of frozen definitions so callers cannot mutate registered policy or schema without a new revision.

## Historical Stage A evidence

The results below belong to source `d460f5461196c6d45416e1c25cf3e41743e20ac0`, based on main `d4786fd368e932bc758ea29da1a597c9d9551794`; they are not measurements of the later public integration or Stage B.

The targeted scaling and atomic-registry suite passed 16 tests. It uses exactly 5,000 synthetic services and 50,000 published tools, issues grants while their selected targets are within the existing limits, then grows the remaining catalog. It verifies the original and refreshed bearer, successful selected invocation, unselected denial, publication/access withdrawal, client/family ceilings, forged signed tool claims and stored selection limits. Full-registry and full-classification-list projections are forbidden during measured authentication and invocation. The existing OAuth, live scope, management-resource, delegated-access, external-OAuth and access-control regression set passed another 246 tests. Ruff, mypy (116 source files), the web build, source-version and repository-identity checks passed.

| Saved grant tools | Definition targets per verification | Full registry projections | Median verification (ms) | Refresh + verification (ms) | Incremental verification peak (bytes) |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 7.400 | 137.953 | 19,466 |
| 100 | 100 | 0 | 9.110 | 135.054 | 406,203 |
| 5,000 | 5,000 | 0 | 205.035 | 344.464 | 21,617,711 |

These are author-executed synthetic measurements, not production latency guarantees. Verification latency is the median of three executions without allocation tracing. The peak is a separate `tracemalloc` execution and excludes fixture construction and the already resident 50,000-tool registry. Refresh timing includes signing and verification. Reproduce from the source checkout with `uv run pytest -q -s tests/test_oauth_catalog_scaling.py tests/test_registry_concurrency.py`.

## Stage B: implemented private candidate catalog

Business grant responses explicitly advertise `scope_catalog_mode: "paged"` when the shared candidate port is configured. The Console then uses `GET /v1/auth/oauth/grants/{grant_id}/scope-catalog`, never a partial legacy `tools` array. The unchanged legacy scope-options contract remains available within its existing bound; public initial consent still has its existing bound.

The private catalog supports `view=tools|groups|unavailable`, up to 100 items, keyword search, exact MCP ID and published access filters. Each response declares `complete: false`, opaque `next_cursor`, stable `catalog_revision`, CSRF, grant/client scope ceilings, live family limits and exact whole/matching tools/read/write/MCP counts. Keyset pagination can traverse the full candidate directory without an offset ceiling. Group counts cover the whole eligible service, even when a read/search filter found it. No schemas or descriptions are returned. Whole-page JSON is bounded by `max_bytes` (8–64 KiB), including tickets/counts; only complete items are trimmed, with a cursor for the remainder.

`POST .../scope-selection` is a read-only, session/Origin/CSRF-bound resolver. `all` and `read` replace the draft from the entire current eligible directory, ignoring display filters/pages. `read` requires a published `read` classification. `groups` adds or clears explicit MCPs; clearing examines only bounded draft/saved IDs. `ids` validates explicit draft IDs independently of the displayed page. Every result returns explicit `tool_ids`, `available_ids`, generic `unavailable_ids`, authoritative selected/difference/write counts and up to 100 MCP selected counts. Summary metadata is limited to at most 100 requested IDs (50 by default) and a 2–64 KiB budget. ID arrays retain the full bounded selection; the metadata budget is not a whole-response budget. Exceeding 5,000 tools or 100 MCPs returns a structured limit error, without a partial selection or grant mutation.

Refresh preserves draft IDs and limits, revalidates availability and returns the quick mode to Custom. Later services never join automatically. Errors retain the draft. Invisible targets reveal no names or service metadata; unavailable reasons are paged only for tools the current owner can access. An administrator API token can invoke an unpublished MCP through the existing admin policy while OAuth excludes it until publication. Ordinary writers cannot use that bypass, so their diagnostics do not disclose those definitions.

Preview and save carry `catalog_revision` and use separate versioned tickets. They reuse current owner/session, publication, grant/client/resource revisions, exact target digest, one-use confirmation, revision CAS, expiry/quota narrowing and atomic redacted audit. Tokens and refresh families retain their existing scopes. Registry deltas after synchronization are conflicts, including deltas queued before the SQL read; no stale index page can be offered under the newer generation. Policy epochs, current roles/permissions and expired owner grants invalidate stale candidates. Restart changes the candidate incarnation. Changed/expired cursors are explicit conflicts; the UI requires refresh rather than silently restarting.

## Shared ownership and file boundaries

| Owner | Responsibility |
|---|---|
| `ToolCatalog` | Existing incremental SQLite `gate_tool_catalog`/FTS, registry delta queue and policy epochs; exposes a read-only revision marker. No second index or registry is created. |
| `ports/oauth_candidate_catalog.py` / `OAuthCandidateCatalog` | Schema-free, current-owner SQL projection, exact counts, keyset pages and bounded draft/global/group resolution over that shared index. |
| `OAuthServer` | Grant/client/resource/session ceilings, synchronized-generation checks, cursor/CSRF binding and existing preview/save transaction. |
| Private OAuth routes | Strict typed requests, safe errors, body/query budgets, rate admission and explicit paged capability. |
| Paged picker / grant editor | Display pages separately from full selected IDs; explicit resolver operations, preserved drafts, bounded reason pages and authoritative difference counts. |

Console startup no longer preloads the legacy full-definition `/v1/tools` response on OAuth routes. The dashboard, tools, invocation and service pages load it when they consume it, including navigation from OAuth. This prevents an unrelated full-schema read during candidate editing; it does not migrate those separate legacy pages to pagination.

## Current execution scope

The HTTP suite uses exactly 5,000 services / 50,000 tools, walks all 50 MCP-group pages, finds a small subset beyond the saved grant and first page, and forbids full registry/classification projection during those requests. Separate 5,000-tool/100-MCP and 101-MCP cases exercise both unchanged selection limits. Regression scenarios cover new published/unpublished services, admin API-token comparison, hidden targets, old narrowed families, owner/publication/client/grant/resource changes, sync races, CSRF/session ownership, quota narrowing and one-use saves.

The opt-in loopback browser fixture uses a synthetic administrator and actual catalog/session/selection/preview/save HTTP with 5,000 services / 50,000 tools. Four desktop sizes in both languages check labels on one line, table space, footer visibility and page overflow. Network failure is injected only at the final save to test draft recovery; the catalog and resolver are not mocked. A separate navigation check mocks only the unrelated legacy tool page with one definition. Author browser evidence is recorded below; independent UI review and real-client acceptance remain separate.

## Author browser evidence before source freeze

The pre-freeze large-catalog run passed all 11 cases: eight real layouts, two real group/refresh/limit/save-recovery flows and one navigation check. The author opened all eight screenshots. PNGs and measured JSON are checked in under `docs/images/console/oauth-catalog/`; [English 1600×900](images/console/oauth-catalog/paged-en-US-1600x900.png) and [Chinese 1600×900](images/console/oauth-catalog/paged-zh-CN-1600x900.png) show the compact editor. Every label shares one line with its control; body/document overflow is zero and the footer remains visible. There are no legacy scope-options or `/v1/tools` requests during the eight real OAuth layout cases.

| Viewport | Complete visible rows, English / Chinese | Body / document overflow |
|---|---:|---:|
| 1600×900 | 8 / 8 | 0 / 0 |
| 1920×1080 | 13 / 13 | 0 / 0 |
| 2560×1080 | 13 / 13 | 0 / 0 |
| 2560×1440 | 15 / 15 | 0 / 0 |

Reproduce from `web/` after building: `GATE_E2E_OAUTH_CATALOG_SCALE=1 npm exec -- playwright test e2e/oauth-grants.spec.ts e2e/oauth-paged-catalog.spec.ts`. Include `e2e/oauth-consent.spec.ts` for the unchanged consent flow. The backend candidate tests are `uv run pytest -q tests/test_oauth_paged_catalog.py tests/test_oauth_scope_catalog.py`; the complete backend command is `uv run pytest -q`. Fixed-commit final execution results are delivered separately from these pre-freeze author screenshots. Independent UI acceptance remains with the design owner.

No real Plane classification, ChatGPT authorization/cache behavior, production grants, real credentials, SSH access, release tags or assets are changed or verified here.
