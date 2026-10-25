# 外部 MCP 配置

[English](../external-mcp-configuration.md) · [项目交付](project-delivery.md)

此流程管理现有外部 Streamable HTTP MCP，无需上传源码、构建制品或在远端启动进程。0.5.6 支持通过 MCP 物理删除配置、管理精确内网 HTTP 连接许可，并提供独立权限的[共享凭据管理](shared-system-credentials.md)。部署和真实 peer 验收与源码、合成测试完成分别记录。

## 选择来源

| 来源 | 路径 |
|---|---|
| 可信本地项目 | 确定性 ZIP → 上传 → 预检/构建 → 部署/启动 |
| 明确 HTTPS Git 仓库 | Git 计划/导入 → 本人 upload → 同一构建交付流程；受审查执行器仍缺失 |
| 现有 HTTP MCP 地址 | HTTP 管理计划 → 确认应用 → 查询操作状态 |

自带 Delivery Skill 包含三条路径。Console 配置保存与本流程复用现有 `McpConfigurationService`；新 REST/MCP 适配器共用一个 `ExternalMcpConfigurationService`。现有 Console 仅保存行为与明确连接、发现选项保持各自语义。

## 推荐的 HTTP 管理工具

| 工具 | 用途 |
|---|---|
| `gate_http_mcp_test` | 使用临时连接检查 HTTP、鉴权、MCP 握手与工具发现；不保存、不授予许可、不发布工具。 |
| `gate_http_mcp_plan` | 离线审核 `create`、`update`、`delete`、`revoke_trust`、`restore_trust`；不联系目标地址 |
| `gate_http_mcp_apply` | 以 `confirmed=true` 和幂等键应用准确的已审核计划 |
| `gate_http_mcp_status` | 查询有权目标或本人操作，包括保存状态和连接结果 |
| `gate_http_mcp_cancel` | 请求取消；结果仍明确显示已经持久化的变更 |

计划、应用、状态和取消工具复用现有操作引擎、有界队列和持久日志；独立联通测试使用临时客户端，不写持久化操作记录。新工具不扩展四个旧 `gate_mcp_config_*` 工具的 schema 或指纹。管理员 API token 保持原 scope 上限。管理 OAuth 必须明确同意新工具和精确目标操作；升级服务、刷新 token 或扩大客户端 scopes 都不会自动扩大旧 grant 或令牌族。

计划/状态要求 `operations.manage`，应用/取消另需 `tools.invoke`，并校验当前有效管理员。创建/更新传 `manifest`，删除/撤销/恢复改传 `server_id`。除创建外均要求当前原始配置文件的 `expected_config_digest`。`connect`、`refresh_tools` 默认 false，刷新要求连接，删除/撤销不能连接。计划五分钟到期，并绑定目标生命周期、配置摘要、trust 版本、凭据版本、actor/连接及准确动作；应用携带计划 ID/摘要和相同的连接/刷新选项。

内网 HTTP 创建/更新的计划会展示精确服务 ID、规范 RFC1918 IPv4 和端口。一次有权应用共同保存配置与连接许可。Console 保存复用同一策略，以地址摘要替代独立的“授权此地址”步骤。静态预检查不写许可、不访问 peer。HTTPS、规范回环行为、禁止重定向和正常 TLS 校验继续生效；不增加任意 URL 的 HTTP 请求工具。

撤销会持久保存。普通更新、重连和自动启动不能恢复许可；核对当前精确地址后，应明确使用 `restore_trust` 计划或 Console 恢复动作。许可绑定 `server_binding`，不只绑定可复用的服务 ID。旧许可只对当前已保存且匹配的服务迁移一次，其他记录需要复核。保存前的许可处于 pending，必须保存匹配配置后才能连接。删除服务会清理许可；同名重建必须通过新的有权创建，不能继承上一实例的许可。

删除计划展示受影响的工具、分组及个人下游绑定；应用复用配置/运行态清理流程，删除外部配置文件、当前目录和分组成员关系，并使旧身份失效。共享凭据与审计历史保留；不会卸载或停止远端 MCP 进程。共享凭据需先解除引用，再单独明确删除。

HTTP 计划不接收凭据原文。先以独立权限创建或更新凭据，再在 manifest 使用 `${credential:example-binding}`。HTTP 使用范围必须匹配服务、origin 与生命周期；pending 范围可由首次匹配保存消费。只写入原文、版本校验和轮换结果见[共享服务凭据](shared-system-credentials.md)。

## 旧工具的权限与输入

以下合同继续服务已有 `gate_mcp_config_*` 客户端及其 REST 适配器，仅创建/更新并保留已有内网 HTTP 许可。合并许可、撤销/恢复及物理删除使用上方新工具。

使用有效 Gate 管理员 Console 会话、明确 scope 的 Gate API token，或经独立同意的 `/mcp/manage` 内置管理 OAuth 连接。必须有 `operations.manage`；应用、取消、可选远程探测还必须有 `tools.invoke`。执行期间及锁等待结束后，重查当前角色权限、token/令牌族 scope、委托上限、用户状态及会话/token 有效性。管理 OAuth 另绑定精确 issuer/resource/client/grant/family、已同意工具指纹及当前精确目标/创建更新策略。普通业务 OAuth 与外部签发方 OAuth 仍拒绝。操作限定所属 actor 和 OAuth 连接；管理员角色本身不能升级 bearer。

