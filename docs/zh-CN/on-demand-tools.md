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

OAuth 上限保持不变：内置 grant 最多 **100 服务 / 5,000 工具**，外部提供方 grant 输入最多 **100 服务 / 1,000 工具**。OAuth 阶段 A 修复 `dfa18dde3169df173be72400054c4d567dc2cb1b` 已复制为 `1b4592d`：验证、token refresh 与进程内 verified-principal refresh 仅查询数据库 grant 的显式 IDs，既有小 grant 不再依赖 owner 全 eligible 目录。请求定义从 registry 持有的快照原子复制；JWT claims 或新发现工具均不扩展 grant。旧全目录同意/选择路径仍保留原上限，owner 候选分页是待集成的独立阶段。单凭 50,000 工具 operator 目录基准不能证明 OAuth 可用性。普通 token、OAuth、小范围 actor、管理员、显式 grant、撤权及分页证据需分别判断；未来服务/工具仍需显式授权。

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

验证位于原权限、速率及并发准入之后，配置、运行时映射和实例派发租约之前。本地引用 DAG 的展开预算为 8,192，schema 与参数的工作预算为 262,144；循环引用失败关闭。获准验证在一次性子进程中执行，墙钟期限两秒，每个 Gate 进程最多四个并发验证器；Linux 另有限制 CPU 时间和 512 MiB 地址空间。超时或取消会终止并回收子进程，使昂贵正则与 schema 求值受限；并非承诺支持所有有效 JSON Schema。验证失败不会调用下游，只记录一条 `not_invoked` 审计。未知或未解析引用记录带关联标识及引用哈希的事件，不记录私有名称或参数值。公共 describe 在返回 schema 前复核目录与策略标记，并发变化返回 `catalog_changed`；管理面分组目录保留已有文档约定的快照语义。

SQLite FTS5 只存名称、有界描述、稳定引用和最小策略字段，不存输入/输出 schema。Registry 注册、目标快照原子替换、移除加入合并后的增量队列；下一次目录操作一次性应用变化。启动时一次对账持久索引。每请求不重建索引、不序列化完整目录。授权变化使游标失效，每一页与所选 schema 都重新检查当前权限，包括到期状态。没有跨用户搜索结果/授权缓存。分页前仍需判定所有匹配摘要，宽泛或空查询通常比窄关键词更耗时。打包 SQLite 需支持 FTS5，保留单 Core/单写者限制。

## 复现与验证边界

运行 `uv run python scripts/benchmark_tool_catalog.py --iterations 30 --output /tmp/gate-catalog-benchmark.json`。默认生成 **5,000 服务、50,000 工具**，每工具 20 个输入字段，包含一个无权服务。脚本记录实际响应字节、median/p95 延迟、进程 RSS、首次索引时间、旧完整列表对照及有界重复搜索观察。使用临时状态，不连接真实下游、不使用真实凭据或生产服务。已执行结果见[性能记录](performance-review.md)及提交的测量 JSON。合成单进程热缓存测量不能作为生产 SLA 或真实端到端 MCP 容量证明。

`uv run python scripts/benchmark_group_catalog.py --iterations 30 --output /tmp/gate-group-benchmark.json` 单独验证 1,000 成员、50,000 工具的分组，每工具一个输入字段，满足原有 32 MiB 结构上限。实测冷/暖分组搜索、小范围 actor、选定实例描述、公共 API 搜索及公共 MCP 描述/调用，并断言真实物理审计及未选中 peer 零调用。仅结构契约缓存，授权不缓存；搜索先求交当前物理与逻辑策略，再排序分页。schema 准备前排除无物理授权候选，每页仅构建一次授权投影。选定描述/调用仅重新校验单条成员记录及该实例工具，避免反复投影整组。全组搜索仍比物理 FTS 索引和选定操作昂贵。合成 token/session、echo peer 与子进程数据不能证明真实提供方 OAuth 或下游延迟。
