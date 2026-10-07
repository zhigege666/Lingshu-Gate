# MCP 分组路由适配接口

[English](../mcp-group-routing-contract.md) · [分组](mcp-groups.md)

实例选择复用原 manifest ID 合同，允许 `_`、`-`、`.` 开头，不新增 128 字符路由限制，也不重命名既有实例；原 manifest、文件系统与请求预算继续生效。斜杠、URL 与未知路由字段仍被拒绝。

外部 OAuth 在锁等待后重新检查完整配置有效性、启用状态、client allowlist、issuer/JWKS 绑定、每个已验证 audience 的 canonical-resource 映射、subject link、过期时间及 grant。认证主体和调用上下文仅携带签名验证后的非秘密 audience/resource/JWKS 证明，适配器必须保留；路由参数不能提供或替换它，缺少证明时拒绝。

共享运行连接使用每个 runtime 的新 epoch 和单调 generation；替换/清空客户端及每次共享 connect/reconnect 尝试（含失败和恢复）均推进 generation，不再从对象地址、时间戳或下游 SID 推导连续性。复用 SID 或 A→B→A 恢复旧客户端不能复活旧路由会话；派发期间 generation 变化也使 guard 失败，必须先对账再显式打开新会话。

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

guard 持有配置/runtime-map 共享租约及所选实例锁直到派发完成；不同实例可以并发，配置/组修改与 runtime-map 变更使用独占租约等待在途调用。已有持有者可以嵌套读取，等待写入期间也不会死锁；读租约升级为写入会失败关闭。租约/实例锁等待后重查授权，读取当前合同并要求原绑定实例。原调用路径仍负责分类、当前用户凭据、限流和实际工具审计。路由字段不加入 `arguments`。此 port 不选择其他实例、不重试写调用、不故障转移。关闭、过期、组编辑、配置变更、runtime 替换或 Gate 重启会使会话失效；调用者必须先核对结果，再显式建立新会话。会话最长一小时，每连接最多 128 个，全局最多 10,000 个。

这里实现的是实例绑定。共享下游连接和逐次调用的用户凭据传输保留原生命周期，不承诺每个逻辑会话有私有下游 MCP 会话。两次观察间相同内容的外部删除重建仍无法区分。合成 peer 验证 port 和原调用路径行为；部署、真实提供方／SSH／浏览器验收不在本开发任务内。
