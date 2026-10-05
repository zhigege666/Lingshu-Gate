# Changelog

## Unreleased

- Group-directory reads use the selected-instance Registry index and bounded revision/immutable-identity structural memoization. Cold preparation and comparison run outside the configuration write lock; current authorization is read again in one transaction and continuously changing snapshots return bounded retryable errors. Full HTTP regressions use 5,000 manifest instances/50,000 tools, preserve the 1,000-member limit, and record p95, process RSS and writer lock waits while proving zero additional structural serialization on warm/search/page reads. This is synthetic evidence, not a production latency guarantee. [Directory bounds](docs/mcp-groups.md).

- Registry structural publication isolates caller/getter references, provides immutable per-instance indexed snapshots and explicit updates preserving handlers, and rejects over-budget JSON before copying or runtime discovery digests/review. A 5,000-instance/50,000-tool index regression forbids global iteration or serialization on repeated reads. [Publication boundary](docs/mcp-groups.md).

- A read-only administrator group contract catalog partitions only currently visible tools by exact original name, conservative input/output declarations and current Gate-reviewed safety semantics. Missing output schema differs from an empty schema; changed or unreviewed contracts remain individual variants. Complete search and paged original member/tool IDs retain current permission/token ceilings. Candidates explicitly leave business equivalence unverified and add no callable aliases, routing, failover or OAuth scopes. [Directory contract](docs/mcp-groups.md).

- Administrator MCP groups organize existing instances through stable IDs, many-to-many membership, revision CAS, strict session CSRF and atomic audit. Cached secret-free instance metadata avoids repeated file reads; actor/body-bound creation receipts support lost-response recovery. Writes require tools.invoke without expanding existing tokens. The existing MCP page adds a centered group editor with complete metadata search/pagination and cross-page selection. Archive/delete changes only metadata; no permissions, configurations or runtime state expand. Logical aggregation and Agent routing remain pending. [Group contract](docs/mcp-groups.md).

- Downstream output schemas are retained in tool registration and discovery digests, including an explicit empty schema. Contract drift invalidates published classifications and access snapshots; Console names changed fields, or states that historical field differences are unavailable. Review and publication remain manual.

- Source acquisition/validation adds bounded SHA-1 Git object export, shared streaming ZIP scans and normalized dependency/offline-worker contract fixtures. Production Git transport, full lockfile graphs and rootless offline installation/build remain unavailable; no executor is injected. [Execution gap](docs/git-executor-decision.md).
- Console presents one account name, translated role tags, one backend version, and one entry for API/logout; keyboard dismissal restores focus.
- Administrator external HTTP configuration adds shared REST/MCP offline plan, digest-bound confirmed apply, actor-owned status and cancellation. Saved configuration is retained on connection failure; initial and refreshed discovery quarantine changed classifications without granting access.
- Live administrator sessions, token scopes, role permissions and credential revisions are rechecked. Plans retain CAS and idempotent completion; attempts enforce cooperative deadlines, cancellation and connection ownership. The Delivery Skill documents separate ZIP, Git and external HTTP paths.
- Separate built-in `/mcp/manage` is disabled by default, uses an explicit client resource allowlist and management consent, and exposes only the four external configuration tools. Business/external tokens and cross-resource code/refresh use are denied.
- Exact create/update targets bind dispatch, queued work, plans and idempotent completions. Private owner target changes require live administrator authority, Origin/session CSRF, reviewed one-use confirmation, revision CAS and atomic audit; JWT/family scopes and business grants do not expand.
- Console and public consent explain resource/scopes and exact targets, with protected centered editors, complete target pagination and brief saved feedback. [Management contract](docs/oauth-external-management-design.md) and [external configuration contract](docs/external-mcp-configuration.md) describe the unreleased behavior. Multi-instance routing, fixed authorized catalog entries, real-client/peer integration and Git executor implementation remain pending; this entry makes no publication claim.

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
