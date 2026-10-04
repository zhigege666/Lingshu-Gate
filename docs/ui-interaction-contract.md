# UI interaction contract

[简体中文](zh-CN/ui-interaction-contract.md) · [Documentation index](README.md)

This is the acceptance contract for new or migrated Console UI and its affected consumers. It covers all Console pages, including Tools, Roles and permissions, and Invoke. It does not claim that the current site already implements these requirements, require unrelated page rewrites, or add an authorization/approval flow.

The goal is efficient task completion: find an object, perform the intended operation, understand its result, and recover from failure. Preserve existing public APIs, permissions, confirmation boundaries, and request semantics unless a change explicitly addresses them.

## Existing foundations

- Keep React/Vite and Ant Design as the primary UI foundation; do not introduce another component library for this contract. Reuse the existing Ajv and domain validation adapters. Dedicated editor or component-preview tooling requires a demonstrated gap; it is not a prerequisite for interaction fixes.
- Extend the existing theme entry points: [`console-design-provider.tsx`](../web/src/components/console-design-provider.tsx), [`index.css`](../web/src/index.css), and the layout rules in [`console-workspace.css`](../web/src/console-workspace.css). Do not create a competing token entry point. Convergence of existing AntD tokens and CSS variables must preserve affected consumers and is a separate migration.
- Use values from those files rather than trial dimensions from design research. For example, the current AntD provider defines `fontSize: 14`, `borderRadius: 8`, `controlHeight: 36`, and `controlHeightSM: 30`; these describe the provider, not a claim that every existing local control matches it. Token changes must be explicit and checked at their consumers.
- Shared components own presentation and interaction mechanics. Domain adapters own requests, authorization, business state, and secret handling. Reuse behavior where it matches; do not turn visually similar pages into a universal CRUD component.

Use `--input` / AntD `colorBorder` for editable control boundaries, including Invoke's nullable/JSON-only value containers. Use the quieter `--border` / `colorBorderSecondary` / `colorSplit` for structural dividers, tables, cards, and read-only results. Keep these mappings aligned in both themes; focus and error indicators retain their own semantic colors. Verify actual rendered controls on their adjacent backgrounds after changing these tokens. The running backend version stays visible on the login/register brand footer and the fixed Console header on desktop and mobile. Both reuse one independent, five-second-bounded read of the existing public `/healthz` metadata per authentication-gate mount, without credentials, cache, polling or automatic retries. Loading and failure labels are localized; unavailable metadata never substitutes a Console build version or blocks authentication. No management API or new public endpoint is needed. When a long prerelease is truncated, the full value remains available in the account menu without requiring hover and wraps within the viewport.

## Rules

The rules below are project decisions. The references explain the practices that informed them; their complete rules and framework choices are not adopted wholesale.

