# Stage 1 development review

[简体中文](zh-CN/stage1-development-review.md) · [External configuration](external-mcp-configuration.md)

This is a candidate review record after published 0.4.3, not a release or production acceptance. The source version and immutable release notes remain unchanged. No push, merge, tag, release, external MCP/SSH invocation, package download, credential provisioning or executor deployment forms part of this validation.

## Candidate and evidence

- Base: published main `5fc3aaba94955e243598783166479136797733e4`; independent branch `recovery/stage1-after-v043`.
- Header commit: `4c61cb4fa9301805386122e27a2e88098c0770fc`; one account name, translated role tags, one version/API/logout entry, accessible controlled menu and focus restoration.
- Header browser evidence: five tests passed, including 16 desktop combinations of 1600×900, 1920×1080, 2560×1080 and 2560×1440, English/Chinese, light/dark. Screenshot existence and browser checks do not replace independent pixel review.
- External configuration: one application service, thin REST/MCP adapters, migrations `0010_gate_external_mcp_config` and `0011_gate_console_csrf`, existing configuration persistence and idempotency/runtime/classification services. No UI save semantics or Git execution guards are bypassed.
- Final reviewed code passed the complete backend run: 1338 passed, 3 skipped in 310.06 seconds. All three skips are `tests/test_mcp_playwright_interop.py` because its fixed peer installation was not supplied; no dependency was installed to remove them. Frontend checks/build and 422 tests in 69 files passed. Browser tests passed 6 in 20.9 seconds: five Header cases with 16 desktop screenshots plus a real Chromium same-origin CSRF POST/body-change/replay case. Lint, mypy (115 source files), identity, Compose and diff checks passed. Test output is not release-asset verification.

The reviewed fixes require strict shared Console Origin/session binding and five-minute single-use CSRF tickets for session REST writes; API bearer verification remains independent. CSRF issuance uses POST so the browser supplies Origin itself. Cleanup checks operation ownership before the no-client path, interrupted runtime application retains unknown/reconciliation, connect/refresh share one strict snapshot and first classification counts, and cancel rechecks terminal state under the queue lock and SQLite writer transaction. Corresponding synthetic regressions cover missing/cross-origin/replayed/foreign/expired tickets, no-client successors, unknown cancellation and completion/cancel races.

[Administrator OAuth design](oauth-external-management-design.md) retains explicit `operations.manage`, current admin/role and JWT/client/grant/family ceilings, the exact four built-ins and preauthorized exact create/update targets. It is not implemented authority. Client metadata/challenge mechanisms were checked against official documentation; the real ChatGPT management-scope request remains unobserved and needs a separately authorized nonproduction test.

## Review order

1. Live admin/session/token/role permissions and scope/delegation ceilings; management plans must not be consumed through another connection.
2. Normalized manifest/credential/target/action digests, plan expiry and single use, create/update CAS and exact idempotent retry.
3. Cooperative lock/HTTP budget, cancellation, initial/refresh classification gate, cleanup ownership and conservative lost-worker recovery.
4. Shared adapters, additive migration, atomic terminal/journal write, redacted returned manifests and bounded structured failures.
5. Synthetic tests, paired docs and the single bundled Skill's ZIP/Git/external routing.

## Remaining boundaries

File persistence, runtime state and SQLite are not one transaction. A successful save is retained after connect/refresh failure. Finalization failure/restart requires reconciliation, never write replay. An audit event emitted after completion can fail independently of the terminal transaction. Cooperative deadlines do not hard-interrupt OS DNS; existing SQLite contention may use its 30-second busy limit. The configuration/runtime manager locks serialize this control path; no multi-Core or parallel multi-instance guarantee is claimed.

Expired consumed plans stay while their journal-linked operation exists. After the existing journal retention removes the operation, a subsequent plan creation prunes the expired orphan using an indexed lookup; it never makes a consumed plan reusable.

`instance_id` is currently the same target as `server_id`; file-digest CAS cannot identify identical delete/recreate generations. The new service reuses private idempotency helpers from `ProjectDeliveryMcpService`; factoring a common coordinator is a future architectural choice, not a parallel write workflow. Real peer, deployment, cancellation under real socket/DNS contention and independent root visual review remain unverified.

## Retained next-phase work and acceptance matrix

| Phase / work | Required behavior | Acceptance evidence still required |
|---|---|---|
| Git executor decision | Choose native isolated Linux adapter, Core + remote worker, or dedicated VM worker; retain current Core guards and five-method port | Reviewed lifecycle, source/artifact digests, egress/tool integrity, full sandbox cancellation/restart; no host shell substitute |
| Grouping / multiple instances | Explicit logical group, stable instance/generation, no credential inheritance or implicit extra grants | Independent instance state/config revision, failover and authorized group selection; delete/recreate and late response races |
| Stateful instance routing | Sticky target for the entire MCP session; an update must not silently switch it | Concurrent users/sessions, stale mapping, restart/cancel and refused unsafe retry of writes |
| Fixed `current_connection` entry | Current effective connection's authorized overview and complete pagination only | User/grant/token-scope isolation, current revocation, cursor invalidation and no hidden/global counts |
| Fixed `authorized_tool_search` entry | Small authorized MCP/tool/client summaries; full-result search/pagination | Large lists, no current-page-only filtering, inaccessible name/schema/count nondisclosure |
| Fixed `tool_describe` entry | On-demand schema bound to current authorized tool and instance/schema revision | Revocation and schema drift between search/describe/invoke; no descriptor as an authority input |
| Read/write/destructive invocation entries | Separate classification/permission checks; generic invoke never advertises read-only | Current ACL/scope/classification/instance recheck on every call, writes never replayed as reads, destructive confirmation |
| Direct tool compatibility | Keep commonly used direct tools alongside fixed entries; one initial client catalog refresh | Real supported-client evidence; new MCP/tool additions later need no repeated client refresh, permission changes still take effect live |
| Freshness hints | Authorization/config revision is advisory display data, never a capability | Tampered or old metadata cannot authorize; backend remains the authority |

The fixed-entry phase is recorded here as authorized follow-on scope; these entries and a new search system have not been implemented in this slice.
