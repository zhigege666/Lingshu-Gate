# Test an external HTTP MCP connection

[简体中文](zh-CN/http-mcp-connection-testing.md)

This guide describes HTTP authentication and connection testing in 0.5.6. Installing the published version is required to use the new controls; a source checkout or successful test does not upgrade a running instance.

## Console

Open a new or existing external HTTP MCP configuration. Enter the service ID and endpoint, select an authentication method and an existing or new credential, then select **Test connection**. The footer keeps Cancel, Test connection and Save Config. Static validation runs automatically before saving; its manual action is under Advanced configuration (and in the JSON toolbar). Network testing is optional and remains separate from saving, runtime connection and tool publication. The request originates from the Gate host, not the browser.

The result reports five stages: configuration, HTTP reachability, request authentication, MCP handshake and tool discovery. Each stage is passed, failed or not verified. HTTP 200 alone is not success: a login page or other HTML response does not establish MCP compatibility. A successful tool listing does not prove permission to invoke any particular business operation.

The test uses a new temporary protocol client. It neither saves the draft, grants/revokes connection permission, binds pending credentials, starts a managed process, changes the running connection nor publishes tools. It never calls a business tool. Draft edits invalidate the displayed result; unfinished form rows block testing. Pending tests block duplicate submissions and ordinary dialog navigation. A browser wait timeout does not claim that a remote request was canceled.

The default test budget is 15 seconds. The API accepts a budget of 1–30 seconds, using the existing transport deadline and response/page limits. At most two tests execute concurrently in one Core; a saturated test slot returns `http_test_busy`. There are no automatic business retries. Operating-system DNS resolution and connection cleanup remain subject to the underlying transport behavior.

## Credentials and endpoint permission

Choose **None**, **Bearer Token**, **API Key**, **Basic**, or **Custom**. Choosing an existing credential writes the reference-based header directly into the semantic draft; there is no additional Add step. None removes only the recognized authentication header. Multiple, unsupported or masked authentication values stay Custom and are not silently discarded or decoded. Other headers survive preset changes and Form/JSON round trips.

**New credential** presents a name and secret; its editable ID is generated automatically and placed in a collapsed section. Bearer accepts the token alone or one pasted `Bearer ` prefix. API Key offers `X-API-Key`, `Api-Key`, and a custom header name. Basic asks for username and password and encodes them before the normal encrypted credential write; an existing Basic credential must already contain the encoded value. Base64 encoding is not transport encryption: use a protected connection. Values never enter the manifest, browser storage or configuration history. Failed credential writes retain input and reuse the operation key for unchanged retries; explicit cancellation clears the input. A successful credential write survives cancellation of the configuration.

While a credential is unfinished, Save and Test remain unavailable and the footer names that specific reason. Changing authentication/runtime modes cannot silently discard it; save or explicitly cancel the credential first. Choosing None or Custom cannot wipe unrelated headers. Credential-list errors have a Reload action and are not represented as empty results. Only matching service/origin scopes can be selected in the preset list; the backend still validates the exact lifecycle and current permission.

**Advanced headers** retains the full key/value editor for exceptional configurations. Gate generates Content-Type, Accept and MCP protocol headers. The **Home** shortcut selects Bearer, shows the token creation instructions and appends `/mcp` only to an explicit root URL. It never overwrites an existing path, guesses a port, requests a token, changes permissions or sends network traffic. The form remains vendor-neutral.

Connection results sit below authentication. A short summary emphasizes success/failure, elapsed time and discovered tool count, with icon-and-text stage states. Protocol/status codes and further details are expandable. Results belong to their tested draft; no success is retained as current after the draft changes. The desktop dialog uses a 1200 px maximum width and keeps footer actions outside the body scroll area.

The credential must be explicitly scoped to this service ID and exact HTTP origin. Tests may use a matching pending credential scope without sealing it or changing its revision. A saved scope bound to a different service lifecycle or address is not reusable. A changed credential revision, saved configuration or connection policy aborts the test before another protocol request.

For an unsaved private-HTTP draft, the explicit administrator test permits only that request-local target. It does not create reusable trust. An existing revoked or needs-review permission is never restored by a test, including after recreation of a service ID. Ordinary HTTPS verification and redirect rejection remain enabled. Plain HTTP is still unencrypted; prefer HTTPS or a separately secured private transport.

