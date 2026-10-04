# 外部 MCP 配置

[English](../external-mcp-configuration.md) · [项目交付](project-delivery.md)

此开发候选可登记现有外部 Streamable HTTP MCP，无需上传源码、构建制品或在远端启动进程。它与普通 OAuth 工具访问分开。发布与真实 peer 联调仍待独立复核。

## 选择来源

| 来源 | 路径 |
|---|---|
| 可信本地项目 | 确定性 ZIP → 上传 → 预检/构建 → 部署/启动 |
| 明确 HTTPS Git 仓库 | Git 计划/导入 → 本人 upload → 同一构建交付流程；受审查执行器仍缺失 |
| 现有 HTTP MCP 地址 | 外部配置计划 → 确认应用 → 查询操作状态 |

自带 Delivery Skill 包含三条路径。Console 配置保存与本流程复用现有 `McpConfigurationService`；新 REST/MCP 适配器共用一个 `ExternalMcpConfigurationService`。现有 Console 仅保存行为与明确连接、发现选项保持各自语义。

## 权限与输入

使用有效 Gate 管理员 Console 会话、明确 scope 的 Gate API token，或经独立同意的 `/mcp/manage` 内置管理 OAuth 连接。必须有 `operations.manage`；应用、取消、可选远程探测还必须有 `tools.invoke`。执行期间及锁等待结束后，重查当前角色权限、token/令牌族 scope、委托上限、用户状态及会话/token 有效性。管理 OAuth 另绑定精确 issuer/resource/client/grant/family、已同意工具指纹及当前精确目标/创建更新策略。普通业务 OAuth 与外部签发方 OAuth 仍拒绝。操作限定所属 actor 和 OAuth 连接；管理员角色本身不能升级 bearer。

仅接受 `launch.type=external` 与 `transport.type=streamable_http`。拒绝未知字段、命令、工作目录、挂载、构建元数据、roots、analysis 与权限修改。Header 只使用已有托管凭据引用，例如 `Bearer ${credential:example-binding}`；禁止传入秘密值。新增个人凭据槽应另行配置；更新可以保留已有声明。

新 manifest 默认 `enabled=true`、`auto_start=false`、`startup_policy=gate_start_v1`，下游超时 120 秒。启用表示允许连接，不表示已连接。未来 Gate 启动策略与本次 `connect` 独立。保留 HTTPS 验证、禁止重定向及现有地址限制。内网 HTTP 必须已有独立批准且绑定精确服务/IP/端口的信任记录；计划不能创建或扩大信任。

## 计划与应用

| MCP 工具 | REST 路由 | 用途 |
|---|---|---|
| `gate_mcp_config_plan` | `POST /v1/mcp/external-configs/plan` | 离线预检与五分钟计划；可选明确探测 |
| `gate_mcp_config_apply` | `POST /v1/mcp/external-configs/apply` | 确认准确计划，排队保存及可选连接 |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/operations/{operation_id}` | 本人操作进度及终态 |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/targets/{server_id}` | 脱敏配置及当前 Gate 连接状态 |
| `gate_mcp_config_cancel` | `POST /v1/mcp/external-configs/operations/{operation_id}/cancel` | 明确请求取消；保留已保存配置 |

Console 会话 REST 写入必须携带与 Console 完全相同的 `Origin`，拒绝 cross-site/`none` fetch，并消费绑定当前有效 Console 会话、动作路径和请求摘要的五分钟一次性 CSRF 票据。此边界复用 OAuth Console 的 Origin/会话绑定辅助函数，不依赖启用 OAuth 或生成签名 key。每次 plan/apply/cancel POST 前，携同一 Origin 获取 `POST /v1/mcp/external-configs/csrf?action=plan|apply|cancel&request_digest=...`；cancel 还需 `operation_id`。摘要是请求体按键排序、紧凑分隔符、不转义 Unicode 的 UTF-8 JSON 的 SHA-256。将返回的 `csrf` 放入 `X-CSRF-Token`。票据不可缓存、到期失效，不能重放或跨会话、动作、请求体复用。传输失败重试时获取新票据，保留原业务参数和幂等键。Gate API bearer token 仍走独立身份/scope 校验，不使用浏览器 CSRF 票据。管理 OAuth 仅通过其 MCP 资源接受，不认证这些 REST 路由；两个适配器的管理权限都由同一应用服务核验。