仅接受 `launch.type=external` 与 `transport.type=streamable_http`。拒绝未知字段、命令、工作目录、挂载、构建元数据、roots、analysis 与权限修改。Header 只使用已有托管凭据引用，例如 `Bearer ${credential:example-binding}`；禁止传入秘密值。新增个人凭据槽应另行配置；更新可以保留已有声明。

新 manifest 默认 `enabled=true`、`auto_start=true`、`startup_policy=gate_start_v1`，下游超时 120 秒。明确指定的 `auto_start=false` 或 `startup_policy=legacy_restore` 会保留。启用表示允许连接，不表示已连接。未来 Gate 启动策略与本次 `connect` 独立。保留 HTTPS 验证、禁止重定向及现有地址限制。内网 HTTP 必须已有独立批准且绑定精确服务/IP/端口的信任记录；计划不能创建或扩大信任。

## 旧工具的计划与应用

| MCP 工具 | REST 路由 | 用途 |
|---|---|---|
| `gate_mcp_config_plan` | `POST /v1/mcp/external-configs/plan` | 离线预检与五分钟计划；可选明确探测 |
| `gate_mcp_config_apply` | `POST /v1/mcp/external-configs/apply` | 确认准确计划，排队保存及可选连接 |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/operations/{operation_id}` | 本人操作进度及终态 |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/targets/{server_id}` | 脱敏配置及当前 Gate 连接状态 |
| `gate_mcp_config_cancel` | `POST /v1/mcp/external-configs/operations/{operation_id}/cancel` | 明确请求取消；保留已保存配置 |

Console 会话 REST 写入必须携带与 Console 完全相同的 `Origin`，拒绝 cross-site/`none` fetch，并消费绑定当前有效 Console 会话、动作路径和请求摘要的五分钟一次性 CSRF 票据。此边界复用 OAuth Console 的 Origin/会话绑定辅助函数，不依赖启用 OAuth 或生成签名 key。每次 plan/apply/cancel POST 前，携同一 Origin 获取 `POST /v1/mcp/external-configs/csrf?action=plan|apply|cancel&request_digest=...`；cancel 还需 `operation_id`。摘要是请求体按键排序、紧凑分隔符、不转义 Unicode 的 UTF-8 JSON 的 SHA-256。将返回的 `csrf` 放入 `X-CSRF-Token`。票据不可缓存、到期失效，不能重放或跨会话、动作、请求体复用。传输失败重试时获取新票据，保留原业务参数和幂等键。Gate API bearer token 仍走独立身份/scope 校验，不使用浏览器 CSRF 票据。管理 OAuth 仅通过其 MCP 资源接受，不认证这些 REST 路由；两个适配器的管理权限都由同一应用服务核验。

Console cookie 不能通过 `/v1/tools/{id}/invoke`、`/v1/invoke`、`/mcp` 或其他通用注册表入口调用这四个管理工具；计划/状态和应用/取消均如此。Console 会话使用上述专用路由；普通工具和带 scope 的 API token 保留既有通用入口。

运行时/目标锁等待后及目录替换前再次核验凭据版本。连接/探测读取时，解密前与同一加密记录中的批准版本核对。绑定变化返回 `external_config_credential_changed`；若已持久化则保留配置。重新核对计划，不能用旧确认消费轮换后的值。

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

独立管理资源默认关闭，须明确同意资源/scope/工具/目标，见[管理员 OAuth 配置](oauth-external-management-design.md)。本人可在 Gate 确认精确目标变更，不改变 JWT/令牌族 scope 上限；旧计划失效，缓存完成记录、状态和取消均重查当前连接与真实目标。单独调整目标不能增加工具或 scopes。凭据操作另需 `credentials.manage.system` 和对应的已同意工具；发现工具不自动发布分类或授予业务访问。

操作终态与幂等完成在一个 SQLite 事务中提交。重启、工作线程丢失或完成事务失败会转为 `interrupted`，状态未知且需要对账。恢复不自动重放、重连或停止。文件、HTTP 与 SQLite 仍不是分布式事务。

锁等待、HTTP 初始化/发现及刷新共享 1–120 秒单调时钟预算，另有五秒清理尝试。控制锁等待最多五秒，每进程最多四个排队操作。取消为协作方式；正在进行的 socket I/O 使用剩余期限。系统 DNS 解析和现有 SQLite busy timeout 仍有各自底层限制，不是强制杀进程保证。终态记录跟随现有幂等日志保留策略。

目前 `instance_id=server_id`，`config_revision` 是文件 digest，每目标仍只有一份配置。HTTP 许可与凭据使用另绑定生命周期 `server_binding`，相同配置字节不能恢复上一实例的权限。这不增加多实例路由或远程 runtime。配置文件、trust、凭据和操作日志不组成分布式事务；部分成功或中断后，需结合 `config_applied`、`trust_applied`、`requires_reconciliation` 和连接/发现字段判断结果。


## 独立联通测试

`gate_http_mcp_test` 不进入上述持久化操作日志，不创建计划或长期连接。需要明确的 `confirmed=true`；管理 OAuth 需要新工具及精确目标 `test` 动作。当前 Console 在配置弹窗中提供“测试联通”，与静态校验及保存分离。字段、结果语义、凭据使用范围和 Home 接入示例见[联通测试指南](http-mcp-connection-testing.md)。
