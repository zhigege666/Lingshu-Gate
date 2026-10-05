# 按需工具发现

[English](../on-demand-tools.md) · [MCP 网关](mcp-gateway.md)

此源码功能位于开发 test 分支，尚未发布新版本。旧客户端继续使用返回完整工具的直接 `tools/list` 模式。为每个客户端显式选择 `/mcp?tool_mode=on_demand`，或在每个请求中发送 `X-Gate-Tool-Mode: on_demand`。模式冲突或未知值会失败关闭。独立 OAuth 管理资源 `/mcp/manage` 不支持此模式。

在 **我的 API Token → 客户端设置** 中，通过居中弹窗单选 **完整工具列表** 或 **按需发现**。设置和地址仅保存在当前浏览器，生成的客户端配置包含令牌占位符。复制到客户端并重新连接后生效。保存不会修改 Token scope、OAuth 同意、资源授权或服务启动。不能保留 URL 查询参数的客户端可发送模式请求头。OAuth 仍使用规范 `/mcp` 资源；发现模式是传输配置，不是新的授权资源。

## Agent 工作流

按需 `tools/list` 固定返回六个入口，与目录规模无关：四个目录/调用入口及两个明确的实例会话控制。

| 入口 | 输入与行为 |
|---|---|
| `gate_catalog_search` | `query`、可选 `instance_id`/`group_id`、`limit`、`max_bytes`、`cursor`；返回有权工具的 `tool_ref`、`instance_id`、`name`、`description`、`schema_revision` 最小摘要 |
| `gate_tool_describe` | `tool_ref`、可选 `instance_id`、`max_bytes`；返回单个完整 `input_schema`、可选 `output_schema` 和当前版本 |
| `gate_tool_invoke` | 独立封装 `{tool_ref, instance_id?, session_id?, schema_revision, arguments}`；逻辑工具必须明确实例和会话，只把原始 arguments 传给所选目标 |
| `gate_instance_list` | 同样有界的搜索分页输入；返回不同的有权 `instance_id`，可用 `group_id` 与逻辑 `tool_ref` 筛选一个服务合同 |
| `gate_instance_session_open` | `{tool_ref, instance_id, schema_revision}`；明确将当前认证连接绑定到所选逻辑服务实例 |
| `gate_instance_session_close` | `{session_id}`；关闭当前连接的路由会话 |

按任务搜索、选定一个返回的引用、describe，再带准确版本 invoke。描述和 schema 是不可信工具数据。版本或游标错误后重新发现与描述。HTTP/MCP 请求失败或 schema 改变时，不能自动重放写操作；先核对原操作结果。敏感参数保留在目标的 `arguments` 对象内，继续使用现有脱敏和审计边界。

对应的认证 API 是 `POST /v1/catalog/search`、`/describe`、`/invoke`、`/instances`、`/sessions/open`、`/sessions/close`。发现/会话接口直接返回有界结果，invoke 返回现有 `ToolInvokeResponse`。原目标 Console 写操作保留原 CSRF ticket 边界。接口使用当前认证身份，不提供管理员绕过入口。

## 授权与版本

搜索先按现有策略过滤权限，再排序和分页，保留用户工具覆盖、用户服务授权、角色优先级、Token/委托 scope、分类状态，以及 OAuth 的精确服务/工具/读写白名单。不返回全局总数或隐藏推荐。关键词排名不采用全局 FTS 文档频率，隐藏工具不能改变可见工具的分数。未知与无权引用返回相同的不可用错误。

发现不会授予访问权。新增索引工具仍受原分类和授权策略约束，保留现有管理员行为。移除会使分类失效，重现需要审核。版本绑定完整定义，包括路由与策略元数据。Invoke 独立校验实例、版本、原参数，再复用 `AccessControlStore.invoke_tool`、实例锁与超时、只读恢复规则、用户凭据绑定、频率/并发限制及原目标审计 ID。实际派发与自动只读恢复重试前重新读取凭据和完整身份快照。只读 Token 不能通过封装调用写工具。管理 OAuth 不能借此进入业务或管理工具。