| ID | Acceptance requirement |
|---|---|
| UI-01 — Page identity | Keep one clear, accessible page identity. A compact or inline heading is valid; preserve the existing desktop/mobile identity arrangement. Do not stack decorative category labels, synonymous large headings, and repeated introductions. Necessary object names and task instructions remain visible. |
| UI-02 — Useful space | Let content determine height. Do not reserve empty columns, empty equal-height panels, placeholder statistics, or large waiting areas to complete a layout. Keep necessary grouping space and usable editor/log work areas. Distinguish genuine empty, loading, error, forbidden, and unselected states. |
| UI-03 — Tokens | Reuse existing semantic colors, spacing, typography, radius, and layer values. New arbitrary values need a concrete layout reason and local review. Values such as `0`, `auto`, percentages, and content-driven sizes are not automatically violations. Do not imply that token lint already exists. |
| UI-04 — Density | Controls in one task area use a consistent density; long text and errors may increase height. Compact layouts must retain readable text, operable targets, and reachable actions at narrow widths and zoom. Do not impose an unverified fixed row height on all content. |
| UI-05 — Forms | Use typed controls for known fields, repeatable rows for supported arrays, and key/value editing for suitable maps. Provide associated labels; placeholders do not replace them. Separate purpose, format/unit help, and validation. Prefer one column unless related short fields benefit from sharing a row. |
| UI-06 — Validation | Represent issues with code, message, severity, source, document path, and draft revision; include a text range when available. Show JSON syntax diagnostics as the raw draft changes; show ordinary required/format errors after the relevant field is touched or submission is attempted. Do not greet an untouched form with a wall of warnings. Keep actionable errors visible near fields and provide a summary for multiple or hidden errors. Summary actions reveal and focus the relevant field or JSON location. Do not rely on a tooltip or transient toast alone. |
| UI-07 — Form/JSON | Both modes automatically synchronize one semantic draft without a separate user-operated sync/apply step or loss of unrepresented data. Preserve invalid raw text; never submit the previous valid value in its place. Preserve unknown fields, array order, and distinctions among absent, `null`, `0`, `false`, and empty string. Changes distinguish set, remove, and unchanged. Apply the editor boundaries below. |
| UI-08 — Feedback | Put field errors at fields, region loading/failure in the affected region, short success feedback in a message, and ongoing task results with the task. Persistent failures need a visible recovery route. Avoid duplicate feedback for one result. Prevent duplicate submissions and define which submitted snapshot owns the response. |
| UI-09 — Overlays | Separate editing, read-only details, and destructive confirmation. Provide an accessible name, suitable initial focus, keyboard navigation, and a sensible focus return. Define close behavior for dirty and pending states. Keep long-form actions reachable without obscuring the last field. Do not add an interrupting dialog when inline content serves the task. |
| UI-10 — Lists and tables | Make search scope, applied filters, loaded range, pagination, and selection scope accurate. Use a real link/button for the row's primary action. Keep frequent actions discoverable; batch results retain unresolved selection and explain partial failure. A limited snapshot must not imply a server-wide total. |
| UI-11 — Empty states | Explain the actual state and offer an available next action, such as creating, clearing filters, or retrying. Do not present a failed request as an empty collection. When context is already clear, use a compact hint instead of another title or illustration. |
| UI-12 — Logs and tasks | Keep snapshot, connection, execution, and follow-scroll states distinct. New records must not steal the reading position. Preserve each source's real timestamps, limits, and transport capabilities; do not label snapshots as live streams. Display components must not silently start polling or invent cancellation. |
| UI-13 — Accessibility | Prefer native control semantics, accessible names, visible focus, and information beyond color. Check the keyboard path through the changed task, including menus and overlays. Automated accessibility results do not replace assessment of focus order, reading order, zoom, and task completion. |
| UI-14 — Language | Use consistent domain terms and concrete action labels; dangerous confirmations identify the action, target, and consequence. Maintain Chinese/English keys, units, and time meaning. Keep diagnostic identifiers useful without exposing secrets; do not translate raw logs as if they were interface copy. |
| UI-15 — Reuse | A new composite component states its actual consumers, supported states, and responsibilities it leaves to the caller. Migrate explicitly and check affected consumers. Preserve the latest Tools, Roles, and Invoke behavior while adopting shared patterns; do not rebuild their new capabilities in parallel. |

## Overview and domain boundaries

The Dashboard opens with a compact resource overview instead of a separate row of navigation shortcuts already available in the sidebar. Preserve its accessible page heading and inline scope explanations; a generic help dialog is not required when it adds no task guidance. Gate health describes only Gate's health endpoint, service states keep their actual meanings, and tool counts cover the current user's visible catalog. Each resource distinguishes loading, failure, and a successful empty result independently. Resource links follow the same permissions as their destination; visual summaries do not grant access or imply that every visible tool can be invoked.

## Editor and domain boundaries

Form/JSON conversion must operate on the active document and revision. Form changes update the JSON representation automatically, and successfully parsed JSON updates the semantic draft automatically; switching views does not require an extra **Apply JSON** or **Sync form** action. Do not reformat raw text or move the caret on every keystroke. JSON syntax failure keeps the raw draft, provides an immediate syntax diagnostic, and blocks submission; stale parsed data is not a fallback. A view switch must not discard invalid text or replace it with the last valid value.

Validation and when an issue is shown are separate decisions. Ordinary required/format errors appear after a field has been touched or on a submit attempt; an initial empty form does not list every missing field. Revalidate an already exposed issue as the field is corrected. A submission always validates the entire current draft, including untouched and hidden fields, before any write or execution. Required-field errors need their complete path, including the missing property. Summaries reveal and focus hidden fields or the corresponding JSON location. Raw syntax errors remain immediate because they prevent reliable interpretation of the active document.

Schema changes, late responses, and refreshes must not overwrite a dirty draft. Undo for parameter changes must not restore an old execution result. These local synchronization rules do not merge the domain's separate save/apply or confirm/publish decisions.

