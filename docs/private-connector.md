# Connect a private HTTP MCP

[简体中文](zh-CN/private-connector.md) · [Documentation index](README.md)

The opt-in connector exposes a **fixed set of HTTP MCP targets** through an outbound WebSocket connection. The private host runs an agent; a reachable relay authenticates that agent and Gate's consumer credential. It is a tool bridge, not an SSH, SOCKS or arbitrary TCP proxy.

## Configure the three trust relationships

Copy [relay.json](../examples/connector/relay.json) and [agent.json](../examples/connector/agent.json) outside the source checkout. Set real certificate, CA and token paths before starting.

| Credential | Used by | Authority |
|---|---|---|
| Agent token | Private agent → relay | Register only its configured target IDs |
| Consumer token | Gate → relay | Invoke only its configured target IDs |
| Upstream token, optional | Agent → private HTTP MCP | Authenticate to that fixed service |

Generate independent random agent and consumer tokens of at least 32 ASCII characters and save each in a separate protected file. All relay identities must have distinct tokens. On POSIX use the process owner's regular file with `0400` or `0600`, no group/other access; Windows requires restricted, verifiable ACLs. Files are local plaintext, not an automatic entry in Gate's encrypted store. Do not commit them.

Each target has exactly one agent owner. Agent and consumer allowlists are explicit. An authenticated caller cannot supply a destination URL, select another agent or borrow another consumer's session. Keep the relay and agent clocks synchronized: requests carry both a relative timeout and an absolute UTC expiry.

## Start relay and agent

~~~bash
lingshu-gate connector relay --config /etc/gate-connector/relay.json
lingshu-gate connector agent --config /etc/gate-connector/agent.json
~~~

Use the native executable path or `uv run lingshu-gate` from source. For a remote listener, configure TLS certificate/key files and exact `allowed_hosts`, including the port clients use. Remote agents use `wss://…/connector/agent`. Browser origins, if needed, are an exact separate allowlist. Non-browser processes normally send no Origin.

The agent's target URL is fixed HTTPS, loopback HTTP, or an explicitly approved private **literal IP** HTTP endpoint using `allow_private_http`. A private DNS name is not implicitly trusted for plaintext transport. Private CA files are explicit; certificate verification stays enabled. The agent and status command CA settings do not configure Gate Core: the relay certificate must also be trusted by the Gate process. Install a private CA in the Gate host/container trust store separately; the Core manifest has no CA-file field. Replace example relay/target addresses with your actual addresses. When keeping the example loopback target on port 18880, start the demo server on the agent host first. Network proxy environment variables are not adopted.

On the Gate host, put the consumer token in Gate's existing credential store. Configure an external Streamable HTTP service from [the relay target manifest](../examples/mcp.d/connector.yaml), replacing its `credential:connector-consumer` reference with your actual credential ID. Validate, save, apply, start, review discovered classifications, publish, and grant users their intended access. The connector does not replace any Gate authorization step.

Check the relay using the consumer's protected file:

~~~bash
lingshu-gate connector status --url https://relay.example:18882/connector/status --token-file /run/gate/consumer-token --ca-file /etc/gate-connector/relay-ca.pem
~~~

Status shows only that consumer's target IDs, connection and heartbeat state, inflight counts, last exchange status/error code and session count. It does not return tokens, arguments or response bodies. Configuration changes require restarting the affected service process and refreshing Gate's downstream connection.

## Protocol and failure boundary

The relay exposes `/connector/agent` over WebSocket, `POST` / `DELETE /connector/mcp/{target}`, and `GET /connector/status`. The MCP subset is `server/discover`, `initialize`, `notifications/initialized`, `ping`, `tools/list` and `tools/call`. Matching bounded SSE POST replies are supported; resources, prompts, reverse server requests and a general GET/SSE tunnel are not.

Requests are at most **1 MiB**, responses **8 MiB**, and WebSocket frames **12 MiB**. There are at most **16 inflight requests per agent connection**, **64 globally**, and **64 targets**. Sessions are opaque and bound to consumer, target, contract revision and connection generation, with a one-hour idle TTL. Limits and stale sessions produce explicit failures.

A timeout or disconnect can mean **the upstream result is unknown**. The connector never automatically retries or replays a business request. Check the original operation before sending another write. Reconnecting the WebSocket repairs transport only; a new generation invalidates old sessions. Session deletion releases the relay mapping even if an upstream returns 405; that does not claim the upstream process was stopped.

Credentials, Cookie and arbitrary headers are not transparently forwarded. Redirects are refused, and request/response limits apply before accumulating unbounded content. Run the relay and agent as separate processes; Gate Core does not silently launch an agent or provision an ingress endpoint.
