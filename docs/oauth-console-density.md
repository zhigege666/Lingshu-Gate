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

## Executed validation and author evidence

The fixed code checkpoint is `2a84ea44dd8284674cdcd1b57d5ea95efd7b390e`. The later evidence commit adds documentation and synthetic PNG/JSON files only. Screenshot metadata records this code SHA; the density fixture also records the built Console index SHA256. [The artifact manifest](images/console/oauth-density/manifest.json) identifies the baseline separately and hashes each evidence file.

| Executed check | Result |
|---|---|
| Frontend source and behavior | Check passed; 441 tests in 74 files passed in 15.86 seconds; both builds passed. The existing large OAuth chunk warning remains. |
| Complete selected browser regression at the fixed SHA | 202 passed, no skipped cases, in 9.7 minutes: 24 density/keyboard, 70 personal-grant, 15 public-consent, 15 real paged-catalog, 26 setup, six client-management, 40 management-resource and six external-identity cases. |
| Targeted authorization backend | 183 passed in 223.05 seconds: built-in OAuth, scope catalog, live scope and paged catalog. Backend source/tests and dependency locks are byte-identical to the integration base; this is not a new complete-backend-suite claim. |
| Source/configuration discipline | Frozen Python/npm dependencies, repository identity, unchanged 0.4.4 version, guide links and whitespace checks passed. No authorization API or trust-boundary change. |

The normal tool table has 40 px rows. At 1600×900 the [scope baseline](images/console/oauth-density/baseline-scope-en-US-1600x900.png) captured from exact `7d145c2` has seven complete 45 px rows and a partially visible eighth. The new view has nine complete rows. The [configured-page baseline](images/console/oauth-density/baseline-infrastructure-en-US-1600x900.png) still displays the large setup block and places the signing action below the fold. Those two captures intentionally fail the new density expectations; they are comparison evidence, not a baseline test pass.

| Viewport | Complete tool rows, English / Chinese | Scope body vertical / document horizontal overflow |
|---|---:|---:|
| 1600×900 | 9 / 9 | 0 / 0 |
| 1920×1080 | 13 / 13 | 0 / 0 |
| 2560×1080 | 13 / 13 | 0 / 0 |
| 2560×1440 | 22 / 22 | 0 / 0 |

Every measured scope label shares one line with its control. The configured page's labels also share their controls' rows, has zero horizontal overflow, and keeps guide/register/signing/client-action/management-switch controls visible at all four sizes. Its 61-client fixture checks 25-row pagination, internal scrolling and page/search scroll reset. Real large-catalog layouts measure MCP-group rows separately: 9, 14, 14 and 15 complete rows in both languages, with zero body/horizontal overflow and no legacy scope-options or full-definition tool read.

| Viewport | Scope screenshots | Configured-management screenshots |
|---|---|---|
| 1600×900 | [English](images/console/oauth-density/scope-en-US-1600x900.png) · [中文](images/console/oauth-density/scope-zh-CN-1600x900.png) | [English](images/console/oauth-density/infrastructure-en-US-1600x900.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-1600x900.png) |
| 1920×1080 | [English](images/console/oauth-density/scope-en-US-1920x1080.png) · [中文](images/console/oauth-density/scope-zh-CN-1920x1080.png) | [English](images/console/oauth-density/infrastructure-en-US-1920x1080.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-1920x1080.png) |
| 2560×1080 | [English](images/console/oauth-density/scope-en-US-2560x1080.png) · [中文](images/console/oauth-density/scope-zh-CN-2560x1080.png) | [English](images/console/oauth-density/infrastructure-en-US-2560x1080.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-2560x1080.png) |
| 2560×1440 | [English](images/console/oauth-density/scope-en-US-2560x1440.png) · [中文](images/console/oauth-density/scope-zh-CN-2560x1440.png) | [English](images/console/oauth-density/infrastructure-en-US-2560x1440.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-2560x1440.png) |

The author opened all 16 screenshots above, both baseline captures, both dark long-content scope captures and both dark management captures. The author also opened the real paged 1600×900 examples and all four lost-response/readback screenshots: [English unknown](images/console/oauth-density/save-unknown-en-US-1600x900.png), [English reconciled](images/console/oauth-density/save-reconciled-en-US-1600x900.png), [中文未知](images/console/oauth-density/save-unknown-zh-CN-1600x900.png), [中文回读](images/console/oauth-density/save-reconciled-zh-CN-1600x900.png). All eight real paged layouts have automated geometry evidence; the remaining six are not claimed as manual visual review. Independent design review and real Gate/Plane/ChatGPT acceptance remain with the integration owner. No production credentials, grants, services, SSH session, release tag or release assets are changed here.

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