1. 新建选择未占用目标 ID。更新先查询目标状态，保留 `config_digest`：已保存原始文件的 SHA-256。不能用旧交付状态工具的规范化 manifest digest 替代。
2. 计划明确 `mode=create|update`、manifest，更新传 `expected_config_digest`。默认 `connect=false`、`refresh_tools=false`、`probe=false`。刷新要求连接，明确连接要求 manifest 已启用。
3. 离线预检不写文件、注册表，也不联系 peer。只有独立获准的 `probe=true,probe_confirmed=true` 使用临时会话初始化/发现并关闭；不会登记或授权工具。
4. 核对模式、目标、调用方已知地址、脱敏 manifest、摘要、旧版本、期限、超时与准确动作。更新替换当前 Gate 连接。计划返回地址/Header 掩码；更新可保留目标状态中的掩码，无需读取秘密。
5. 使用相同计划 ID/digest、动作、`confirmed=true` 和新幂等键应用。计划绑定 actor、Console 会话/API token/委托或已验证管理 OAuth 连接与目标策略版本、规范化 manifest、目标、旧文件摘要、凭据版本、动作及期限。计划只能使用一次；新建/更新在现有配置修改锁内执行 CAS。
6. 轮询直到 `terminal=true`。传输中断后保留准确参数和幂等键重试；不能再新建一次修复连接失败。输入变化需要重新核对计划与键。

连接在替换注册表前完成一次严格初始发现及分类核对。`connect=true,refresh_tools=true` 复用同一 records、快照及首次新增/变化/退役计数，不再次发送 `tools/list`，也不发布分类或扩大授权。连接及初始发现成功不能证明权限已经可用。

## 完成与恢复

应组合读取：

| 字段 | 含义 |
|---|---|
| `config_applied` / `config_digest` | 文件已保存及其版本；完成中断后为未知 |
| `connection_state` | 本次 Gate 连接、失败、清理或后继所有权 |
| `discovery_state` | 本操作实际观察的发现；目标查询返回 `not_observed` |
| `operation_id` / `terminal` | 持久操作标识及观察到的完成状态 |
| `cleanup_state` / `requires_reconciliation` | 本次是否安全断开，或需人工核查 |

终态为 `success`、`partial`、`failed`、`cancelled`、`timed_out`、`interrupted`。保存成功而连接失败属于部分完成，保留配置。查询目标后，用当前 digest 核对更新。取消是独立确认的幂等写，在排队锁及 SQLite 写事务内重查目标终态；`cancel_requested` 不等于取消完成。失败/取消只清理本次 Gate HTTP 连接，不断开后继连接、不停止远程进程；即使没有 client，也先校验操作归属。运行时应用中断保留未知连接/发现/清理及对账要求，不删除配置或授权历史，也不声称远端进程已停止。

独立管理资源默认关闭，须重新明确同意资源/scope/目标，见[管理员 OAuth 配置](oauth-external-management-design.md)。本人可在 Gate 确认精确目标变更，不改变 JWT/令牌族 scope 上限；旧计划失效，缓存完成记录、状态和取消均重查当前连接与真实目标。目标变更不能创建凭据、HTTP 信任或发布分类。真实客户端 scope 请求及真实 peer 验收仍未验证。

操作终态与幂等完成在一个 SQLite 事务中提交。重启、工作线程丢失或完成事务失败会转为 `interrupted`，状态未知且需要对账。恢复不自动重放、重连或停止。文件、HTTP 与 SQLite 仍不是分布式事务。

锁等待、HTTP 初始化/发现及刷新共享 1–120 秒单调时钟预算，另有五秒清理尝试。控制锁等待最多五秒，每进程最多四个排队操作。取消为协作方式；正在进行的 socket I/O 使用剩余期限。系统 DNS 解析和现有 SQLite busy timeout 仍有各自底层限制，不是强制杀进程保证。终态记录跟随现有幂等日志保留策略。

目前 `instance_id=server_id`，`config_revision` 是文件 digest；每目标只有一个配置，不表示分组或多实例路由。内容摘要不能区分相同字节的删除后重建。未来 generation/会话路由需要独立设计与测试。本功能没有安装 Git 执行器或远程 runtime。
