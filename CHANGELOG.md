# Changelog

## Unreleased

## 0.5.3

- Make downstream MCP message budgets configurable with `LINGSHU_GATE_MCP_MAX_MESSAGE_BYTES`, defaulting to 33,554,432 bytes (32 MiB). Apply the same budget to stdio messages, HTTP JSON responses and SSE responses/events.
- Reject invalid budgets outside 1–268,435,456 bytes, including zero; preserve response deadlines, discovery paging, event-count bounds and fail-closed oversized-message handling.
- Cover large image-shaped responses above the previous 8 MiB limit, subsequent responses, custom small budgets and invalid configuration with transport regressions. Expose the setting in native and Compose examples and paired configuration guides.
- Retain the 0.5.2 business-credential features and upgrade requirements. This patch adds no database migration or runtime dependency over 0.5.2. Existing tags remain immutable.

## 0.5.2

- Add personal and shared business accounts to the existing credentials pages, with encrypted usernames/passwords, masked responses, environment/business-role labels and explicit user/role grants.
- Add reviewed MCP adapter bindings, with `agent_browser` as the first adapter. Synchronize selected vault copies, track each binding's version and outcome, and invoke native login using a credential reference and an explicit logical session. Existing MCP permissions remain required.
- Apply managed-browser restrictions to the entire bound instance, separate sessions by caller and Gate connection, and recheck the current credential, binding, authorization and tool contract before dispatch. Block raw vault access, state export and unreviewed execution paths; protect secrets in transport diagnostics, returned content and result-cache handling.
- Keep credential disablement, remote vault deletion and browser-session closure separate. Preserve unresolved cleanup records and report unknown outcomes without claiming website-wide logout or replaying uncertain writes automatically.
- Add bilingual account, grant, binding, synchronization and browser-session controls; retain HTTPS/loopback secret entry, clear secret drafts, and fix dropdown interaction inside dialogs.
- Fix long MCP names and status badges in the tool-review filter, preserve usable search width and let the toolbar wrap at narrower desktop widths.
- Project current governance lists from the live tool registry and retire classifications only after MCP deletion is durably saved. Reject stale edits, confirmations and publication for removed tools; retain audit history and review state across temporary stops/restarts.
- Add migration `0024_business_credentials`. Back up the database, configuration and credential keys together, including the business-credential key; the remote browser vault remains a separate trusted store.
- Update paired guides, release overviews and release notes with dedicated-instance restrictions and the distinction between synthetic regression coverage and unverified installed browser contracts or real business logins.

## 0.5.1

- Refine all 23 signed-in Console routes with shared spacing and control sizes, compact headers, centered dialogs and bounded table scrolling for four desktop sizes in English and Simplified Chinese.
- Move static field explanations behind label-adjacent help buttons, with click, keyboard, Escape and focus recovery; keep validation errors, live status and confirmation facts visible.
- Preserve advanced MCP JSON fields and incomplete numeric/key-value drafts across Form/JSON editing. Reject duplicate object keys, unsafe integers and non-finite numbers before lossy conversion while retaining the source text.
- Add managed-container stdio form fields for digest-pinned images, arguments, environment, lifecycle and health settings. Keep process/container environments distinct, credential references explicit and unsupported container HTTP transport blocked.
- Reorganize built-in OAuth into connection settings, independent management access and client operations. Show only the next relevant setup recommendation, distinguish configured and active management states, and recover configuration/client/key reads independently.
- Improve authorization catalog paging, current-tool selection and preset limits while preserving scope, revision, confirmation and one-time-secret boundaries.
- Preserve actionable drafts and failed selections across classification publication, project delivery, network settings and observability recovery; restore focus after delayed reads and dialogs.
- Synchronize the single runtime version, paired release overviews and release notes, and use tag-pinned documentation links in GitHub Release text. No additional database migration is introduced over 0.5.0.

## 0.5.0

- Add persistent pinned tools and optional plain-text result budgets to business authorizations, with current authorization, contract, group-session and cache-isolation checks.
- Add four argument-policy rule types, a paired Console editor and pure example evaluation; enforce current rules on effective arguments immediately before dispatch, including file-reference conversion and retries.
- Preserve raw confirmation receipts while first-party argument preparers produce bounded effective arguments; retain separate classification confirmation and publication.
- Add independent private connector relay/agent commands with fixed targets, separate credentials, bounded sessions and no automatic replay of business requests.
- Add a strict local OpenAPI 3.0/3.1 adapter with selected operations, fixed HTTP/authentication contracts and immutable tool identities.
- Add default-off Prometheus metrics and OpenTelemetry OTLP/HTTP tracing with current dual-permission scraping, bounded export, fixed destinations and argument/result/credential privacy.
- Include a local demonstration service, paired first-call/integration/observability guides, neutral examples and complete public documentation in native and Compose bundles.
- Add a released-image Docker quickstart with independent local trial volumes, public demo readiness checks, package-specific bilingual READMEs and a complete dynamic first-call guide. Put download/install choices and current Console captures near the top of both project READMEs.
- Add migrations `0022_tool_preferences` and `0023_tool_argument_policy`. Back up database, configuration and credential keys together; old binaries do not enforce new policies.
- Synchronize dependency locks, native OpenTelemetry packaging, third-party notices and the bilingual [release notes](packaging/release-notes.md). Keep existing immutable tags and all formal release gates.

