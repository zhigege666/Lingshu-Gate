# MCP 分组路由适配接口

[English](../mcp-group-routing-contract.md) · [分组](mcp-groups.md)

本内部 port 基于 exact 0.4.4 实现。公开 MCP 调用入口由按需目录持有。分组不增加第二套通用调用端点，也不把逻辑别名注册成下游工具。

`McpGroupRoutingService.resolve(actor, tool_ref=..., instance_id=...)` 返回 `CatalogTarget`：包含实际 `server_id`、原 `tool_id`、显式 `instance_id`、逻辑 `service_id`、`group_id`、`group_revision`、`schema_revision` 和 `definition_fingerprint`。`schema_revision` 是分区的完整合同指纹。逻辑引用格式为 `mcp-group:<group-id>:<partition-fingerprint>`。原 `mcp.<server-id>.<name>` 标识和 API 保持可用。

`search` 和 `describe` 交集当前用户／角色／控制权限、API token 或 OAuth 授权上限、实际实例／工具权限、逻辑服务／工具授权。逻辑服务使用现有资源授权存储中的 `server_id=mcp-group:<group-id>`，可选精确 `tool_id=tool_ref`。加入实例不产生授权。OAuth 继续授权原实际工具 ID，逻辑路由不能扩大允许列表。结构缓存不保存授权。

`open_session(actor, GroupToolSelection)` 必须显式指定 `tool_ref` 与现有 `instance_id`。返回生成的会话标识，绑定调用者的认证连接、组修订、配置摘要和当前 runtime 代际。持久化的 `default_instance_id` 仅为建议，缺少实例选择会被拒绝。路由 envelope 拒绝 endpoint、secret 和未知字段。默认实例必须已选中且可用。

统一调用入口在原调用路径外使用 `dispatch_guard(actor, GroupToolCall)`，得到 `(current_actor, target)`：

```python
with router.dispatch_guard(actor, call) as (current_actor, target):
    response = access.invoke_tool(
        registry, current_actor, target.tool_id, call.arguments,
        expected_definition_revision=target.definition_fingerprint,
        allow_read_retry=False,
    )
```

guard 持有配置和 runtime 锁直到派发完成；等待锁后重查授权，读取当前合同并要求原绑定实例。原调用路径仍负责分类、当前用户凭据、限流和实际工具审计。路由字段不加入 `arguments`。此 port 不选择其他实例、不重试写调用、不故障转移。关闭、过期、组编辑、配置变更、runtime 替换或 Gate 重启会使会话失效；调用者必须先核对结果，再显式建立新会话。会话最长一小时，每连接最多 128 个，全局最多 10,000 个。

这里实现的是实例绑定。共享下游连接和逐次调用的用户凭据传输保留原生命周期，不承诺每个逻辑会话有私有下游 MCP 会话。两次观察间相同内容的外部删除重建仍无法区分。合成 peer 验证 port 和原调用路径行为；部署、真实提供方／SSH／浏览器验收不在本开发任务内。
