# Business credentials and browser accounts

[简体中文](zh-CN/business-credentials.md) · [Configuration](configuration.md) · [Documentation index](README.md)

Business credentials let you maintain a website account in Gate, authorize specific MCP instances to use it, and give an agent a reference instead of a password. This guide covers the `agent_browser` adapter. A binding is an additional restriction: it does not publish tools or expand the caller's existing MCP permissions.

## Choose the correct credential type

| Credential type | Use it for |
| --- | --- |
| Shared service credentials | Server startup environment variables and shared HTTP headers, through existing credential references. |
| My service credentials | Personal downstream HTTP headers in the slots declared by an eligible MCP instance. |
| Business credentials | Website accounts, environment and business-role labels, explicit target bindings, and versioned copies in an agent-browser vault. |

Business credentials do not turn an HTTP header slot into a browser account. OAuth consent, access tokens, and refresh tokens remain a separate authorization flow. Other MCP products need an adapter with a reviewed contract; an arbitrary tool cannot resolve a business credential reference.

## Prepare a browser instance

Use a dedicated, trusted instance of the official agent-browser MCP server. Its startup configuration must expose the browser tools and the `state` profile, for example:

~~~text
agent-browser mcp --tools core,state
~~~

The adapter checks the discovered save, login, delete, and navigation contracts. In particular, login must support `session` and `noNavigate`. The default `core` profile alone does not expose the auth tools. If the compatibility check fails, inspect the actual installed version and discovered tools; a matching tool name alone is insufficient.

Review classification and publication in Gate as usual. A user must already be permitted to invoke the relevant MCP tools. Binding an account never grants that permission.

The administrator must also ensure that the instance starts its own browser, has protected local storage, and does not inherit a shared CDP connection, a reused browser profile, restored state, or an unreviewed provider or plugin. The binding checks explicit manifest overrides, but Gate cannot inspect every configuration file or inherited setting on a remote machine.

The first adapter does not support browser targets with per-user downstream HTTP-header slots (`user_credentials`). Such headers can route different Gate users to different remote vaults or browser domains, so an administrator's save or close receipt would not establish the outcome for another user's target. Use a dedicated instance with one reviewed target identity.

**Binding an account enables credential-managed restrictions for that MCP instance.** The restrictions apply to calls through Gate, including calls made by other users of that instance. Use a separate instance for unrestricted browser diagnostics. Removing the final account or binding does not reopen the raw vault tools.

## Create an account and select its targets

1. Open the business-account section of the appropriate credentials page. Use the personal scope for an account you alone manage and use; use the shared scope for an account managed for explicitly authorized users or Gate roles.
2. Enter a descriptive name, such as `Staging clinician`, the environment, the business role, the login URL, username, and password. The business-role label describes the website account; it does not assign a Gate authorization role.
3. For shared credentials, select the allowed Gate users or roles. An empty recipient list is not an instruction to grant everyone access.
4. Keep optional username, password, and submit selectors empty when the site's normal login form works. Configure them only for the site's actual controls.
5. Save the account. Responses show a username mask and configuration status; they do not reveal stored passwords. When editing, leave username and password empty to retain their existing values. A displayed mask is not a replacement credential.
6. Add a binding to each eligible MCP instance. Check the instance ID, not only the machine's display name. Each binding has its own synchronization state.
7. Synchronize the selected binding and read back its state and synchronized version. Repeat for the other selected instances.

Enter secrets only through a trusted HTTPS Gate entry or a local loopback connection. The website login URL also defaults to HTTPS. A legacy HTTP login requires an explicit HTTP acknowledgement; this does not relax protection of the Gate management connection. HTTP sends the account password over that website's network connection without TLS.

Login URLs must be absolute HTTP(S) URLs without embedded credentials or a query string. A route fragment such as `#/login` is supported; fragments that contain `?` or `=` or do not start with `/` are rejected. Do not put passwords or tokens in a URL, display name, environment, role label, selector, manifest, or chat message.

## Ask an agent to log in

Select the bound instance's `agent_browser_auth_login` tool through Gate. Use the credential reference shown by the page and an explicit logical session:

~~~json
{
  "name": "gate:<credential-id>",
  "session": "task-demo"
}
~~~

These are the tool's arguments. Choose the target instance separately; do not add `server_id` to this argument object. Replace `<credential-id>` with the actual ID. The display name helps people choose an account, while the reference identifies it unambiguously.

A suitable instruction is:

> Use the “Staging clinician” credential on the selected browser instance in session `task-demo`, then check the page for the application's signed-in state.

Gate validates the account, caller, target binding, current version, and tool contract before using the remote copy. It opens the configured login page and uses the native login operation with origin verification before filling credentials. Callers cannot override the login URL or provide arbitrary CLI arguments.

**“Login action performed” is not proof of successful website authentication.** The native operation fills and submits a form; the site can still reject the password, request a verification code, or require another step. Inspect the returned page state using the permitted browser tools. This adapter does not automatically verify a site's account identity or complete its MFA flow.

Use the same logical session for subsequent actions:

~~~json
{
  "session": "task-demo",
  "interactive": true,
  "compact": true
}
~~~

The example above is for `agent_browser_snapshot`. Gate maps the logical session to an internal session associated with the caller and target, and binds it to the chosen credential. Use a new logical session for another account or role. A change to the credential version or binding revision invalidates existing sessions for further browser actions; close them and start a new session after completing the required synchronization. This also applies when a binding is disabled and enabled again or its synchronization is repeated.

The first adapter allows a reviewed set of navigation, form interaction, waiting, text/snapshot inspection, and session-close tools. Direct `open` requests must stay on the configured login origin. A website link or browser history can lead elsewhere; that does not authorize Gate to fill credentials on the new origin.

