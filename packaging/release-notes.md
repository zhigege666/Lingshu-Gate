# Lingshu Gate 0.5.7

## English

0.5.7 makes MCP request timeouts easier to interpret and lets authorized callers recover eligible late stdio responses without repeating the original tool invocation.

### Changes

- Return structured `mcp_request_timeout` errors with request, dispatch and connection context. A waiting deadline is not remote cancellation or a command exit result. Timed-out operations are not automatically replayed.
- Add read-only `gate_request_status` and `POST /v1/catalog/requests/status`. An opaque recovery handle refers to the original request and can read its late JSON-RPC response when the shared stdio connection supports recovery.
- Check the exact original principal, live authority, tool revision and runtime connection before returning a retained response. Handles do not grant permissions, and another token or session cannot use a copied handle to read the result.
- Keep retained requests bounded by a 300-second lifetime, count, bytes and structural complexity. Read response pages by Unicode-character offset; reading does not extend their lifetime or dispatch another invocation.
- Distinguish waiting, completed, interrupted and unavailable request states. `completed` means that the original response arrived; it does not prove remote execution terminated, and the outer recovery result does not invent an exit code.
- Add the recovery entry to default on-demand discovery, increasing its entry count from six to seven. Full tool-list mode and existing business tool behavior are retained.
- Update paired MCP, operator, security and release documentation.

### Upgrade and compatibility

No new runtime dependency or database migration is introduced over 0.5.6. Existing configuration, data and credential directories remain in use. Preserve the normal consistent backup of data, configuration, encrypted credential stores and their keys when upgrading.

Recovery records exist only in the current Gate process and original runtime connection. A Gate restart, expired record, replaced connection or changed authorization can make the handle unavailable or interrupted; the caller must reconcile the original operation instead of treating an absent response as proof that it never ran. Existing authorization is not expanded by upgrading.

### Support and validation boundaries

This initial late-response recovery applies only to eligible shared stdio calls. HTTP calls receive structured timeout information but do not retain a late-response reader. Grouped calls, managed business-credential calls and external-provider OAuth calls are outside this initial recovery scope.

This release does not add durable SSH jobs, MCP `tasks`, remote process cancellation, cross-restart execution recovery or final command exit-code reporting. It does not claim to diagnose or speed up an underlying Git clone.

Source regression coverage includes response retention and paging, identity and authorization changes, connection replacement, HTTP timeout context, protocol behavior, runtime bounds and secret-safe error handling. Formal release publication separately requires all four quality shards, five native packages, Compose, two offline Core images, application SBOM, exact container reference, aggregate checksums and provenance verification. A tag or a partially completed workflow is not a finished release.

See [on-demand request recovery](../docs/on-demand-tools.md), [MCP gateway](../docs/mcp-gateway.md), [security](../SECURITY.md) and [release verification](../docs/releases.md).

## 简体中文

0.5.7 明确 MCP 请求超时的含义，并允许有权调用者读取符合条件的 stdio 迟到响应，减少因回包缺失而重复执行原工具的风险。

### 变更

- 返回结构化 `mcp_request_timeout`，提供请求、派发及连接上下文。等待到期不代表远端取消或命令退出，超时操作不会自动重放。
- 增加只读 `gate_request_status` 与 `POST /v1/catalog/requests/status`。不透明恢复句柄指向原请求；共享 stdio 连接支持恢复时，可读取原 JSON-RPC 迟到响应。
- 返回响应前核对原身份、当前权限、工具修订及运行时连接。句柄不授予权限，另一个 Token 或会话不能通过复制句柄读取结果。
- 按 300 秒存留期限、数量、字节和结构复杂度限制保留内容。按 Unicode 字符偏移分页读取，读取不延长期限，也不重新派发调用。
- 区分 waiting、completed、interrupted 与 unavailable 请求状态。`completed` 只代表原响应到达，不证明远端执行已终止；外层回读结果不伪造退出码。
- 按需发现模式增加恢复入口，默认入口由六个增至七个。完整工具列表模式及既有业务工具行为保持不变。
- 同步中英文 MCP、操作、安全及发行文档。

### 升级与兼容

相对 0.5.6 不新增运行依赖或数据库迁移，继续使用既有配置、数据及凭据目录。升级时沿用数据、配置、加密凭据存储和全部密钥的一致备份要求。

恢复记录仅存在于当前 Gate 进程及原运行时连接中。Gate 重启、记录过期、连接替换或授权变化后，句柄可能 unavailable 或 interrupted；调用方应核对原操作，不能根据缺少回包推断它从未执行。升级不扩大既有授权。

### 支持与验证边界

第一批迟到响应回读仅适用于符合条件的共享 stdio 调用。HTTP 调用增加结构化超时信息，但不保留迟到响应读取器；分组、托管业务凭据及外部提供方 OAuth 调用暂不在回读范围内。

本版不增加持久 SSH 任务、MCP `tasks`、远端进程取消、跨重启执行恢复或最终命令退出码，也不宣称已经定位或加速底层 Git 克隆。

源码回归覆盖响应保留与分页、身份和授权变化、连接替换、HTTP 超时上下文、协议行为、运行时上限与错误脱敏。正式发布另需四个质量分片、五个平台原生包、Compose、两个离线 Core 镜像、应用 SBOM、精确容器引用、总校验和及来源证明全部通过。标签或部分流水线成功不代表完整发布。

参见[按需请求回读](../docs/zh-CN/on-demand-tools.md)、[MCP 网关](../docs/zh-CN/mcp-gateway.md)、[安全说明](../SECURITY.zh-CN.md)及[发行验证](../docs/zh-CN/releases.md)。