## 0.4.10

- Fix blank stdio endpoints incorrectly entering Streamable HTTP URL validation across precheck, create, edit, reload and transport switching.
- Preserve HTTP URL, private-origin trust, redaction and lossless Form/JSON boundaries; no placeholder HTTP endpoint is required.
- Correct release identity findings in documentation and test helpers, with historical exceptions pinned to exact existing commits, paths, blobs, digests and findings.
- Preserve all original C2PA bytes in four concept images. Distinguish source attribution only for exact reviewed image/chunk digests; changed images, other metadata and other rules remain checked.
- Align stale external-management and legacy-protocol tests with persisted discovery modes and dispatch guards, including negative no-write/no-invocation cases.
- Use a new patch identity without rewriting occupied tags or adding a database migration; retain full formal asset, checksum, SBOM and provenance requirements.
- See the paired [0.4.10 validation record](docs/release-validation-0.4.10.md) for executed checks and remaining boundaries.

## 0.4.9

- Preserve tool classifications, reviewer timestamps, and OAuth authorization snapshots across MCP service restarts, temporary connection outages, and upgrades for unchanged tool definitions.
- Tools belonging to stopped, failed, or disconnected MCP servers leave the callable catalog immediately; preserving reviews does not leave offline tools invocable.
- Reconcile tool snapshots against complete `tools/list` on recovery: unchanged definitions preserve existing authorization snapshots, newly introduced tools require classification review and publication, and tools omitted from the new list remain invalidated.
- Retain strict invalidation boundaries for definition changes, explicit unregistrations, service recreation, and grant revocation.
- See the paired [0.4.9 validation record](docs/release-validation-0.4.9.md) for executed checks and candidate boundaries.

## 0.4.8

- Unify personal credentials under "My Authorizations" in the Web Console: personal API tokens, Gate OAuth grants, and external identity authorizations share a unified management table, toolbar search and filtering, status indicators, and lifecycle operations without separate standalone pages or redundant intros.
- Continuous MCP authorization: personal API tokens and Gate OAuth grants support whole-service continuous authorization in read-only or read-write mode, automatically granting newly discovered and published tools under that MCP. Bind continuous policies to service lifecycle identity so deleted and recreated services or replaced trust targets require explicit re-authorization.
- Authorization-level on-demand discovery: persist tool discovery mode (`on_demand` vs `direct`) per authorization for personal API tokens, Gate OAuth grants, and external OAuth records, defaulting both new and existing business authorizations to on-demand. Client URL query parameters and request headers are ignored in favor of the persistent setting.
- Editable invocation limits: business authorizations enforce per-minute rate limits (1–10,000, default 6,000) and concurrency limits (1–100, default 100), verified in dispatch with CAS revisions, explicit preview differences, and atomic rollback audit.
- Distinguish multi-instance execution (`execution`) from multi-data-source query (`data_source`) through an explicit group purpose. Preserve existing groups as `unspecified`; legacy updates that omit the purpose retain the saved value, and legacy MCP creation receipts keep their request digest across upgrades.
- Require a purpose choice in Console and show it in group directories/details. Authorized on-demand group summaries, instance pages, describe and session-open results identify the purpose and selected source using existing instance names.
- Database migrations: add `authorization_discovery`, `mcp_authorization_identity`, and `token_authorizations` migrations while preserving single-writer SQLite and isolated Core execution boundaries.
- See the paired [0.4.8 validation record](docs/release-validation-0.4.8.md) for executed checks and candidate boundaries.

## 0.4.7

- Reuse request-held immutable tool contracts when a configuration writer invalidates a group-directory snapshot. Bind reuse to publication revision and frozen identity; reject known-stale inputs before policy projection and comparison.
- Recheck current token scopes, grants, classifications and group/configuration/Registry versions. Retain bounded inputs, shared cache limits, the three-attempt limit and the real 5,000-instance/50,000-tool concurrent regression with its original 20-second reader budget.
- Carry the integrated root Console, groups/instance sessions, on-demand directory, OAuth editor, account-menu and fresh packaging changes forward under a new patch identity. Keep the occupied v0.4.5/v0.4.6 tags immutable.
- Local evidence demonstrates avoidable retry work; it does not establish the unique cause of the earlier hosted timeout or a production latency/RSS guarantee. Formal publication retains the complete quality, native, Compose/Core, checksum, SBOM and provenance gates.
- See the paired [0.4.7 validation record](docs/release-validation-0.4.7.md) for exact-source checks, fresh candidates and publication boundaries.

## 0.4.6