Text entered into a key/value row before **Add** is also a draft, including a key without a value. Include it in dirty detection and exit protection. Saving, running, switching modes, replacing parameters, or removing its parent must not silently ignore or discard that input: retain it safely, or ask the user to add or explicitly clear it and locate the row. The row-level Add action does not introduce a separate form/JSON synchronization step.

Every entry point that replaces an editing context uses the same exit decision: dialog close, application navigation, command navigation, and browser Back/Forward. Dirty forms offer continued editing or explicit discard; pending form submissions keep the editor mounted. Invoke retains its distinct warning that a request may continue after leaving. Browser document exit uses `beforeunload` where supported, without promising protection against a browser crash. The shared exit registry stores only dirty/pending flags, never field values or secrets.

A form may expose only the structures it can represent safely. Unsupported schema dialects, references, or constructs must not be treated as successfully validated. Use the existing fail-closed validation path; show an actionable reason or retain JSON editing where supported. A JSON view does not bypass validation. Parsing, duplicate-key detection, number-precision protection, structural validation, and domain checks are different capabilities; do not claim `JSON.parse` or Ajv supplies all of them automatically.

Tool arguments use the tool's schema. Manifest editing uses the actual project model and existing checks; a generic `dict` request schema is not a complete Manifest form specification. Read-only audit, log, and result JSON does not gain editing privileges. Shared editor structure must not silently add preflight requests or change the separate save/apply behavior.

| Domain | Required boundary |
|---|---|
| Redacted endpoint in an existing configuration | Represent keep/replace explicitly. Keeping a redacted endpoint uses the existing preservation protocol bound to the original configuration ID; do not validate the mask as a literal URL, expose the secret endpoint, or remove backend redaction. A replacement must pass normal endpoint validation. Creating a configuration must not accept a mask as a valid endpoint. This domain-specific keep state does not relax UI-07 or fail-closed schema validation. |
| Manifest one-time credentials | Keep `user_credential_values` outside the round-trippable Manifest and ordinary undo/copy/history. Preserve the existing removal from editor state before submission and re-entry on failure. |
| Global credentials | Preserve the existing controlled-input lifecycle on failure and the domain's keep/replace semantics. Do not submit a masked value as a replacement or clear all secrets through a generic error handler. |
| Downstream credentials | Do not retrieve or prefill the previous secret. Preserve existing clear-on-success/close behavior and the current attempt's failure behavior. |
| Personal tokens | Full token value remains a one-time creation result, separate from the creation draft; do not imply it can later be queried again. |
| Temporary passwords and tool parameters | Preserve their existing submit/session lifecycles. Do not infer clearing or persistence from Manifest rules. Never put secrets in URLs or automatically persist them in browser storage. |
| Execution and navigation | Leaving Invoke must not be presented as cancellation. Define warnings for a running request or actual unsaved changes according to the session's real lifetime; do not silently retry or promote sensitive drafts/results into persistent history. |
| Decisions and permissions | Preserve independent upload, build, deploy, overwrite, start, cancel, abandon, save/apply, classification confirm/publish, and token scope-expansion decisions where they exist. Discovery/display never grants access. |

For local versus remote filtering, name the behavior. A remote query keeps draft filters distinct from applied filters and makes pending changes visible; **Reset conditions** clears the draft and immediately requests defaults; **Apply filters** submits other draft edits. Local filtering may update immediately over loaded records. This is a migration target, not a claim that every current page already follows it. Refresh must identify its scope and must not silently request every page's data.

## Migrated shared patterns and consumers

The following are implemented consumers in this tree, not a claim that every state has passed browser or independent review. Domain-specific confirmation, permissions, request ownership, and secret lifecycles remain with callers.

