# My authorizations

[简体中文](zh-CN/my-authorizations.md) · [Built-in OAuth](builtin-oauth.md)

This guide describes the current development source. It does not assert publication, deployment or real-client acceptance.

## One personal entry

**My authorizations** combines personal Gate API tokens, Gate OAuth grants and external-provider grants. Authentication type remains a property of each record; the underlying credentials, protocol and revocation targets remain distinct. The legacy personal-token bookmark opens the combined page with the API-token filter. Revoking one record affects that source record only. Each source reports loading failures separately; a partially loaded list is not a complete total.

Use **New authorization** to create an API token. OAuth grants still originate from the client's actual authorization flow. An API-token secret appears only in the successful creation response and one-time display; listing records never recovers it. Scope and quota edits require the active owner's Console session and `credentials.manage.self`.

## MCP scope

Each business MCP has three explicit choices: **No access**, **Continuous authorization**, or **Selected tools**. Continuous access is either read-only or read/write; read/write includes future published write tools. Selecting all current tools retains a snapshot and does not imply continuous authorization. A service cannot simultaneously use continuous and selected-tool modes in the same authorization.

Continuous authorization is implemented for independent Gate API-token scopes and Gate business OAuth grants. Later tools join only after valid classification publication and only within current account resource permissions and functional scopes. Unpublished tools remain unavailable. Read-only continuous policies never acquire write tools. A changed tool is unavailable while its classification is invalid; after review and publication a continuous policy reevaluates it, while a selected-tool snapshot still requires explicit reconfirmation.

Service policies bind the MCP lifecycle identity. Deleting/recreating a service or replacing its trust target does not transfer old authorization merely because its ID or name is reused. A display rename or ordinary upgrade that preserves the trusted identity preserves continuous intent. API-token selected snapshots also bind service identity. Classification, discovery, authorization and deployment remain separate operations.

Existing selected-tool OAuth grants retain their saved snapshots; they are not silently converted. Existing API tokens without an independent policy keep **Follows account resource access**, including their previous inheritance behavior. They have no invented quota. The owner can explicitly convert a token to independent MCP scope; an empty independent scope grants no business MCP access. The editor does not offer a return to account-following mode. Functional control permissions remain separate from business MCP selection.

External-provider grants retain their existing provider/local allowlist contract and do not offer continuous MCP authorization. The separately enabled `/mcp/manage` resource retains its fixed management-tool and exact-target contract; it does not subscribe to business MCPs.

## Tool discovery

The Tool discovery column opens a centered editor for that record with On demand and Full tool list radio choices. **New and existing business authorizations default to on-demand**. Each API token, built-in business OAuth grant and external OAuth local grant saves its own mode; management retains fixed tools. On-demand exposes six default discovery/invocation/instance-session entries, optional authorized pins and the result reader when enabled; direct mode lists currently permitted tools. Both keep the same authority checks.

Client settings now save only the name and endpoint; generated configuration omits `tool_mode`, including when reading old browser preferences. Legacy URL/header mode hints are ignored; only the authorization setting applies. Refresh the client tool cache or reconnect after switching. Owner confirmation, CSRF, revision checks and atomic audit protect changes; unknown outcomes require readback before retrying. This does not edit global rules, MCP client plugin configuration or the host's local-MCP/plugin routing preference.

Actual local synthetic screenshots: [independent modes](images/console/continuous-authorization/runtime-discovery-per-authorization.png), [mode editor](images/console/continuous-authorization/runtime-discovery-editor.png), and [client settings without the duplicate choice](images/console/continuous-authorization/runtime-client-settings-without-mode.png). These do not prove deployment or real-client cache refresh.

## Editable quotas and safe saving

New business authorizations default to **6000 calls per minute** and **100 concurrent calls**. The editable boundaries are integers **1–10000** and **1–100** respectively. Existing records load their actual values; opening an editor does not replace them with defaults. Old API tokens show unset quotas until explicitly configured. The owner-confirmed API-token and business OAuth editors support increasing or decreasing quotas, including quota-only changes. Legacy shrink-only OAuth operations keep their original contract, and quota editing does not extend expiry or increase OAuth scopes.

Preview identifies the exact target, policy changes, added/removed tools, future write authority and previous/new quotas. Preview grants nothing. Save requires explicit confirmation, current permission checks, version/catalog/target binding, a single-use confirmation, revision compare-and-swap and an atomic redacted audit. Audit failure rolls back the change. A quota-only save preserves stale selected snapshots and invalid service bindings; it does not reapprove them. Unknown save results retain the draft and require reading the actual state before another write; creation must not be blindly replayed to recover a lost secret.

Runtime access intersects current account/resource permissions, the token or grant policy, valid published classification and functional scope. Gate OAuth additionally intersects the registered client, grant, JWT and family scopes. Quota changes do not reset consumed rate counts. Lowering concurrency does not cancel dispatched calls; subsequent admission uses the new limit. Business calls share a budget per API-token ID or OAuth grant ID across MCPs; listing tools is not tool execution. Counters remain limited to one Core process and reset on process restart. SQLite requires one writer/Core; the defaults do not promise measured throughput.

## Directory and verification limits

The API-token creation/editor directory currently supports a complete candidate response up to **5000 tools / 100 MCPs**. New creation beyond that bound fails explicitly; it does not silently truncate. When a larger owner's unrelated directory exceeds this limit, a smaller existing token can load its bounded saved scope with `catalog_complete=false` and `scope_editable=false` and edit quotas only. Broader API-token candidate pagination is not implemented. Saved/effective scopes remain bounded and fail closed on overflow.

The Console follows the [UI interaction contract](ui-interaction-contract.md): compact tables, left labels/right controls, accessible mode radios, no repeated page introductions, and contextual errors or requested help. A source read failure is not displayed as an empty complete list.

Gate reevaluates subsequent requests and rechecks queued calls before dispatch. It does not push a replacement tool list or broaden client OAuth authorization. Clients may cache their directory and need a refresh. Actual provider/ChatGPT connection behavior, cache refresh, deployment and production capacity require separate acceptance; source and synthetic tests do not establish those outcomes.

## Saved discovery preferences

The discovery editor also manages up to 20 pins and an optional plain-text result budget. Mode, pins and budget share one reviewed revision and atomic save. Switching mode preserves other draft fields; unavailable discovery is an error, not an empty selection. Refresh after a conflict before confirming again. Preferences preserve the credential's scope and expiry. See [pinned tools and result budgets](on-demand-tools.md#pinned-tools-and-result-budgets) for limits and group-session requirements.
