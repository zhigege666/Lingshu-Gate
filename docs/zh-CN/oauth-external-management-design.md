# 外部配置的管理员 OAuth

[English](../oauth-external-management-design.md) · [外部配置](external-mcp-configuration.md) · [内置 OAuth](builtin-oauth.md)

0.4.4 增加独立且默认关闭的内置 OAuth 管理资源。安装此版本不启用生产入口、不登记真实客户端或生成真实密钥，也不认证实际客户端联调。历史发行 tag 与制品保持不变。

## 明确配置与资源隔离

先为现有内置 OAuth 保存可信 HTTPS 地址、准备活动签名密钥并明确启用。在**连接基础设施**中单独启用**独立管理连接**。管理 URL 从已保存业务资源的 origin 推导为 `https://gate.example.test/mcp/manage`，路径专用资源元数据为 `/.well-known/oauth-protected-resource/mcp/manage`；它不是 OAuth 回调。启用要求当前管理员及 `operations.manage`，私有 Console 写入另有严格 Origin、有效会话 CSRF、版本 CAS 与原子脱敏审计。启用不会生成密钥或客户端。

登记或明确编辑静态客户端的允许资源：**业务 /mcp**、**管理 /mcp/manage**、**两个资源**。既有客户端迁移后仅允许业务资源。管理必须明确允许 `operations.manage`；应用、取消和远程探测还需 `tools.invoke`。业务 `tools.read`/`tools.invoke` 与管理权限分别校验。即使客户端允许两个资源，也必须分别完成精确资源授权，保持独立 grant 和刷新令牌族。

管理员通过现有授权码/S256 流程新建管理连接，明确申请精确资源和管理 scopes。公共同意页展示客户端、资源、申请 scopes、当前管理员、可同意的配置工具及逐项填写的初始目标/操作。不会从普通业务连接推导管理授权。普通 operator、外部签发方、业务 bearer、API token 和 Console Cookie 均不能认证 `/mcp/manage`。

调用路由在认证前从可信配置选择精确预期资源；JWT 声明、请求参数、Host 和转发头不能选择另一个 audience。即使 issuer/密钥/用户/客户端相同，双向跨资源访问令牌、授权码和刷新令牌也拒绝。管理验证失败不回退外部 issuer、API token 或 Cookie。关闭管理时不提供管理目录；启用后的匿名请求返回带路径专用元数据和明确管理 scopes 的 401 challenge。