| Pattern | Actual consumers | Supported behavior and caller responsibilities |
|---|---|---|
| [`FormDialog`](../web/src/components/form-dialog.tsx) | 12 editor instances across 9 pages: Roles (role/type), Users (create/edit), Tool classification (batch/review), Configurations, Uploads, Global credentials, Downstream credentials, Resource grants, and Personal tokens | Fixed header/actions around scrollable fields; persistent form errors; pending close lock; accessible title and description; dirty/pending registration. Callers supply fields, validation, pending state, real dirty comparison, close/discard handling, and submit behavior. Read-only details and destructive confirmations keep separate components. |
| [`EditorNavigationContext`](../web/src/components/editor-navigation-guard.tsx) and [`useDraftCloseGuard`](../web/src/components/use-draft-close-guard.ts) | The registry covers all 12 `FormDialog` instances; the close helper serves the editors that adopt it | Each open editor registers and cleans up its own exit flags. The local close helper prevents overlapping discard prompts where adopted; Roles, Configurations, and Uploads retain their own domain close handling. App owns navigation decisions; callers own clearing and secret handling. Invoke uses its own session exit state. The one-time token result is not classified as an unsaved form draft. |
| [`ValidationErrors`](../web/src/components/validation-errors.tsx) | `McpConfigEditor` in Configurations/Uploads and the Invoke parameter editor | Persistent issue summaries with code/source/path/revision and a locate action. Adapters produce diagnostics, choose when to expose them, reject stale revisions, and reveal/focus the appropriate input or JSON location. Other typed forms retain field-level validation and persistent server errors. |
| [`McpConfigEditor`](../web/src/components/mcp-config-editor.tsx) | Configurations and Uploads → save as configuration | Shared Manifest form/JSON views, supported argument rows and key/value maps, pending-entry protection, masked endpoint keep/replace, and cooperation with caller-owned one-time credential submission boundaries. Callers provide the original configuration identity, save request, and secret lifecycle. Configurations retain preflight; Uploads opts out of backend preflight and credential-list loading and retains its separate create request. Unsupported structures remain in JSON. |
| [`useListPage`, `ListViewport`, `ListPagination`](../web/src/components/list-pagination.tsx) | Advanced configurations, credentials, downstream credentials, users, roles/types, grants, personal tokens, runtime cache, invocation audit, tool classification; Logs/events reuse only the viewport | Paginate authorized loaded collections with 50 rows per page, bounded row scrolling, page/filter scroll reset, exact loaded ranges, and sticky action columns where present. Classification selects the current page and retains cross-page selections. Callers own authorization, remote limits, filtering, object identity, confirmation and mutations. Logs/events retain their existing 15-row sorting/paging contract. This is not evidence of server-wide totals or browser acceptance. |
| [`PageRefreshContext` / `usePageRefresh`](../web/src/components/page-refresh.tsx) | 13 page loaders: Builds, Credentials, Users, Roles, Grants, Tool classification, Personal tokens, Downstream credentials, Invocation audit, Logs/events, Runtime cache, Uploads, and Diagnostics. App supplies scoped reads for Dashboard, Configurations, Services, Tools, and Invoke. | The shell invokes the mounted page's read handler and respects its busy state. Callers define required dependencies and error recovery; refresh does not remount editors, poll, apply unsent filter drafts, or fetch all pages. Explicit local actions such as log refresh may remain. |
| [`QueryStatus`](../web/src/components/query-status.tsx) | Logs/events and Invocation audit | Displays unapplied changes, the applied query summary, and the successful snapshot time. Pages own draft/applied filters, limits, requests, and errors; Reset conditions clears the draft and immediately requests the defaults. Local search remains limited to loaded records. |
| [`getToolAccessDisplay`](../web/src/features/tool-access.ts) | Tools catalog via `tool-catalog`, and Invoke | Both derive displayed access from `metadata.gate_access.required_access`; pending is shown only for an explicit pending classification. Unknown stays distinct. This adapter neither infers access from a declaration nor authorizes execution. |

## Evidence and review

Select states and checks according to the changed behavior and its risks; do not require a Cartesian product of every state, language, theme, and viewport. Relevant examples include loading, stale data during refresh, no matches, failure, forbidden, dirty, submitting, completion, long content, and a narrow viewport. Theme/copy/layout changes need corresponding light/dark, Chinese/English, or zoom evidence.