Configurations declaring personal downstream credential slots are not tested by this shared-administrator path. They return `personal_credentials_required`; use the caller-owned personal connection flow instead of borrowing another identity.

## MCP and REST

The new tool is `gate_http_mcp_test`. It is a non-destructive, network-using management action, not a business write. It requires current administrator authority, `operations.manage` and `tools.invoke`, plus the tool scope and exact target action `test` when management OAuth is used. Previous consent does not silently gain the new tool or target action. Existing explicitly wildcard-scoped administrator API tokens retain their normal authorization semantics.

Example tool arguments, using a previously created and appropriately scoped credential:

```json
{
  "manifest": {
    "id": "example-home",
    "enabled": true,
    "launch": {"type": "external"},
    "transport": {
      "type": "streamable_http",
      "endpoint": "https://home.example.test/mcp",
      "headers": {"Authorization": "Bearer ${credential:example-home-token}"}
    }
  },
  "confirmed": true,
  "timeout_seconds": 15
}
```

For an existing configuration, also provide `existing_server_id` and its original `expected_config_digest`. Omitting them does not turn an existing ID into a new draft. The MCP tool and `POST /v1/mcp/external-configs/test` share the same application service and safe result contract.

Console sessions require a same-origin, one-use CSRF ticket bound to the full test body. The Console obtains it by posting that same body to `/v1/mcp/external-configs/test/csrf`; the server computes the canonical digest, so LAN HTTP does not depend on browser WebCrypto. The test then sends the ticket as `X-CSRF-Token`. The existing `/external-configs/csrf?action=test&request_digest=...` route is also available. Tickets, diagnostic results and errors must not be reused across sessions. The dedicated successful responses use `Cache-Control: no-store`.

Results expose finite stage/error codes, HTTP status, elapsed time, negotiated protocol and tool count. They never include a raw response body or resolved credential. `config_saved`, `trust_changed`, `registry_changed` and `business_permissions_verified` remain false. A Bearer challenge is not evidence of OAuth support. The test may report that OAuth resource metadata was advertised, but does not fetch untrusted metadata, sign in or acquire tokens automatically.

## Troubleshooting

| Result | Next action |
| --- | --- |
| `authentication_required` / 401 | Check the token issuer, format, expiry and revocation. A challenge is only a scheme hint. |
| `access_denied` / 403 | Check account/action/space permissions, Origin rules and reverse proxies; 403 does not prove expiry. |
| `endpoint_not_found` / 404 or `http_method_not_allowed` / 405 | Check the actual MCP path and POST forwarding. |
| `redirect_blocked` | Enter the reviewed final endpoint; credentials are not forwarded through redirects. |
| `tls_failed` | Correct the certificate chain or hostname; do not disable verification. |
| `network_failed` / `timeout` | Check routing, DNS, firewall, container networking and the service from the Gate host. |
| `mcp_protocol_failed` | Check Streamable HTTP support and protocol negotiation; a normal webpage is not an MCP server. |
| `credential_scope_denied` / `credential_changed` | Use a target-scoped credential and reload changed state before retesting. |
| `config_changed` / `http_trust_revoked` | Reload the original configuration, or explicitly restore permission through the normal save flow. |

### Home example

Home 0.0.2's repository documents **Admin → Data sources and MCP → MCP and access tokens → Create token**. Choose the current-space scope for bookmarks/page operations rather than a source-only push token. Use the endpoint shown by that Home instance, ending in `/mcp`, and its own PAT as a Bearer credential. Browser login cookies, account passwords and a GitHub Traffic token are not substitutes.

`navigation:read` supports bookmark reads. Dashboard reads additionally require `pages:read`, plus `sources:read` for external inputs. Add `navigation:write` only when bookmark edits are required. Page editing has its own `pages:write` and binding read requirements. Home validates the account, space and action at invocation; discovery alone cannot prove all those rights.

References: [Home user guide](https://github.com/zhigege666/Lingshu-Home/blob/main/docs/USER_GUIDE.md), [Home API contract](https://github.com/zhigege666/Lingshu-Home/blob/main/docs/API.md), [Home MCP implementation](https://github.com/zhigege666/Lingshu-Home/blob/main/server/internal/home/integrations_mcp.go). Check the deployed Home version independently. Repository inspection and isolated test-peer success do not constitute a production Home login test.
