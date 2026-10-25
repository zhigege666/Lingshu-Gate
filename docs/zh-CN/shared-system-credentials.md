# 共享服务凭据

[English](../shared-system-credentials.md) · [HTTP MCP 管理](external-mcp-configuration.md)

共享凭据可通过 Console、私有凭据 REST API 或五个管理员 MCP 工具管理，仍加密保存。读取、成功写入、校验错误、操作回执、日志及可选调用内容记录均不返回已保存明文。Manifest 使用 `${credential:<id>}` 引用。本流程与个人下游绑定、业务账号密码库分别管理。

## 工具与权限

| 工具 | 必需输入 | 结果 |
|---|---|---|
| `gate_credential_list` | 无 | 当前有权查看的脱敏元数据 |
| `gate_credential_get` | `credential_id` | 脱敏元数据及当前 `updated_at` 版本 |
| `gate_credential_create` | `name`、`value`、`idempotency_key`；可选明确 ID、说明及 HTTP 范围 | 新建加密记录；同 ID 已存在时失败，不覆盖 |
| `gate_credential_update` | ID、`expected_revision`、幂等键及变更字段 | 校验版本后修改元数据、轮换值或调整范围 |
| `gate_credential_delete` | ID、`expected_revision`、幂等键 | 实时依赖检查通过后删除 |

有效管理员需要 `credentials.manage.system`，写入另需 `tools.invoke`。API token 和委托上限继续生效，已明确授权的通配 scope 保留原含义。普通业务 OAuth 不能调用这些工具。内置管理 OAuth 还要求 `operations.manage`、明确申请并同意的 `credentials.manage.system` scope、选定凭据工具指纹，以及精确凭据目标操作：`credential.read`、`credential.create`、`credential.update`、`credential.delete`。服务的 `create`、`delete` 等操作不会授权同 ID 凭据。旧 grant 和令牌族升级后不会自动扩大。

管理某个凭据的权限包含其完整 `http_scopes` 元数据，以及对这些精确用途的批准。它不会授予所列服务的配置、连接或工具调用权限；这些操作仍需各自的服务权限。连接和依赖明细另按当前可见权限过滤。

Console 会话使用专用 `/v1/credentials` 路由，通用 MCP/注册表凭据调用拒绝会话身份。配置编辑器支持内联创建凭据，保留 HTTP 配置草稿，完成后只插入凭据引用。独立凭据页面继续提供查看、轮换和删除。

## 版本与重试

先读取当前 `updated_at`，更新/删除时作为 `expected_revision` 提交。版本过期会失败，不能静默覆盖新值。省略 `value` 或传 `null` 保留原秘密；掩码 `***` 不能作为替换值。轮换时使用新幂等键提交真实新值。

MCP 写入必须有幂等键。同一身份连接、参数和键的准确重试，在重新校验当前权限后返回原脱敏完成记录。相同键配不同参数会冲突。日志使用带密钥的请求指纹，不保存秘密原文或可直接猜测秘密的普通哈希。完成状态丢失时明确返回 pending/interrupted 并要求核对，不猜测写入是否发生后自动重复。

REST 保留原有列表/详情/创建/更新/删除路由形式。更新在 JSON 体传 `expected_revision`，删除在查询参数传该字段。建议明确传 `idempotency_key`，Console 已使用；省略键的旧 REST 请求每次取得新的内部键，不具备传输重试保证。JSON 解析和模型错误不反射被拒绝的值，凭据响应使用 `Cache-Control: no-store`。

## 精确 HTTP 使用范围

HTTP 使用必须在 `http_scopes` 中明确声明，例如：

```json
{
  "server_id": "example-http",
  "origin": "http://10.10.0.23:4747",
  "server_binding": null
}
```

Origin 仅含协议、主机和端口；MCP 路径保留在服务 manifest 中。已绑定范围使用服务当前的 `server_binding`。null 表示 pending，也适用于尚未保存这项用途的已有服务；只有下一次匹配的配置保存才能消费，单凭 pending 不能连接。变更 origin 或删除后重建服务，不继承旧范围；需要明确增加或复核新范围。范围缺失、不匹配或已撤销时，发送凭据前即拒绝。

旧凭据仅迁移一次，只绑定当前已保存、有效的 HTTP 消费者及其生命周期身份。孤立凭据不会获得未来服务通配权限。Git 认证、构建环境及代理仍遵循其原凭据语义，HTTP 限制不重新定义这些消费者。

## 轮换、删除与结果

既有 HTTP 客户端在派发时重新解析当前有权 Header，不再长期缓存旧值。完成轮换后，后续派发使用新值；已经派发的请求不会被追回。保存成功不能证明下游接受新凭据。结果分别报告 `value_saved`、受影响连接、`refresh_on_next_dispatch` 及 `connection_verified=false`，下游验证需另行连接或执行有权检查。

删除检查已保存配置、Git/构建引用、代理修订及网络默认值。仍被引用时返回 `credential_in_use`；先解除依赖，再读取当前版本并用新键重试。删除外部 MCP 配置会保留共享凭据。依赖和连接明细按调用者当前可见权限返回，必要时提供隐藏数量。

加密文件与 SQLite 操作/审计状态不是一个事务。收到中断结果后，先读取脱敏元数据和相关配置，再决定新写入。备份时同时保存加密存储、密钥、Gate 数据库和配置；MCP/REST 不提供明文恢复。