| Layer | What it establishes | Current status and limits |
|---|---|---|
| 1. Source and architecture checks | TypeScript and existing source/language-key contracts; additional import or architecture rules need explicit implementation | `npm --prefix web run check` runs type checking and `check:ux`. Language keys are checked through the TypeScript AST: the two required locale objects must be present, nonempty, and free of duplicate or missing keys. Other UX rules still check source strings, including `PageHeader` and help entries. Keep those gates until a focused change replaces them; they do not prove rendered behavior. |
| 2. Component behavior | Observable transitions, lossless conversion, request ownership, and error recovery | Use relevant existing Vitest tests and focused additions for changed behavior. A test file's existence does not establish that it ran. |
| 3. Browser evidence | Real layout, scrolling, focus, overflow, and keyboard use | Capture applicable pages/states. Label mocked data and distinguish it from real API/permission verification. Token lint, Playwright, axe, and Storybook are not established repository gates by this document. |
| 4. Independent UI review | Task clarity, useful density, consistent interaction, and domain preservation | A reviewer independent of the implementation/design author examines the proposal and evidence, records findings, and checks fixes. This review does not create a new user permission prompt. |

Record the command/scenario, observed result, scope, and anything not executed. Data loss, secret exposure, or dangerous misexecution blocks acceptance. Main-task keyboard failures, hidden persistent errors, or misleading operation scope require correction. Cosmetic issues may be tracked with an affected scope and next step. A source check or screenshot match alone is not a whole-site UI pass.

For a documentation-only change, verify links, language parity, and `git diff --check`. For product code, follow the root instructions and run relevant existing checks, including `npm --prefix web run check`, `npm --prefix web test`, and `npm --prefix web run build`; report their actual results separately from browser and independent review evidence.

## Implementation status and follow-up work

1. Implemented the language-key extractor fix in [`i18n-contract.mjs`](../web/scripts/i18n-contract.mjs), called by `check:ux`. It reads the top-level `messages` object with the existing TypeScript AST, accepts formatting/locale order and `as const`/`satisfies` changes, and rejects missing/empty language objects, duplicate properties, mismatched keys, malformed syntax, and dynamic members it cannot inspect. It never evaluates application source. Regression cases, including the real catalog, run with `npm --prefix web test -- scripts/i18n-contract.test.mjs`; this checks the static catalog contract, not translated meaning or browser behavior.
2. In a separate focused change, evolve source-string gates into reliable syntax/data checks and browser behavior evidence. Preserve existing useful classification/fingerprint/batch constraints. Do not weaken `PageHeader` or help-entry gates without replacement coverage of page identity and necessary guidance.
3. The consumers above have migrated to shared editor, feedback, query, refresh, and exit patterns. Complete and record applicable browser checks and independent product/UI and test review, fix findings, and recheck affected consumers. Component adoption or passing source tests alone does not establish whole-site interaction acceptance.
4. Map current AntD tokens and CSS variables at the existing entry points, then remove measured inconsistencies with consumer checks. Introduce lint, component stories, or browser tooling only when the pilot identifies a concrete recurring need; document exactly what is installed and enforced.

## Centered dialogs and direct choices — 2026-10-04

Design owner: dot. This supplement follows the user's selection of design 2 and
long-term Gate UI requirements on 2026-10-04. Engineering implements it; dot owns
independent visual and interaction acceptance. Existing non-conflicting rules
and authorization/draft safeguards remain in force.

### Scope and dialog frame

- New, edit and detail context overlays in Gate use a centered Dialog. Ordinary
  route pages remain pages. This applies to Gate, not automatically to Admin.NET
  or browser extensions. Existing drawers require explicit per-page migration.
- Configuration editors have a default maximum width of 1200 px, bounded by the
  viewport minus 96 px, and maximum height of the viewport minus 64 px. Desktop
  acceptance sizes are 1600×900, 1920×1080, 2560×1080 and 2560×1440.
- Keep the title and close action at the top, actions at the bottom, and one
  principal body scroll area. JSON mode scrolls inside its editor instead of
  creating two competing vertical scroll areas.
- The configuration editing frame keeps this bounded viewport height in both
  modes so JSON retains a usable workspace when switching from the form.
- Use two columns for short fields; endpoints, errors and key/value lists span
  the available width. Large displays do not stretch inputs indefinitely. Allow
  sufficient label width in English and Chinese.
- Form / JSON tabs share one draft. Organize content with spacing and thin
  dividers instead of stacked cards. Common fields remain visible; infrequent
  advanced fields may be progressively disclosed.
- Close, Cancel, Escape, outside click and navigation follow the same dirty
  protection. Pending saves prevent duplicate submission and loss on close.
  Focus enters the dialog, remains trapped, and returns to its trigger.

### Choice controls

- Use native or fully accessible radio / segmented radio for 2–5 fixed, mutually
  exclusive short options. One click selects an option; do not use Select.
