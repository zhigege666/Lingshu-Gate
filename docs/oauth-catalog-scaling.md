# OAuth catalog scaling — development candidate

[简体中文](zh-CN/oauth-catalog-scaling.md) · [Built-in OAuth](builtin-oauth.md)

This work uses `test/oauth-catalog-scaling-20261005`, based on main `d4786fd368e932bc758ea29da1a597c9d9551794`. It does not alter the completed scope-selection UI branch, increase selection limits or establish release/client acceptance.

## Stage A: saved-grant authentication

Previously, token verification projected every tool available to the owner and enforced the 5,000-tool catalog ceiling before intersecting the saved grant. The regression reproduces HTTP 401 for an otherwise valid one-tool grant after its owner gains more than 5,000 candidates.

Verification now uses the database grant's explicit IDs. One atomic registry lookup returns only those definitions; current owner permission, published classification, resource, client/grant/family/JWT scope ceilings and saved snapshots remain authoritative. Missing, unpublished, changed or withdrawn targets do not appear in the principal. Signed JWT `tools`/`tool_ids` claims cannot add targets. Stored grants beyond 5,000 tools or 100 MCPs fail before registry lookup. The existing refresh and expiry rules remain; a refreshed bearer undergoes the same bounded verification.

The single-tool invocation path also synchronizes only that definition instead of discarding a return value containing the entire classification table. Other classification-list APIs keep their existing response contract. `OAuthServer._grant_tools` is the shared bounded projection seam; main at this baseline has no `refresh_verified_principal` method, so any later verified-principal refresh path must reuse it rather than rebuild the owner catalog.

## Executed synthetic evidence

The targeted scaling and atomic-registry suite passed 16 tests. It uses exactly 5,000 synthetic services and 50,000 published tools, issues grants while their selected targets are within the existing limits, then grows the remaining catalog. It verifies the original and refreshed bearer, successful selected invocation, unselected denial, publication/access withdrawal, client/family ceilings, forged signed tool claims and stored selection limits. Full-registry and full-classification-list projections are forbidden during measured authentication and invocation. The existing OAuth, live scope, management-resource, delegated-access, external-OAuth and access-control regression set passed another 246 tests. Ruff, mypy (116 source files), the web build, source-version and repository-identity checks passed.

| Saved grant tools | Definition targets per verification | Full registry projections | Median verification (ms) | Refresh + verification (ms) | Incremental verification peak (bytes) |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 7.400 | 137.953 | 19,466 |
| 100 | 100 | 0 | 9.110 | 135.054 | 406,203 |
| 5,000 | 5,000 | 0 | 205.035 | 344.464 | 21,617,711 |

These are author-executed synthetic measurements, not production latency guarantees. Verification latency is the median of three executions without allocation tracing. The peak is a separate `tracemalloc` execution and excludes fixture construction and the already resident 50,000-tool registry. Refresh timing includes signing and verification. Reproduce from the source checkout with `uv run pytest -q -s tests/test_oauth_catalog_scaling.py tests/test_registry_concurrency.py`.

## Stage B: proposed minimum contract, not implemented

- Add private `GET /v1/auth/oauth/grants/{grant_id}/scope-catalog` with a bounded page size (1–100), an opaque cursor, search, MCP and access filters, and a tools/MCP-groups view. Return the page, exact matching and whole-catalog read/write/MCP counts, a stable owner-bound `catalog_revision`, next cursor, CSRF and explicit selection limits of 5,000 tools / 100 MCPs. A page is explicitly incomplete and must never be passed to the current picker as a complete catalog.
- Add a read-only, CSRF-bound selection resolver for all-current, all-current-read-only and specific MCP groups at that revision. Global choices ignore list filters and pagination. Resolve the whole current candidate set; exceeding either selection ceiling returns a structured limit error without a partial selection. Refresh never reapplies the previous bulk mode or includes later services automatically.
- Validate selected draft IDs separately from the current page. Off-page IDs are not unavailable merely because they are absent from that page. Return no names or server details for targets the current owner cannot see. Failed requests retain the draft and limits.
- Keep the legacy full-catalog scope-options response unchanged for catalogs within its bound. Large catalogs require an explicit paged capability/error, not a partial `tools` array that an old UI could mistake for all eligible tools. Integrate the existing preview, one-use confirmation, CAS, publication and scope/limit rechecks with the same catalog revision before saving.

Proposed wire fields retain the current `OAuthTool` shape and the existing scope-options metadata (`csrf`, `expires_at`, `grant_revision`, `scopes`, `effective_scopes`, `family_scope_limits`); owner-visible unavailable reasons, when supported, retain their existing codes. New list fields are `view`, `items`, `next_cursor`, `catalog_revision`, `complete: false`, `matching_counts`, `catalog_counts` and `selection_limits`. Tool items use `OAuthTool`; group items contain `server_id`, `server_name`, `tool_count`, `read_count`, `write_count` without embedding all definitions. Counts distinguish tools/read/write/MCPs. Selection limits are `{ "tools": 5000, "mcps": 100 }`.

The proposed resolver is `POST /v1/auth/oauth/grants/{grant_id}/scope-selection`. Its request carries `csrf`, `expected_revision`, `catalog_revision` and one explicit operation: `mode: "all" | "read"` replaces the draft; `mode: "groups"` takes `server_ids`, `checked` and `tool_ids` for the current draft; `mode: "ids"` validates a draft without replacing it. A successful response returns the resolved explicit `tool_ids`, selected current `tools`, `unavailable_ids` with generic reasons, selected counts and per-MCP selected counts. Every returned selection is bounded; a limit failure leaves the prior client draft intact. No operation grants access or saves changes.

The picker must receive a paged-data adapter rather than compute global/group choices or availability from a page's `items`. Refresh keeps draft IDs and validates them through the resolver; only an explicit bulk click replaces them. Add `catalog_revision` to the current preview request while retaining its existing fields and confirmation result. Preview and save revalidate that revision plus all current authority and quota checks; new tickets have a distinct purpose/version. Cursor bindings include owner/session, grant/client/resource revisions, catalog revision, filters and view; changed bindings fail with a structured conflict and never silently restart. Revision/index storage is intentionally left to the shared candidate-catalog implementation review.

The completed bulk-selection UI needs to consume this contract before large-catalog editing can be accepted. Candidate indexing/revision ownership and the endpoint details are for root's design review before Stage B implementation. Stage A does not fix the legacy interactive catalog's hard bound or the gateway's separate full namespace construction; those are separate integration work. No real Plane classification, real ChatGPT authorization/cache behavior, production grants, credentials or SSH access were used or verified here.