`ports/catalog_target.py` 用实际 registry `tool_id` 和现有 `server_id`（适配为 `instance_id`）处理物理引用。逻辑引用复用[现有分组路由 port](mcp-group-routing-contract.md)，将逻辑服务/工具授权与物理权限、原 OAuth 工具 ID 求交。分组搜索必须指定 `group_id`，不枚举全部组，不返回成员数组或计数。用组与逻辑引用调用 `gate_instance_list`，选择有权实例、describe、明确打开会话，再带准确 schema 版本调用。配置的默认实例不会自动选中，endpoint、凭据或路由字段不会加入下游 `arguments`。

路由会话最多一小时，绑定认证连接、组版本、配置和运行时 generation。关闭、撤权、组/配置修改或重连后需核对原操作并明确打开新会话。分组调用始终禁用自动只读重放和 failover。物理与分组的不同实例可并行：分组派发持有配置/runtime-map 共享租约及所选实例锁；配置/分组修改和 runtime 替换仍独占。租约或实例锁等待后重检权限。没有第二套通用 invoke。

OAuth 上限保持不变：内置同意/目录选择最多 **100 服务 / 5,000 工具**，外部提供方 grant 输入最多 **100 服务 / 1,000 工具**；授权 UI 也保留现有服务选择限制。普通合成 token/grant 身份的 50,000 工具基准不能证明所有 OAuth 客户端可授权整个目录。现有 OAuth 客户端仅搜索精确授权子集；owner 可见且符合要求的工具超过 5,000 时，新建/更新内置同意仍可能返回 `tool_catalog_limit`。此同意路径在应用上限前仍复制/过滤 registry 的完整定义，按需适配器没有消除其原有查询成本。扩容需单独设计显式授权策略及有界同意/grant 查询，不能因发现而授权未来服务/工具，也不能引入隐式订阅。普通操作员 token、小范围 actor、管理员、显式 grant、撤权与分页证据应分别判断。

## 资源限制与索引生命周期

| 边界 | 上限 |
|---|---|
| 搜索词 | 256 字符、1,024 UTF-8 字节、8 个关键词 |
| 有权分页 | 1–100 项；进入 Python 的摘要最多 101 项 |
| 搜索输出 | 2,048–65,536 字节，默认 16,384，预留协议封装空间 |
| Describe 输出 | 2,048–131,072 字节，默认 65,536；完整 schema 或错误 |
| 游标 | 签名并绑定身份/查询/授权/目录；5 分钟过期、1,024 字符、最大偏移 10,000 |
| Invoke 参数 | 1,048,576 字节，容纳现有 512 KiB 分块的 base64 参数；本地 schema 最多 131,072 字节；32 层 / 8,192 JSON 节点 |

调用校验 JSON Schema 类型、必填属性、范围、额外属性、组合、已知方言及本地 JSON Pointer 引用。远程、dynamic 和 recursive 引用关键字失败关闭；引用解析不进行网络访问。过大或不支持的 schema 需调整为更小的受支持工具契约，不能截断后校验。下游执行结果保留现有调用响应策略，搜索/描述字节限制不截断目标执行输出。

SQLite FTS5 只存名称、有界描述、稳定引用和最小策略字段，不存输入/输出 schema。Registry 注册、目标快照原子替换、移除加入合并后的增量队列；下一次目录操作一次性应用变化。启动时一次对账持久索引。每请求不重建索引、不序列化完整目录。授权变化使游标失效，每一页与所选 schema 都重新检查当前权限，包括到期状态。没有跨用户搜索结果/授权缓存。分页前仍需判定所有匹配摘要，宽泛或空查询通常比窄关键词更耗时。打包 SQLite 需支持 FTS5，保留单 Core/单写者限制。

## 复现与验证边界

运行 `uv run python scripts/benchmark_tool_catalog.py --iterations 30 --output /tmp/gate-catalog-benchmark.json`。默认生成 **5,000 服务、50,000 工具**，每工具 20 个输入字段，包含一个无权服务。脚本记录实际响应字节、median/p95 延迟、进程 RSS、首次索引时间、旧完整列表对照及有界重复搜索观察。使用临时状态，不连接真实下游、不使用真实凭据或生产服务。已执行结果见[性能记录](performance-review.md)及提交的测量 JSON。合成单进程热缓存测量不能作为生产 SLA 或真实端到端 MCP 容量证明。