- Filters that need an all-items choice explicitly include **All**, selected by
  default. It is one radio value, not a select-all action. Editing fields follow
  actual model defaults and do not acquire an All value automatically.
- Collections with six or more options, dynamic loading, search needs or long
  labels may use a searchable selector. Radios may wrap; lack of space alone
  does not justify switching back to Select.
- Use a switch or checkbox for one Boolean, and checkboxes for multiple choices.
  Radios support arrow keys, visible focus, full label hit areas and an explained
  disabled state. Selection is not conveyed by color alone.

### Data semantics

- Enabled state, runtime mode, endpoint and timeout are directly visible. The
  current form modes are managed Stdio, external HTTP and managed HTTP. Advanced
  is a read-only unsupported-combination state, not a selectable fourth mode.
- Access declarations belong in the advanced section as a read-only summary
  with JSON editing. `permissions` is a declaration object, not a read/write/admin
  enum or an access grant. Actual access remains in authorization management.
- Every form row keeps its label and control on the same line: a fixed-width
  label on the left and the input, radio group, switch or textarea on the right.
  Help and errors sit below the control. Labels stay on one line in English and
  Chinese. Paired short fields retain this layout inside each cell; narrow
  layouts collapse to individual rows instead of moving labels above inputs.
- Enabling does not mean immediate execution. Saving, applying and connecting
  explain their real effects; saving success does not imply a connected service.
- Startup policy is separate from enabled state. Both modes use **Start
  automatically when Gate starts**. The managed-mode helper says **Start the MCP
  process automatically and connect**; the external-mode helper says **Connect
  automatically without starting a remote process**. Missing `startup_policy`
  retains `legacy_restore`; only an explicit startup switch edit selects
  `gate_start_v1`. At the next Gate process start the new policy follows enabled
  and auto_start once; manual actions then control the current process without
  changing its next startup policy. Explain legacy behavior until migration.
  Do not imply remote-process or OS
  boot control. Unsupported restart/health options are explicitly reported rather
  than silently changing the meaning of a saved draft.
- Preserve untouched schema-supported fields. Unknown fields do not bypass the
  backend schema. Explain removal or incompatibility before a mode switch.
- Invalid JSON retains its raw text and diagnostic location; it does not revert
  to an old form. Results belong to a draft revision and expire when it changes.

### Precheck and actions

- Present one overall state: **Check failed · N errors**, **Check completed · N
  warnings**, or **Check passed**. Errors start expanded, with concise field
  reasons and remedies. Empty normal/info groups are absent; hard failures are
  not described as a recommendation. Technical paths and original reasons may
  have expandable detail while important reasons remain visible.
- Selecting an issue locates its field or JSON. A failed check disables Save and
  explains why. **Validate configuration** is secondary; **Cancel** and **Save
  configuration** are standard actions. Static validation must not claim to test
  network connectivity.
- Reuse existing icon components with localized text. Decorative icons are
  `aria-hidden`; copied SVG markup alone is not evidence of a rendering fault.

### Migration and acceptance

The service configuration editor is the current migration target. Remaining
drawers are service tool/call details (`servers-page.tsx`), upload history
(`uploads-page.tsx`), personal tool/call details (`personal-workspace-page.tsx`),
proxy-profile editing (`network-settings-panel.tsx`) and network settings
(`git-import-form.tsx`). This inventory does not claim site-wide completion.

Check all four desktop sizes, both languages, long errors/URLs, large header
lists, Form/JSON round trips, error/warning/pass states, discard recovery,
keyboard operation and focus. A design image sets direction; it does not replace
real browser acceptance or permission/security tests.

## Open-source references

These primary sources informed the contract; project-specific rules above remain explicit project decisions. Borrowing their review practices does not require adopting their component libraries or their full test matrices.

