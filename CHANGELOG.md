# Changelog

## 0.4.3

- Explicit owner confirmation in Gate adds, reconfirms or removes MCPs/tools on the existing OAuth grant. The same bearer and refresh family follow the live tool list within unchanged OAuth scope ceilings; no repeated client OAuth flow is needed for same-scope tools.
- Session/Origin/CSRF, bound confirmation, current policy, revision CAS and atomic audit protect updates. Missing OAuth scopes are not manufactured; narrower families keep their own limits, and other grants remain unchanged.
- Configuration Form/JSON editing preserves unknown fields and exact drafts, with explicit Gate-start/restart policies and accurate reload feedback. New MCPs default enabled with auto-start off; applying does not silently start them.
- Built-in tool origins resolve consistently in catalog, grants and classification review.
- Scope dialogs retain controls/actions while tools scroll; MCP selectors show IDs and search names, with owner-wide search and pagination.
- Automatic HTTP negotiation recognizes the precise initial legacy-initialization rejection and shows the actual negotiated version without replaying business calls.

[Candidate validation](docs/development-validation.md). Formal publication, platform artifacts and independent visual acceptance are recorded separately.

## 0.4.2

0.4.2 adds exact service/IP/port authorization for private HTTP MCP connections, with live administrator checks, CAS, explicit inline confirmation, default denial, revocation checks and unchanged HTTPS/redirect boundaries.

[Validation / 验证记录](docs/release-validation-0.4.2.md) · [Release notes / 发行摘要](packaging/release-notes.md)
