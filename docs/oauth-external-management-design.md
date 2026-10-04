# Administrator OAuth for external configuration

[简体中文](zh-CN/oauth-external-management-design.md) · [Current external workflow](external-mcp-configuration.md)

This is the approved direction for an incremental implementation, not enabled OAuth authority in this candidate. The existing ChatGPT business connection cannot yet configure an external MCP. No production authorization, client change or credential provisioning was performed.

## Authority and targets

Reuse the existing permission name `operations.manage` as an explicit OAuth management scope. `tools.invoke` alone never permits configuration. Only tokens verified by Gate's built-in issuer qualify; another trusted JWT issuer does not. Require a currently active administrator and current `operations.manage` role permission. Apply, cancel and a probe retain the additional `tools.invoke` permission/scope ceiling. Every required scope must be in the intersection of JWT claims, current enabled client, live grant and live refresh family.

The grant authorizes exactly `gate_mcp_config_plan`, `gate_mcp_config_apply`, `gate_mcp_config_status` and `gate_mcp_config_cancel`, with definition/schema fingerprints. Other built-ins remain denied. Configuration targets are a separate grant field containing exact `server_id` and allowed `create`/`update` actions. Creation requires a preauthorized unused exact ID; no wildcard, prefix or all-new-IDs permission. Update/status/cancel also check their actual target. Management does not grant downstream business tools, credential creation/read, HTTP trust changes, classification publication, project execution or Git executor access.

## Smallest server changes

1. Add `operations.manage` to built-in issuer/client scope validation and metadata; preserve the two existing business scopes. Add explicit management-tool snapshots and target policy to grants/authorization codes. Do not recast built-ins as published downstream tools or add them to ordinary grants.
2. Extend the verified principal/invocation context with built-in issuer identity, client/resource, grant/family identities, token expiry and effective scope ceiling. Recheck all live rows and permissions before each side effect and after lock waits. Keep raw bearer tokens out of plans, journals and workers.
3. Bind the plan and idempotent request to that management connection and target policy, as well as existing manifest/config/credential/action digests. Exact-tool and target checks precede cached-result returns. Revocation, expiry, disabled clients, role downgrade or target removal stop queued work without granting recovery authority.
4. Add a Console confirmation for one user/client/resource, the four tools, exact target IDs/actions and expiry. Reuse strict Origin, live session binding and one-use confirmation. The OAuth consent consumes the matching reviewed intent and displays its target bounds; targets never come from an untrusted authorize query. Keep business grants, old JWTs and existing family ceilings unchanged. New management rights require a fresh client-initiated authorization-code/PKCE flow and a new management grant/family.

## ChatGPT scope request: verified mechanism and remaining evidence

The official client authentication documentation describes OAuth tool `securitySchemes` and `_meta["mcp/www_authenticate"]` errors together as the tool-level linking trigger; resource metadata alone is insufficient. A management descriptor requests `operations.manage`; writes additionally request `tools.invoke`. The challenge names the fixed `/mcp` resource metadata and required scope. Static OAuth clients are supported. These are documentation-verified mechanisms, **not a verified management connection to this Gate**. Sources: the official Authentication and ChatGPT Developer mode guides, reviewed on 2026-10-04; direct source links accompany the independent review response.

The proposed bootstrap exposes only static management descriptors to an explicitly enrolled active admin/client with a reviewed target intent, so the client can receive a scope challenge. This narrow discovery exception is not invocation authority and reveals no target inventory, credentials or operation state. Ordinary business connections do not automatically acquire management descriptors or a new scope. The transport must preserve `securitySchemes` and the challenge error metadata; today's generic denied-tool result is insufficient. Bootstrap visibility and the grant-authorized catalog/invocation paths require separate tests.

Before claiming ChatGPT support, use an authorized nonproduction fixture connection to observe that the actual client-generated authorize request contains `operations.manage` (and needed write scope), the exact client/redirect/resource, its own fresh state/PKCE, and that new code/JWT/grant/family carry the approved intersection. Never synthesize a production client's state/challenge, upgrade an old family, treat `scopes_supported` as a request, or bypass scope checks. If ChatGPT does not request the scope or cannot consume the challenge, this path remains blocked with a clear reconnect/authorization instruction. No such live test is authorized in this round.

## Acceptance before enabling

Synthetic regressions must deny ordinary OAuth, read-only and nonadmin callers, external issuers, other built-ins, unlisted targets and create/update substitution. Test exact-tool/schema drift, foreign grants/families, expired/replayed/cross-session confirmations, plan/idempotency connection swaps and revocation/downgrade while queued. Prove old business JWTs/families are unchanged, management grants grant no downstream tool access, and denied bootstrap requests disclose no target data. Add protocol tests for complete metadata/challenge forwarding, then the separately authorized real-client scope observation.