- [Primer contribution rules](https://github.com/primer/react/blob/main/contributor-docs/CONTRIBUTING.md) and [testing strategy](https://github.com/primer/react/blob/main/contributor-docs/testing.md): real reuse, theme values, APIs, state/behavior coverage, and review evidence.
- [Carbon component checklist](https://carbondesignsystem.com/contributing/component-checklist/), [token Stylelint plugin](https://github.com/carbon-design-system/stylelint-plugin-carbon-tokens), and [data-table guidance](https://carbondesignsystem.com/components/data-table/usage/): token governance, behavior specifications, progressive checks, and density variants.
- [GitLab Pajamas forms](https://design.gitlab.com/patterns/forms/), [modal guidance](https://design.gitlab.com/components/modal/), and [empty states](https://design.gitlab.com/patterns/empty-states/): associated help/errors, focus and closing behavior, and contextual next actions. Pajamas is an open-source project hosted on GitLab.
- [Ant Design feedback](https://ant.design/docs/spec/research-message-and-feedback/), [theme customization](https://ant.design/docs/react/customize-theme/), and [visual regression practice](https://ant.design/docs/blog/visual-regression/): contextual feedback, existing token mechanisms, and visual-change evidence.

## Delivery, personal discovery and result review scenarios

- Delivery history: the selected tab owns the list title and collection total. Keep search, status filter and page position in one wrapping toolbar; retain row-level actions and reset pagination on filters.
- Personal MCP: derive services from the current principal's visible tools. Test administrator multi-service pagination, read-only access, one-service read/write grants and guessed unauthorized IDs; preview fixtures are not authorization evidence.
- Invocation result: decode JSON inside MCP text blocks for display only; preserve the raw response for copy. Search only the current displayed result, with match navigation and no new invocation. Test text, nested JSON, arrays, empty/failed responses, escaped markup, no matches and matches beyond a bounded display window. Never render untrusted HTML or fetch returned media URLs.
- Classification review: default order is Needs confirmation, Pending publish, Published, Stale. Review-and-publish requires explicit confirmation of targets and access, validates fingerprints and is atomic within each batch of at most 500. Unknown classifications remain blocked. Later batch failures retain completed work and report unfinished targets.
- Tool origin: classification REST responses project `registry_source` from the current Registry's exact service/tool pair. The stored `source` remains the classification suggestion's provenance. Lists, review details and service filters use the same four builtin group names and system badge only with trusted builtin evidence; IDs, `gate_*` prefixes and suggestion sources cannot establish origin. Missing or mixed origin evidence remains unconfirmed, including historical rows. This display never confirms, publishes or grants tool access.
- Stale classification: unchanged tool definitions must survive refresh without losing publication. Definition changes invalidate prior access; catalog removal and reappearance require review. Show available reasons rather than implying a tool crashed. Historical records without reason evidence cannot establish why they became stale.
- Logs/events filters: show the controls directly in a wrapping row on wide screens, preserving applied versus draft query state and readable labels on narrow screens.

### Filter reset regression

- Compound filters have a stable, compact reset action that does not move the list when enabled. Clear search changes only search; Reset filters restores every condition and page one.
- Logs, events and audit reset immediately request default conditions. On failure, preserve the error and applied snapshot rather than relabeling old results. Same-query refresh preserves the current page; changed filters and reset start on page one and never resurrect an old page.

## Visual craft review

The project's quality target references Awwwards, Webby and FWA craft, without claiming an award or an objective maximum. Preserve Gate's operational clarity and one-click access. Review eight dimensions against real rendered task states:

1. Typography: consistent native/AntD CJK sans fallback; legible secondary copy and tabular numbers
2. Spacing: intentional grouping, no decorative empty columns; dense data must remain readable
3. Hierarchy: visible primary actions, context and results; configuration explanations use the full available row
4. Color: consistent semantic states in both themes; source token contrast checks supplement rendered checks
5. Motion: short feedback, no automatic decorative loops; reduced-motion preference wins
6. Micro-interaction: visible hover/focus/loading/disabled/error states without shifting rows
7. Responsive layout: check actual CSS viewport sizes and long Chinese/English copy; iframe layout checks do not establish physical-device, touch or performance coverage
8. Originality: coherent Gate identity and task-specific composition; never copy award marks or claim certification

Record concrete remaining findings rather than declaring that nothing can be improved. Stop a review round only after its observed usability defects are fixed or explicitly blocked. Keep desktop/mobile evidence and unexecuted automation distinct.

References: [Webby criteria](https://www.webbyawards.com/judging-criteria/), [Awwwards mobile guidelines](https://www.awwwards.com/mobile-excellence-guidelines.pdf), [FWA's stated focus](https://thefwa.com/FWA25/25.html).

Formal desktop acceptance sizes: 1600×900, 1920×1080, 2560×1080 and 2560×1440. Narrow-screen fallback remains available, but phone/tablet-specific expansion is outside the current scope.