普通 `/mcp` 保留业务元数据、challenge 与 scopes，拒绝 `operations.manage`。共用授权服务元数据继续只声明业务 scopes；管理资源元数据与 challenge 明确声明 `operations.manage`、`tools.invoke`。RFC 8414 允许省略部分受支持 scope 的声明，MCP 描述 challenge 优先的 scope 选择。这项实现**不能证明**实际客户端会申请管理 scope。参见 [RFC 8414 第 2 节](https://www.rfc-editor.org/rfc/rfc8414.html#section-2) 与 [MCP scope 选择](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#scope-selection-strategy)。2026-10-04 已查阅官方客户端认证/开发模式指南；实际连接、scope 请求及缓存行为仍未联调。

## 固定工具与精确目标

| 工具 | 管理 scope 上限 |
|---|---|
| `gate_mcp_config_plan` | `operations.manage`；远程探测另需 `tools.invoke` |
| `gate_mcp_config_status` | `operations.manage` |
| `gate_mcp_config_apply` | `operations.manage` + `tools.invoke` |
| `gate_mcp_config_cancel` | `operations.manage` + `tools.invoke` |

管理目录和调用只接受已同意的这四个内置工具子集，并校验当前 schema 指纹。该资源不能查看或调用业务/下游工具及其他内置工具。只有 `operations.manage` 的只读令牌族，不能通过刷新、调整目标或更宽的 grant/client 获得写权限。

目标另存为精确服务 ID 到 `create` 和/或 `update` 的映射。初始同意至少一个目标，最多 1,000 个不重复目标。ID 为 1–128 字符，符合 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`；拒绝通配符、前缀匹配、空操作及其他操作。计划在读目标配置或接触 peer 前校验实际目标和模式；状态/取消也解析并检查操作的真实目标。目标授权不提供凭据、HTTP 信任、分类发布、ZIP/Git 交付或远程执行。

## 在 Gate 确认目标变更

**我的连接 → Gate 内置 OAuth**中，有效管理授权显示**调整管理目标**，不进入业务工具范围编辑器。只读详情保留精确目标和已同意工具供历史查看。编辑器按 10 行分页保存完整目标策略，不丢弃其他页面目标；此处允许移除所有目标，使全部目标操作拒绝。

私有 Console 流程：

1. `GET /v1/auth/oauth/grants/{grant_id}/management-targets` 取得当前目标/版本和会话绑定 options 票据。
2. `POST .../management-targets/preview` 校验精确策略及两个预期版本，返回前后目标和短期确认。
3. 本人明确核对后，`POST .../management-targets` 消费最新确认、重查当前权限与绑定依赖，以 CAS 更新指定授权并增加目标/grant 版本，在同一写事务记录脱敏审计。

接口要求实际授权所有者、当前管理员、`operations.manage`、`tools.invoke`、有效私有 Console 会话及严格 Origin/会话检查。API/OAuth bearer 不能经 `/v1` 调整目标。票据绑定用户/会话、授权/客户端/资源/配置版本、当前目标/工具摘要及精确提案。确认最长十分钟、单次使用，保留既有全局/用户容量限制。过期、替换、其他会话或旧版本确认关闭式失败；审计失败连同变更和消费整体回滚。

同一管理 JWT 在下次验证请求时跟随已明确修改的 live 目标策略；旧计划失效。JWT scope、令牌族 scope、已同意工具、业务授权及其他用户授权均不扩展。未保存或待处理弹窗保护输入和键盘关闭；错误持续可见并可重新读取/核对，成功反馈短暂展示。

## 执行与恢复

每次派发及 worker 边界重新读取当前 issuer/resource、客户端、grant、刷新令牌族、管理员角色/权限、到期、目标版本和工具指纹。所需 scope 来自 JWT/client/grant/family/当前权限/委托的交集。锁等待后及文件保存、运行态应用、连接、发现前都重检；撤销或降权阻止后续副作用。

计划和幂等记录绑定已验证管理连接的 issuer/resource/client/grant/family、当前目标版本及工具快照，并保留 actor、manifest/文件/凭据/动作摘要。返回缓存完成记录前也重新检查权限；另一个连接或变化策略不能复用计划/结果绕过授权。计划和日志不持久化原始入站 bearer。

共用[外部流程](external-mcp-configuration.md)保留离线计划、明确 probe/apply/cancel、五分钟单次计划、CAS、原子完成日志、协作期限、连接所有权、秘密脱敏与中断结果核对。可使用现有托管凭据引用及已批准内网 HTTP 信任，但不会创建它们。发现变化仅隔离分类，不发布或授予业务访问。`instance_id=server_id` 仍是每目标一份配置；分组、固定目录、多实例路由与生产安全 Git 执行器不属于此变更。

关闭管理只撤销管理令牌族和待处理管理授权码，业务令牌族保留其权限。关闭或改变基础内置 issuer/resource 也会关闭管理，之后不自动重新启用。

## 验证与剩余验收

有界合成 ASGI 文件 `tests/test_oauth_management_e2e.py` 使用真实入站 authorize → consent → code/token → 管理 MCP → 确认外部配置链路、临时签名密钥及假的下游 HTTP peer。覆盖双向资源替换、普通/外部/非管理员/只读拒绝、精确目标、目标 CSRF/CAS/审计回滚、同一 JWT 目标变更、旧计划/幂等隔离、排队后撤销/到期/降权、取消及脱敏。最近一次在 180 秒命令期限内完成 19 passed，耗时 25.67 秒。后端完整测试完成 1,369 passed、三项既有 peer fixture 跳过；管理测试没有跳过。

独立构建资源浏览器测试覆盖 1600×900、1920×1080、2560×1080、2560×1440 的中英明暗布局、明确资源/scope、body 绑定 CSRF、完整 1,000 目标编辑、固定操作、键盘保护与本地校验恢复。最终受影响页面浏览器测试完成 141 passed，耗时 6.4 分钟，包含全部 40 个新增管理用例；前端单元测试完成 70 文件 / 426 tests passed。类型/源码契约检查及两套资源构建通过。这些测试使用 UI mock，不能替代 ASGI 安全测试、独立像素复核、生产 TLS 或真实客户端管理 scope 请求及缓存验收。不宣称发布、真实凭据或真实 peer 验收。
