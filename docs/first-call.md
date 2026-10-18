# First successful and denied tool calls

[简体中文](zh-CN/first-call.md) · [Getting started](getting-started.md) · [Documentation index](README.md)

Use the bundled in-memory MCP to check discovery, publication, a restricted token and an actual denied write. It has no external account, database, filesystem commands or network actions. Its note, revision and write counter reset when the demo process stops.

First [install Gate, sign in and change its initial password](getting-started.md). This walkthrough uses existing HTTP tools and needs no separate desktop MCP client.

## Start the demo beside Gate

With a native package, open a second terminal in its directory:

~~~bash
./lingshu-gate demo-server --host 127.0.0.1 --port 18880
~~~

On Windows use `.\lingshu-gate.exe demo-server --host 127.0.0.1 --port 18880`. From the source checkout use `uv run lingshu-gate demo-server --host 127.0.0.1 --port 18880`. Keep that process running while using Gate. An occupied demo port is an error; it does not silently select another port.

For the **downloaded Docker trial**, from the extracted directory:

~~~bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
~~~

For a **downloaded production bundle**, first complete its `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md` setup, including the image, HTTPS entry and bootstrap secret:

~~~bash
docker compose --env-file .env -f compose.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
~~~

For a source Compose installation, opt into the supplied override:

~~~bash
mkdir -p runtime/workspace
docker compose -f compose.yaml -f examples/compose.demo.yaml up -d --build --wait --wait-timeout 120 core demo
~~~

These commands wait for Core and the actual demo listener. An offline installation first loads its matching offline image and selects `LINGSHU_GATE_PULL_POLICY=never` in its chosen env file. The demo uses the same image as Core and shares Core's network namespace; it does not expose another host port. A normal separate container cannot reach this loopback-only server by its service name.

## Connect and publish

1. Sign in as administrator. On a fresh instance read the local one-time credentials, change the password, then sign in again. The old session is revoked and a generated initial-credentials file is removed. An externally provisioned production password file remains under operator control.
2. In the MCP service workspace create an **external Streamable HTTP** service from [the demo manifest](../examples/mcp.d/demo.yaml). Validate, save, apply and start it as separate operations. The target is `http://127.0.0.1:18880/mcp`, with automatic protocol negotiation.
3. Discover its three tools. Review `gate_demo_echo` and `gate_demo_note_read` as **read**, non-destructive and idempotent. Review `gate_demo_note_write` as **write**, non-destructive and non-idempotent: repeated writes increment its counter.
4. Confirm the reviewed classification and then publish it. Discovery, saving a manifest and confirmation alone do not publish access.

The service ID in the example is `demo`. If you change it, use the tool references returned by your own directory.

## Create a restricted caller

Create a separate active viewer account and grant it **read** access to this demo service. Sign in as that user, change its password if required, and create a personal API token with functional scope `tools.read` and continuous **read-only** access to this service. Keep its discovery mode **On demand**, without added pins. Copy the one-time token; listing tokens cannot recover its secret.

Use this separate token for the following requests. An administrator's own token does not demonstrate restricted access. Save only the non-secret JSON bodies to a local `request.json` outside the repository. In a local Bash terminal, this helper sends the bearer through standard input rather than external process arguments:

~~~bash
GATE_URL='http://127.0.0.1:8000'
read -rsp 'Demo viewer token: ' GATE_TOKEN
builtin export -n GATE_TOKEN
builtin printf '\n'
gate_request() {
  local method="$1" name="$2" body_file="$3"
  local -a headers=(-H 'Content-Type: application/json' -H 'Accept: application/json'
    -H 'MCP-Protocol-Version: 2026-07-28' -H "MCP-Method: $method")
  if [[ -n "$name" ]]; then headers+=(-H "MCP-Name: $name"); fi
  builtin printf 'Authorization: Bearer %s\n' "$GATE_TOKEN" |
    curl --fail-with-body --silent --show-error --connect-timeout 5 --max-time 30 "$GATE_URL/mcp" \
      --header @- "${headers[@]}" --data-binary "@$body_file"
}
~~~

Behind HTTPS set `GATE_URL` to the actual trusted entry; use the actual URL if you changed the local port. The Bash builtin writes the header to curl's stdin. The token is not expanded into curl's argv or exported to child environments. Do not enable shell tracing.

Windows PowerShell can send the same JSON without another client installation:

~~~powershell
$GateUrl = 'http://127.0.0.1:8000'
$SecureToken = Read-Host 'Demo viewer token' -AsSecureString
$GateToken = [System.Net.NetworkCredential]::new('', $SecureToken).Password
function Invoke-GateRequest([string]$Method, [string]$Name, [string]$BodyFile) {
    $Headers = @{
        Authorization = "Bearer $GateToken"
        Accept = 'application/json'
        'MCP-Protocol-Version' = '2026-07-28'
        'MCP-Method' = $Method
    }
    if ($Name) { $Headers['MCP-Name'] = $Name }
    $Body = [System.IO.File]::ReadAllText((Resolve-Path $BodyFile).Path)
    Invoke-RestMethod -Uri "$GateUrl/mcp" -Method Post -Headers $Headers `
        -ContentType 'application/json; charset=utf-8' -Body $Body |
        ConvertTo-Json -Depth 30
}
~~~

The bearer stays in the PowerShell process's memory. Replace a Bash helper call with `Invoke-GateRequest -Method 'tools/call' -Name 'gate_tool_describe' -BodyFile '.\request.json'`, adjusting method/name to that step. For `tools/list` use `-Method 'tools/list' -Name ''`. These HTTP examples do not claim testing of third-party desktop clients.

## Discover, read, attempt a write, and check the counter

Send JSON-RPC to `$GATE_URL/mcp` with these headers:

~~~text
Authorization: Bearer <the viewer token>
Content-Type: application/json
Accept: application/json
MCP-Protocol-Version: 2026-07-28
MCP-Method: tools/call
MCP-Name: <params.name>
~~~

For a `tools/call` request, set `MCP-Name` to the JSON body's `params.name`; omit it for `tools/list`. The included `params._meta` is required by protocol 2026-07-28. Copy each body below to `request.json`, replace indicated references/revisions with returned values and send it using the matching helper arguments. For example:

~~~bash
gate_request tools/call gate_tool_describe request.json
~~~

Change the second argument to `gate_tool_invoke` for invocation bodies. A nonzero curl status or PowerShell exception indicates an HTTP failure; inspect JSON-RPC errors and `result.isError` in an HTTP 200 response too.

**List the gateway entries** with `gate_request tools/list '' request.json`:

~~~json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

Without pins, on-demand discovery lists six entries, including `gate_catalog_search`, `gate_tool_describe` and `gate_tool_invoke`. Listing an entry does not grant downstream access.

**Search the permitted catalog** with `gate_request tools/call gate_catalog_search request.json`:

~~~json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"gate_catalog_search","arguments":{"query":"gate_demo","limit":20},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

Find `gate_demo_echo` and `gate_demo_note_read` and copy their actual returned `tool_ref` values. The write tool should be absent for this read-only viewer.

**Describe `gate_demo_note_read`**, using that tool's returned reference. Use this note-reading tool for the empty-argument request below; echo needs a message and is checked separately afterward:

~~~json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"gate_tool_describe","arguments":{"tool_ref":"<returned read tool_ref>"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

Read the input schema, then copy this tool's returned 64-character `schema_revision` into the call:

~~~json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"gate_tool_invoke","arguments":{"tool_ref":"<returned read tool_ref>","schema_revision":"<returned revision>","arguments":{}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

The successful result reports `text`, `revision` and `write_count`. Record the counter.

To check echo, describe its own returned reference and invoke its own revision with `arguments: {"message":"Hello from Gate"}`. Confirm the returned message equals that text. As the viewer, open **My invocations / 我的调用** and locate the successful underlying demo tool and outcome; the administrator can inspect its invocation audit. Audit decisions do not require optional invocation-content recording, which this walkthrough does not enable.

To exercise an actual authorization rejection, use a separate administrator terminal/authorization to search and describe the write tool, providing only its actual reference and current revision to the demonstration operator. Keep the **viewer token** in the terminal performing the denied call:

~~~json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"gate_tool_invoke","arguments":{"tool_ref":"<write reference from administrator>","schema_revision":"<current write-tool revision>","arguments":{"text":"This write must be denied"}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

Gate returns an MCP error (`isError: true`); HTTP 200 alone does not mean a tool succeeded. Repeat the read call: its `write_count` and note must be unchanged. The administrator can inspect the corresponding invocation audit for the denial and `not_invoked` outcome. A caller without permission cannot describe a hidden tool merely to obtain its revision.

## Check a changed revision, stopping and revocation

Copy the valid read request and change one hexadecimal character in its 64-character `schema_revision`, ensuring it differs from the current value. Invoke it and expect `catalog_schema_revision_conflict` without downstream execution. This deliberate mismatch tests the guard. For a real definition change, describe the permitted tool again and review its new schema before accepting that current revision. Restore the actual revision and confirm the read succeeds.

While the viewer token is still valid, stop the demo. For the downloaded Docker trial:

~~~bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml stop demo
~~~

For production use `.env` and `compose.yaml`; for source Compose keep its original two files. For native use Ctrl+C in the demo terminal. Repeat the valid read and inspect the MCP error, service state and invocation outcome. Catalog or recovery failures can include a structured error code; a transport connection failure can instead return `isError: true` with a text `content` entry. Check the corresponding failed invocation audit, or the catalog rejection event if the tool has already left the registry. Gate itself should still respond at `/readyz`. A stopped/disconnected tool can leave the callable catalog; no branch should return a successful cached note.

Restart the demo with the original command, then reconnect the saved service in Gate if required. Search/describe again and invoke the current read contract. An unchanged definition preserves its published review; the demo's in-memory note and counter reset. Changed definitions require review/publication before use.

Finally revoke the viewer token in **My authorizations / 我的授权** and repeat a request with the same bearer token. It must fail authentication; supplying a Console cookie does not rescue an explicitly revoked bearer token. Clear the terminal variable with `unset GATE_TOKEN` and remove the helper with `unset -f gate_request`. In PowerShell use `$GateToken = $null; $SecureToken.Dispose(); Remove-Variable GateToken, SecureToken; Remove-Item Function:\Invoke-GateRequest`.

## If a step fails

| Observation | Check |
|---|---|
| Cannot connect | Demo process, shared network namespace, exact endpoint and Gate service state |
| Empty or missing tool directory | Classification publication, account grant, functional token scope and token's MCP selection |
| Schema revision rejected | Describe the current permitted tool and review changed definitions |
| A denied call appears successful | Inspect `isError` / the tool error; do not interpret HTTP 200 alone |
| Client still shows old tools | Refresh its tool cache or reconnect after changing discovery settings |
| Counter increased | Verify that the write used the restricted viewer token and that no other caller wrote concurrently |

Stop the independent demo after the walkthrough. Gate retains its saved service configuration; follow the package README to stop Gate while preserving data.
