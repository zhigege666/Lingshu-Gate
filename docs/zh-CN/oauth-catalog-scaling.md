# OAuth 目录扩展 — 开发候选

[English](../oauth-catalog-scaling.md) · [内置 OAuth](builtin-oauth.md)

本任务使用 `test/oauth-catalog-scaling-20261005`，基于 main 的 `d4786fd368e932bc758ea29da1a597c9d9551794`，不修改已完成范围选择 UI 分支，不扩大选择上限，不代表发行或客户端验收。

## 阶段 A：已保存 grant 的认证

原令牌验证先投影所有者的全部可用工具，再检查 5,000 工具目录上限，最后才与已保存 grant 求交。回归已复现：所有者新增到超过 5,000 候选后，原本有效的单工具 grant 收到 HTTP 401。

验证现只使用数据库 grant 的明确工具 ID，以一次原子注册表查询取得这些定义。当前所有者权限、已发布分类、资源、client/grant/family/JWT scope 上限及保存的快照仍是权威。缺失、未发布、变化或撤权的目标不进入 principal；已签名 JWT 的 `tools`/`tool_ids` 声明不能增加目标。存储 grant 超过 5,000 工具或 100 MCP 时，在注册表读取前即拒绝。原有刷新和期限规则保留，刷新后的 bearer 接受同样的有界验证。

单工具调用也只同步该定义，避免丢弃一个包含全部分类表的返回值；其他分类列表 API 的返回合同保持原样。`OAuthServer._grant_tools` 是共用有界投影入口。该 main 基线没有 `refresh_verified_principal`；后续已验证主体刷新路径必须复用此入口，不重新构建所有者全目录。

## 已执行的合成证据

规模及原子注册表专项共 16 项通过。假数据准确包含 5,000 个服务和 50,000 个已发布工具：在所选目标符合既有上限时签发 grant，再新增剩余目录。覆盖原 bearer 与 refresh 后 bearer、已选调用成功、未选调用拒绝、发布/权限撤回、client/family 上限、已签名工具声明伪造及存储选择限额。被测认证及调用期间禁止全注册表与全分类列表投影。既有 OAuth、实时范围、管理资源、委托权限、外部 OAuth 和访问控制回归另有 246 项通过；Ruff、mypy（116 源文件）、web 构建、源码版本及仓库标识检查均通过。

| 已保存 grant 工具数 | 每次验证读取定义数 | 全注册表投影次数 | 验证中位耗时（ms） | Refresh + 验证（ms） | 验证增量峰值（bytes） |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 7.400 | 137.953 | 19,466 |
| 100 | 100 | 0 | 9.110 | 135.054 | 406,203 |
| 5,000 | 5,000 | 0 | 205.035 | 344.464 | 21,617,711 |

以上是作者实际执行的合成测量，不是生产延迟保证。验证耗时为未开启分配跟踪的 3 次执行中位数；峰值来自另一次 `tracemalloc` 执行，排除假数据构建和已驻留的 50,000 工具注册表。刷新耗时包含签名与验证。可在源码检出中运行 `uv run pytest -q -s tests/test_oauth_catalog_scaling.py tests/test_registry_concurrency.py` 复现。

## 阶段 B：拟议最小合同，尚未实现

- 新增私有 `GET /v1/auth/oauth/grants/{grant_id}/scope-catalog`，支持有界页大小（1–100）、不透明分页游标、搜索、MCP/读写筛选及工具/MCP 整组视图。返回本页、准确匹配数量与全目录读/写/MCP 数量、稳定且绑定本人的 `catalog_revision`、后续分页游标、CSRF，以及 5,000 工具 / 100 MCP 明确选择上限。本页须标明不完整，不能作为完整目录传入现有工具选择组件。
- 增加绑定 CSRF 和该 revision 的只读选择解析，处理全部当前工具、全部当前只读及指定 MCP 整组。全局快捷选择不受列表筛选或分页影响，解析整个当前候选集合；超过任一选择上限即返回结构化限额错误，不返回部分选择。刷新不重新应用上次批选模式，不自动纳入以后新增服务。
- 另行核对草稿已选 ID，不因其不在当前页就判为不可授权。不返回当前本人不可见目标的名称或服务详情；失败保留草稿和限额。
- 小目录的旧全量 scope-options 响应保持原样。大目录必须明确采用分页能力/错误，不能给旧 UI 一个被误当成全部可授权工具的部分 `tools` 数组。保存前，将现有预览、单次确认、CAS、发布及 scope/限额复核接到同一目录 revision。

拟议传输字段保留现有 `OAuthTool` 结构和 scope-options 元信息（`csrf`、`expires_at`、`grant_revision`、`scopes`、`effective_scopes`、`family_scope_limits`）；若支持本人可见的不可授权原因，沿用既有原因代码。新增列表字段为 `view`、`items`、`next_cursor`、`catalog_revision`、`complete: false`、`matching_counts`、`catalog_counts` 和 `selection_limits`。工具项使用 `OAuthTool`；整组项包含 `server_id`、`server_name`、`tool_count`、`read_count`、`write_count`，不嵌入全量定义。数量区分工具/读/写/MCP，选择上限为 `{ "tools": 5000, "mcps": 100 }`。

拟议解析端点为 `POST /v1/auth/oauth/grants/{grant_id}/scope-selection`。请求包含 `csrf`、`expected_revision`、`catalog_revision` 和一次明确操作：`mode: "all" | "read"` 替换草稿；`mode: "groups"` 携带 `server_ids`、`checked` 和当前草稿 `tool_ids`；`mode: "ids"` 核验草稿而不替换。成功返回解析后的明确 `tool_ids`、当前已选 `tools`、带通用原因的 `unavailable_ids`、已选数量及各 MCP 已选数量。返回选择均受限；超限失败保留客户端原草稿。任何解析都不授予权限，也不保存更改。

Picker 必须接入分页适配器，不能用一页 `items` 计算全局/整组选择或可用性。刷新保留草稿 ID 并经解析器核验，只有明确批选操作才替换它们。现有预览请求增加 `catalog_revision`，保留原字段和确认返回值；预览及保存复核该 revision 以及全部当前权威和配额检查，新票据使用独立 purpose/version。Cursor 绑定 owner/session、grant/client/resource 版本、目录 revision、筛选及视图；绑定变化返回结构化冲突，不能悄悄重启。Revision/索引存储留给共用候选目录实现审查。

已完成批选 UI 接入本合同后，才能验收大目录编辑。候选索引/revision 归属及端点细节交 root 在阶段 B 实现前审定。阶段 A 不修旧交互目录硬上限或网关独立的全量 namespace 构造，它们属于后续整合。本任务未使用或验证真实 Plane 分类、真实 ChatGPT 授权/缓存行为、生产 grant、真实凭据或 SSH。
