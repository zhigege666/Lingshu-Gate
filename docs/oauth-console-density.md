# OAuth Console density — development candidate

[简体中文](zh-CN/oauth-console-density.md) · [Built-in OAuth](builtin-oauth.md) · [Catalog scaling](oauth-catalog-scaling.md)

`test/gate-oauth-density-20261006` starts from integration source `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. It changes the two built-in OAuth Console views and their presentation tests. Backend authorization, public consent, external identity configuration and dependency locks retain the integration source's contracts. No release, deployment or real-client acceptance is performed by this candidate.

## Adjust authorization scope

The centered editor uses a compact title, client name and state. Selected/available counts appear only in the list statistics. Authorization rules disclose the saved/client/family scope ceilings on demand. Expiry, rate and concurrency stay above the table with labels on the same row as their controls. Whole-directory read-only/all/custom selection, clear and refresh remain explicit; search, MCP and access filters affect display only. Refresh preserves unsaved IDs and limits, and later services never join automatically. Published `read` classification remains the only basis for read-only selection.

Tool rows use a fixed compact MCP column, one-line name, checkbox and persistent read/write tag. The existing cursor orders tool references, so a page can cross MCP boundaries. The fixed column identifies every row without inventing group boundaries, repeating unchecked group totals or changing catalog order. The separate MCP-group view still selects all eligible tools in a service and displays its authoritative selected/available and read/write counts.

Hover or focus discloses a tool ID; activating the name opens read-only details with a copyable full ID, MCP identity and published access. Same-name tools retain unique accessible IDs. A small set of distinct short MCP names uses radios; long, duplicate or larger sets use searchable exact-ID choices. The paged selector reads at most 15 owner-visible groups per request. Its native load-more/retry buttons sit outside the MCP listbox: Tab enters the actions, Enter/Space activates them, Shift+Tab returns to the filter, and Escape closes only the menu and restores filter focus. Tab after the last action moves to the next filter. A failed page retries the same cursor while retaining loaded groups and the scope draft. It never obtains the whole tool-definition catalog.

The footer pairs added/removed/added-write counts with Cancel and Save authorization. Save still runs the existing server preview and explicit difference confirmation before any write. Current-owner checks, scope ceilings, one-use confirmation, CSRF, revision CAS and expiry/quota narrowing are unchanged. Unknown save outcomes continue to block a new preview/write until explicit saved-state readback reconciles the retained draft; failed readback keeps that protection.

## Configured OAuth management

A compact status row reports saved OAuth state, actual signing-key read state and loaded client counts. Four setup steps remain visible until successful reads establish saved enabled OAuth, saved addresses, an active key and an enabled client. Hiding the steps does not claim external connection verification.

The desktop layout gives 40% to URL configuration and signing controls and 60% to the client table. Labels stay beside fields. Clients have search, 25-row pagination, 40 px one-line rows and internal scrolling in whole-row heights. Activating the client name by mouse or keyboard opens read-only details with exact callbacks, scopes and resources; its Edit client action opens the existing editor. The duplicate per-row Details button is removed, while full-ID copy and rotation/enable/disable actions remain. Closing details or editing restores focus to the name.

Active signing-key counts appear in the top status row; the lower signing area retains the action and real loading/error/missing-key states. Enabled configuration explains that URLs require disablement and saving first; a pending disable still keeps URLs locked and requires the original confirmation. Separate management connection has one purpose/authorization sentence. Its fixed path, four tools and exact-target consent details remain in Connection guide and the actual enablement confirmation. The guide also contains TLS/callback/setup explanations and endpoints from the last saved configuration.

Manual resource ownership, disable-before-URL-edit rules, signing-key confirmation/readback, missing-key enable lock, client rotation/disable confirmation and one-time secret acknowledgement retain their original handlers. Real errors stay inline and recoverable. The separate management-resource controls remain default-off with exact-target authorization; the external identity page is outside this layout change.

## Executed validation and author evidence

The fixed code checkpoint is `fdcb3545aa88d1ccb3a961fca3e2c47055bfb105`. It follows the earlier `2a84ea4` code / `4fc96c8` evidence delivery. The integration owner's review of that delivery requested six visual refinements and identified the keyboard paging failure. This checkpoint implements those findings; final independent review remains pending. The later evidence commit updates documentation and synthetic PNG/JSON files only. Every current screenshot is recaptured at the new code SHA; the two `7d145c2` baseline captures remain separately identified. The density fixture also records the built Console index SHA256. [The artifact manifest](images/console/oauth-density/manifest.json) hashes each evidence file.

| Executed check | Result |
|---|---|
| Frontend source and behavior | Check passed; 441 tests in 74 files passed in 18.23 seconds; both builds passed. The existing large OAuth chunk warning remains. |
| Complete selected browser regression at the fixed SHA | 206 passed, no skipped cases, in 10.8 minutes: 26 density/keyboard, 70 personal-grant, 15 public-consent, 17 real paged-catalog, 26 setup, six client-management, 40 management-resource and six external-identity cases. |
| Targeted authorization backend | Inherited from the earlier `2a84ea4` checkpoint: 183 passed in 223.05 seconds across built-in OAuth, scope catalog, live scope and paged catalog. Backend source/tests and dependency locks were rechecked as byte-identical to the integration base; no backend suite was rerun in this follow-up. |
| Source/configuration discipline | Current repository identity, unchanged 0.4.4 version, guide links and whitespace checks passed. Earlier frozen Python/npm dependency checks passed; current locks are unchanged. No authorization API or trust-boundary change. |

The normal tool table has 40 px rows. At 1600×900 the [scope baseline](images/console/oauth-density/baseline-scope-en-US-1600x900.png) captured from exact `7d145c2` has seven complete 45 px rows and a partially visible eighth. The new view has nine complete rows. The [configured-page baseline](images/console/oauth-density/baseline-infrastructure-en-US-1600x900.png) still displays the large setup block and places the signing action below the fold. Those two captures intentionally fail the new density expectations; they are comparison evidence, not a baseline test pass.

| Viewport | Complete tool rows, English / Chinese | Complete client rows, English / Chinese | Client scroll height | Scope body vertical / document horizontal overflow |
|---|---:|---:|---:|---:|
| 1600×900 | 9 / 9 | 5 / 5 | 200 px | 0 / 0 |
| 1920×1080 | 13 / 13 | 9 / 9 | 360 px | 0 / 0 |
| 2560×1080 | 13 / 13 | 9 / 9 | 360 px | 0 / 0 |
| 2560×1440 | 22 / 22 | 11 / 11 | 440 px | 0 / 0 |

Every measured scope label shares one line with its control. The configured page's labels also share their controls' rows, has zero horizontal overflow, and keeps guide/register/signing/client-action/management-switch controls visible at all four sizes. Its 61-client fixture checks actual 40 px rows, whole-row scroll heights, an unobscured complete fifth row, 25-row pagination, access to the bottom row and page/search scroll reset. Real large-catalog layouts measure MCP-group rows separately: 9, 14, 14 and 15 complete rows in both languages, with zero body/horizontal overflow and no legacy scope-options or full-definition tool read.

| Viewport | Scope screenshots | Configured-management screenshots |
|---|---|---|
| 1600×900 | [English](images/console/oauth-density/scope-en-US-1600x900.png) · [中文](images/console/oauth-density/scope-zh-CN-1600x900.png) | [English](images/console/oauth-density/infrastructure-en-US-1600x900.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-1600x900.png) |
| 1920×1080 | [English](images/console/oauth-density/scope-en-US-1920x1080.png) · [中文](images/console/oauth-density/scope-zh-CN-1920x1080.png) | [English](images/console/oauth-density/infrastructure-en-US-1920x1080.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-1920x1080.png) |
| 2560×1080 | [English](images/console/oauth-density/scope-en-US-2560x1080.png) · [中文](images/console/oauth-density/scope-zh-CN-2560x1080.png) | [English](images/console/oauth-density/infrastructure-en-US-2560x1080.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-2560x1080.png) |
| 2560×1440 | [English](images/console/oauth-density/scope-en-US-2560x1440.png) · [中文](images/console/oauth-density/scope-zh-CN-2560x1440.png) | [English](images/console/oauth-density/infrastructure-en-US-2560x1440.png) · [中文](images/console/oauth-density/infrastructure-zh-CN-2560x1440.png) |

The author opened all 16 current screenshots above, both unchanged baseline captures, both current dark long-content scope captures and both current dark management captures. The author also opened the real paged 1600×900 examples, the native keyboard paging focus captures ([English](images/console/oauth-density/selector-keyboard-en-US-1600x900.png), [中文](images/console/oauth-density/selector-keyboard-zh-CN-1600x900.png)), and all four lost-response/readback screenshots: [English unknown](images/console/oauth-density/save-unknown-en-US-1600x900.png), [English reconciled](images/console/oauth-density/save-reconciled-en-US-1600x900.png), [中文未知](images/console/oauth-density/save-unknown-zh-CN-1600x900.png), [中文回读](images/console/oauth-density/save-reconciled-zh-CN-1600x900.png). All eight real paged layouts have automated geometry evidence; the remaining six are not claimed as manual visual review. Independent design review and real Gate/Plane/ChatGPT acceptance remain with the integration owner. No production credentials, grants, services, SSH session, release tag or release assets are changed here.

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
