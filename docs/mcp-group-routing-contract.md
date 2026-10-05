# MCP group routing adapter

[简体中文](zh-CN/mcp-group-routing-contract.md) · [Groups](mcp-groups.md)

This internal port is implemented on the exact 0.4.4 base. The on-demand directory owns the public MCP invocation entry. Grouping adds no second generic invocation endpoint and does not register grouped aliases as downstream tools.

`McpGroupRoutingService.resolve(actor, tool_ref=..., instance_id=...)` returns `CatalogTarget` with actual `server_id`, original `tool_id`, explicit `instance_id`, logical `service_id`, `group_id`, `group_revision`, `schema_revision` and `definition_fingerprint`. `schema_revision` is the partition's complete contract fingerprint. Logical references use `mcp-group:<group-id>:<partition-fingerprint>`. Existing `mcp.<server-id>.<name>` IDs and APIs remain available.

`search` and `describe` intersect current user/role/control permissions, API token or OAuth grant ceilings, physical instance/tool policy, and logical service/tool grants. Grants for a logical service use the existing resource-grant store's `server_id=mcp-group:<group-id>` and optional exact `tool_id=tool_ref`. Adding a member creates no grant. OAuth continues to authorize the original physical tool IDs; a logical route cannot enlarge that allowlist. Structural memoization contains no authority.

`open_session(actor, GroupToolSelection)` takes an explicit `tool_ref` and existing `instance_id`. It returns a generated session identifier, bound to the actor's authenticated connection, group revision, configuration digest and current runtime generation. A group's persisted `default_instance_id` is only a suggestion; omitted instance selection is rejected. Routing envelopes reject endpoints, secrets and unknown fields. The default must be a selected, available member.

The shared invocation entry wraps its original invocation path in `dispatch_guard(actor, GroupToolCall)` and receives `(current_actor, target)`:

```python
with router.dispatch_guard(actor, call) as (current_actor, target):
    response = access.invoke_tool(
        registry, current_actor, target.tool_id, call.arguments,
        expected_definition_revision=target.definition_fingerprint,
        allow_read_retry=False,
    )
```

The guard holds the configuration and runtime locks through dispatch. It rechecks authority after lock waits, reads the current contract and requires the original bound instance. The existing invoker supplies classification, per-user credential resolution, rate limits and the physical tool's audit. Route fields are never added to `arguments`. No peer selection, write retry or failover happens in this port. A close, expiry, group edit, configuration change, runtime replacement or Gate restart invalidates the session; the caller must reconcile before explicitly opening another. Sessions last at most one hour and are bounded to 128 per connection and 10,000 globally.

This is instance stickiness. Existing shared downstream connections and per-call user-credential transports retain their current lifecycle; the adapter does not promise a private downstream MCP session per logical session. Identical out-of-band delete/recreate between observations remains indistinguishable. Synthetic peers prove the port and existing invoker's behavior; deployment and real provider/SSH/browser acceptance are outside this development task.
