# OAuth Console density — development candidate

[简体中文](zh-CN/oauth-console-density.md) · [Built-in OAuth](builtin-oauth.md) · [Catalog scaling](oauth-catalog-scaling.md)

`test/gate-oauth-density-20261006` starts from integration source `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. It changes the two built-in OAuth Console views and their presentation tests. Backend authorization, public consent, external identity configuration and dependency locks retain the integration source's contracts. No release, deployment or real-client acceptance is performed by this candidate.

## Adjust authorization scope

The centered editor uses a compact title, client name, state and selected count. Authorization rules disclose the saved/client/family scope ceilings on demand. Expiry, rate and concurrency stay above the table with labels on the same row as their controls. Whole-directory read-only/all/custom selection, clear and refresh remain explicit; search, MCP and access filters affect display only. Refresh preserves unsaved IDs and limits, and later services never join automatically. Published `read` classification remains the only basis for read-only selection.

Tool rows use a fixed compact MCP column, one-line name, checkbox and persistent read/write tag. The existing cursor orders tool references, so a page can cross MCP boundaries. The fixed column identifies every row without inventing group boundaries, repeating unchecked group totals or changing catalog order. The separate MCP-group view still selects all eligible tools in a service and displays its authoritative selected/available and read/write counts.

Hover or focus discloses a tool ID; activating the name opens read-only details with a copyable full ID, MCP identity and published access. Same-name tools retain unique accessible IDs. A small set of distinct short MCP names uses radios; long, duplicate or larger sets use searchable exact-ID choices. The paged selector reads at most 15 owner-visible groups per request and provides explicit load-more and retry actions. It never obtains the whole tool-definition catalog.

The footer pairs added/removed/added-write counts with Cancel and Save authorization. Save still runs the existing server preview and explicit difference confirmation before any write. Current-owner checks, scope ceilings, one-use confirmation, CSRF, revision CAS and expiry/quota narrowing are unchanged. Unknown save outcomes continue to block a new preview/write until explicit saved-state readback reconciles the retained draft; failed readback keeps that protection.

## Configured OAuth management

A compact status row reports saved OAuth state, actual signing-key read state and loaded client counts. Four setup steps remain visible until successful reads establish saved enabled OAuth, saved addresses, an active key and an enabled client. Hiding the steps does not claim external connection verification.

The desktop layout gives 40% to URL configuration and signing controls and 60% to the client table. Labels stay beside fields. Clients have search, 25-row pagination and internal scrolling; full IDs are copyable, while exact callbacks, scopes and resources appear in read-only details. Connection guide contains TLS/callback/setup explanations and endpoints from the last saved configuration. Closing these disclosures restores keyboard focus and does not mutate state.

Manual resource ownership, disable-before-URL-edit rules, signing-key confirmation/readback, missing-key enable lock, client rotation/disable confirmation and one-time secret acknowledgement retain their original handlers. Real errors stay inline and recoverable. The separate management-resource controls remain default-off with exact-target authorization; the external identity page is outside this layout change.

## Reproduce presentation and behavior evidence

Build first, then run from `web/`:

```bash
GATE_E2E_OAUTH_CATALOG_SCALE=1 \
GATE_IDENTITY_EVIDENCE_DIR=/tmp/gate-identity-evidence \
GATE_OAUTH_SCREENSHOT_DIR=/tmp/gate-oauth-evidence \
GATE_UI_SOURCE_SHA=<tested-code-commit> \
npm exec -- playwright test \
  e2e/oauth-density.spec.ts e2e/oauth-grants.spec.ts e2e/oauth-consent.spec.ts \
  e2e/oauth-paged-catalog.spec.ts e2e/oauth-setup.spec.ts \
  e2e/oauth-management.spec.ts e2e/oauth-management-resource.spec.ts \
  e2e/external-identity-layout.spec.ts
```

The density fixture mocks OAuth responses with 137 tools, six MCPs and 61 clients. Real paged cases use loopback HTTP with 5,000 MCPs and 50,000 tools, including committed-save response loss, failed readback and later separately confirmed updates. External identity evidence is opt-in and must be enabled for that regression. Synthetic screenshots, author inspection, independent design review and real Gate/ChatGPT acceptance are separate evidence categories.