- Prevent a cached, closed account menu from reclaiming keyboard focus during a queued animation frame; keep controlled closing and focus recovery for the current menu.
- Deliver the integrated root Console, explicit groups/instance sessions, bounded on-demand directory, OAuth editor improvements and fresh wheel staging under a new patch version. Existing authorization and optional host/client boundaries stay unchanged.
- Bind candidate checks to exact source and package hashes. Actual local HTTP/stdio acceptance and owned-process cleanup are separate from browser, remote-host and OAuth acceptance.
- Keep the occupied v0.4.5 tag immutable. Formal publication of v0.4.6 requires all existing quality, five-platform native, Compose, dual-architecture Core/offline, checksum, SBOM and provenance gates.
- See the paired [0.4.6 validation record](docs/release-validation-0.4.6.md) for executed checks and remaining boundaries.

## 0.4.5

- Move the browser Console to the root with content-negotiated JSON discovery, stable /v1/meta, compatible old links, confined assets and verified native entry smoke.
- Integrate explicit MCP groups/connection-bound instance sessions, the bounded on-demand directory and killable schema validation; actual tool/instance authority and credential checks remain in dispatch.
- Integrate private OAuth catalog pagination, whole-selection resolution, compact bilingual editors, lossless drafts and explicit recovery after unknown write outcomes; scope/family and selection ceilings stay unchanged.
- Restore controlled account-menu closing, keyboard focus and localized built-in role names without duplicate or blank entries; explain available classification contract changes and distinguish legacy records without field digests.
- Stage repeated wheel builds privately and verify exact static inventories/RECORD, including sdist-to-wheel; preserve safe path boundaries and frozen worker entries.
- Keep Vite 8/Rolldown with identifier mangling disabled and Console base /; include reviewed Windows startup, TLS, protocol/OAuth and frozen-export fixes.
- Optional Native/Linux rootless Podman remains disabled until separately approved host provisioning/readiness. Real Podman, ChatGPT OAuth and multi-machine acceptance remain incomplete.
- [Candidate validation](docs/release-validation-0.4.5.md) separates current source/package/CI checks from historical browser failures and formal publication.

## 0.4.4

- The four management tools reject Console cookies at generic invocation entries; dedicated Console REST retains Origin/session/body-bound CSRF. Connection/probe checks reject credential rotation after lock waits and before decryption. Memory diagnostics omit command arguments and environments, and Core installs Debian's exact Perl security revision without scan exceptions.
- Administrator external HTTP configuration adds shared REST/MCP offline plan, digest-bound confirmed apply, actor-owned status and cancellation. Saved configuration is retained on connection failure; initial and refreshed discovery quarantine changed classifications without granting access.
- Live administrator sessions, token scopes, role permissions and credential revisions are rechecked. Plans retain CAS and idempotent completion; attempts enforce cooperative deadlines, cancellation and connection ownership. The Delivery Skill documents separate ZIP, Git and external HTTP paths.
- Separate built-in `/mcp/manage` is disabled by default, uses an explicit client resource allowlist and management consent, and exposes only the four external configuration tools. Business/external tokens and cross-resource code/refresh use are denied.
- Exact create/update targets bind dispatch, queued work, plans and idempotent completions. Private owner target changes require live administrator authority, Origin/session CSRF, reviewed one-use confirmation, revision CAS and atomic audit; JWT/family scopes and business grants do not expand.
- Console and public consent explain resource/scopes and exact targets, with protected centered editors, complete target pagination and brief saved feedback. [Management contract](docs/oauth-external-management-design.md) and [external configuration contract](docs/external-mcp-configuration.md) describe the behavior. Real-client/peer integration remains unverified. Multi-instance routing, large-catalog search and the Git executor are outside this release.

## 0.4.3

- Explicit owner confirmation in Gate adds, reconfirms or removes MCPs/tools on the existing OAuth grant. The same bearer and refresh family follow the live tool list within unchanged OAuth scope ceilings; no repeated client OAuth flow is needed for same-scope tools.
- Session/Origin/CSRF, bound confirmation, current policy, revision CAS and atomic audit protect updates. Missing OAuth scopes are not manufactured; narrower families keep their own limits, and other grants remain unchanged.
- Configuration Form/JSON editing preserves unknown fields and exact drafts, with explicit Gate-start/restart policies and accurate reload feedback. New MCPs default enabled with auto-start off; applying does not silently start them.
- Console configuration file reads and mutations normalize paths and enforce the configured directory boundary, including symlink escape checks.
- Built-in tool origins resolve consistently in catalog, grants and classification review.
- Scope dialogs retain controls/actions while tools scroll; MCP selectors show IDs and search names, with owner-wide search and pagination.
- Automatic HTTP negotiation recognizes the precise initial legacy-initialization rejection and shows the actual negotiated version without replaying business calls.

[Candidate validation](docs/development-validation.md). Formal publication, platform artifacts and independent visual acceptance are recorded separately.

## 0.4.2

0.4.2 adds exact service/IP/port authorization for private HTTP MCP connections, with live administrator checks, CAS, explicit inline confirmation, default denial, revocation checks and unchanged HTTPS/redirect boundaries.

[Validation / 验证记录](docs/release-validation-0.4.2.md) · [Release notes / 发行摘要](packaging/release-notes.md)