Tools that can read the host, export browser state, execute arbitrary JavaScript, or alter the browser runtime are unavailable on a credential-managed instance. This includes raw vault management, `eval`, input-value/HTML inspection, cookies/storage/state export, network capture, file upload/download, screenshots, batch execution, plugins, CDP attachment, and global session controls. Unknown tools and unreviewed fields also fail closed. These restrictions are part of the adapter, even when a broader MCP token would otherwise permit the tool.

For this adapter, string arguments passed to the native CLI must not start with `-`. This includes selectors, form text, select-option values, and stored usernames; otherwise the CLI could interpret a data value as a process option. The saved password is passed through stdin and is exempt from this restriction. Gate rejects such unsupported values instead of silently changing them.

## Understand synchronization states

| State | Meaning | Next action |
| --- | --- | --- |
| `pending` | This binding has no confirmed copy of the current account version. | Synchronize the selected instance. |
| `synced` | Gate received the expected success receipt for the recorded version. | Compare the synchronized version with the current version before use. |
| `failed` | The operation failed. An older or partially updated remote copy may still exist. | Resolve the reported condition and retry the relevant operation. |
| `unknown` | Gate cannot confirm the outcome, for example after a timeout or interrupted response. | Treat a remote copy as possible; retry synchronization or cleanup through Gate. |
| `deleted` | Gate received confirmation that this binding's remote vault entry was deleted. | Synchronize again only if the account should remain usable. |

Editing an account creates a new version and marks its bindings pending. It does not silently claim that all nodes have been updated. Synchronize the intended targets explicitly. A stale page or an operation based on an older revision is rejected; reload the record before retrying.

A successful synchronization receipt proves that the configured target accepted the save operation. It is not an independent inspection of the target's disk, nor proof that the website accepts the password. If a delete reply is lost, an empty vault listing does not prove cleanup; retain the unresolved record until cleanup can be verified.

**Before upgrading a bound target or changing its manifest or tool contract, disable the affected bindings, delete their remote copies, close their managed browser sessions, and remove the bindings.** Then change the target and create reviewed bindings again. The first adapter pins the original target and tool contracts; it does not silently accept a changed target for cleanup or login. If a change has already occurred, restore the original reviewed configuration when possible to complete cleanup first. A successful operation against a replacement target must not be used as proof that the old target was cleaned up.

## Disable, clean up, and close separately

| Action | What it does | What it does not do |
| --- | --- | --- |
| Disable a credential or binding | Prevents further authorized use through that binding. | Does not delete a password already stored on a node or revoke a website session. |
| Delete a remote copy | Calls the adapter's controlled vault-delete operation for that binding. | Does not sign out an already-open browser. |
| Close a browser session | Closes the selected managed browser session. | Does not revoke all sessions issued by the website. |
| Delete the Gate record | Removes the local encrypted record after required remote-copy cleanup. | Does not replace website-side account or session revocation. |

To retire an account, disable it, clean up each remote vault copy, and separately close the browser sessions that used it. Gate retains records whose remote cleanup is unresolved; an offline node does not become “cleaned up” merely because its account was disabled. Remove the Gate record after the required cleanup succeeds.

In the account's binding view, expand **Browser sessions** to inspect recorded session states and close an individual session. A state of `unknown` requires checking or cleanup; it is not confirmation that no browser was opened. A successful close is displayed as browser closure, with website sign-out still unverified.

To close the current logical session, call the selected instance's `agent_browser_close` with:

~~~json
{
  "session": "task-demo"
}
~~~

The native `all` option is prohibited. Do not use a global close to terminate unrelated users' work. Where website-wide logout is required, use the site's own session-management or account-revocation mechanism separately.

## Security and recovery boundaries

Gate encrypts business usernames and passwords at rest, keeps secrets outside MCP manifests, and exposes safe metadata through its management APIs. Controlled save/delete/login responses use bounded status data. Text from an active credential-bound browser session is scrubbed for the current stored secret and supported encoded forms before being returned; this is additional protection, not a guarantee about arbitrary transformations performed by a website.

Managed browser responses are rebuilt from the reviewed action result, without raw CLI stdout/stderr, and are excluded from Gate's short-lived `gate_result_read` cache. Disabling a credential blocks new managed calls; it cannot withdraw information already delivered to a caller.

The target browser must receive and fill the real password. Its host administrator and code running in that browser's trusted execution boundary can therefore access it. The adapter cannot protect against a malicious target host, hostile site code, direct vault access, or another gateway that bypasses these controls. Use a dedicated trusted target and a trusted login origin.

agent-browser's vault is scoped to the operating-system user, not to its browser session. Multiple Gate installations sharing the same OS user or vault are outside this adapter's isolation guarantee. Session naming does not replace OS or container isolation. The workflow prevents accidental reuse and unauthorized calls through this Gate instance; it does not claim a general sandbox for mutually hostile users.

Back up the Gate database and its protected credential key material together. For business credentials, the key is under `<data-dir>/business-credentials/credential.key`; ciphertext is in the Gate database. The remote agent-browser vault has its own key and lifecycle. Losing either store's key can make its encrypted values unreadable. Keep backups outside the repository and inaccessible to browser content.

For installation and deployment, see [Getting started](getting-started.md) and [Configuration](configuration.md). Upstream contracts are documented in the official [agent-browser commands](https://agent-browser.dev/commands), [security](https://agent-browser.dev/security), and [sessions](https://agent-browser.dev/sessions) guides. MCP transport authorization is described separately in the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
