# MCP 组

[English](../mcp-groups.md) · [配置](configuration.md)

本未发布切片提供管理员维护的已有 MCP 实例集合。实例 ID 仍是原 `server_id`；配置、工具、凭据、endpoint、授权和运行状态均留在实例上。一个实例可属于多个组。创建组或添加成员不授予访问权限，未分组实例保持原有行为。

在 **MCP 服务**页直接切换实例与组。创建/编辑使用居中弹窗，填写名称/说明，选择有效或已归档状态，并显式多选已有实例。成员搜索覆盖完整元数据目录；分页和搜索保留其他页的选择。每组最多 1,000 个成员，存储最多 1,000 个组。组查询只返回实例元数据，不读取全部工具 schema。名称修改不改变 ID。

归档或删除组只改变组元数据和关系，不停止、删除、重连或复制服务，不移除历史，也不改变授权。归档成员关系保留；未分组视图表示没有有效组成员关系。实例缺失或未载入时仍能看到其 ID 与名称。

已知实例删除会在运行时/文件删除前使成员关系失效；即使删除失败并补偿恢复，仍需显式确认成员。配置重载使已消失实例成为缺失成员。同 ID 实例返回不会自动恢复缺失关系。可以保留/移除成员，或取消选择后再显式选中恢复的实例。归档允许保留缺失成员。当前详情查询也会将不可用文件显示为不可用；外部文件修改与 SQLite 元数据并非单一原子存储。

## 管理 API

所有端点要求当前有效管理员、当前 `operations.manage` 权限，以及有效 Console 会话或带对应 scope 的 API token。业务 OAuth 与管理 OAuth 均不能管理组。原四个管理 MCP 工具及资源/scope 上限保持不变；本切片不新增 MCP 工具。

| 方法与路径 | 操作 |
|---|---|
| `GET /v1/mcp/groups` | 完整搜索组名称、说明或 ID；支持 `status=active/archived/all`、`q`、`offset`、`limit`（最大 100） |
| `GET /v1/mcp/groups/instances` | 完整搜索实例名称/ID 并分页；可选 `group_id` 或 `ungrouped=true` |
| `GET /v1/mcp/groups/{id}` | 读取已保存元数据、revision、成员 ID 与可用状态 |
| `POST /v1/mcp/groups/csrf` | 用 `action`、`request_digest` 和更新/删除时的组 ID 获取短期、绑定会话/请求体/方法/目标的单次票据 |
| `POST /v1/mcp/groups` | 创建明确确认的组元数据与成员关系 |
| `PUT /v1/mcp/groups/{id}` | 使用 `expected_revision` CAS 替换元数据/成员 |
| `DELETE /v1/mcp/groups/{id}` | 使用 `expected_revision` 和 `confirmed=true` 删除元数据/关系 |

创建/更新包含 `name`、`description`、`status`、不重复的 `members` ID、可选显式 `reconfirm_members` 和 `confirmed=true`。拒绝未知字段及不可用的新选/重新确认实例。浏览器写入要求严格同 Origin，并用 `X-CSRF-Token` 票据绑定键排序规范 JSON 的 SHA-256；API token 保留自身 scope 上限。更新/删除在写事务内重验当前权限。版本冲突或审计失败时，变更不生效；审计与元数据同事务提交。

Console 每次请求限时 15 秒，写入不自动重放。超时表示完成状态未确认，应先刷新保存状态再重试。错误持续可见，失败保留草稿；重读/关闭脏草稿要求明确放弃。提交期间阻止重复保存与关闭，迟到目录/详情响应不能覆盖新选择或已关闭编辑器。

## 支持边界

本切片**尚未实现**逻辑工具兼容审核、schema revision 目录、Agent 路由信封、未来实例自动授权或会话绑定。不新增同名工具聚合、endpoint 路由或跨实例重试/failover。共享下游客户端与每次新建的用户凭据客户端保持原有生命周期，不宣称浏览器会话隔离。Git transport 与隔离 worker 的 readiness 缺口保持不变。
