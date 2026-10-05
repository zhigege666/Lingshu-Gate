# Lingshu Gate 0.4.4

## English — release overview

0.4.4 adds confirmed external HTTP MCP configuration through REST and four built-in management tools: `gate_mcp_config_plan`, `gate_mcp_config_apply`, `gate_mcp_config_status` and `gate_mcp_config_cancel`. The bundled Delivery Skill selects external HTTP configuration separately from ZIP delivery and the blocked Git execution path.

- Planning is offline by default. An explicit bounded probe requires its own authorization. Apply binds the exact manifest, plan digest, prior configuration digest, action choices and managed credential revisions; plans expire after five minutes and are single use. Operations retain actor ownership, revision CAS, idempotent completion, cancellation, cooperative deadlines and connection ownership checks.
- Saving, connecting and discovery have distinct results. Connection failure retains the saved configuration. Discovery quarantines new or changed tool classifications and never publishes classifications or grants access. A Gate HTTP connection does not start the remote service.
- A separate built-in `/mcp/manage` OAuth resource is disabled by default. It requires explicit administrator enablement, client resource registration, management scopes, consented configuration tools and exact server-ID/create-update targets. Business `/mcp` and external-issuer tokens cannot acquire management authority; codes and refresh families cannot cross resources.
- Private owner target changes require a live administrator Console session, strict Origin/CSRF, a reviewed single-use confirmation, revision CAS and atomic redacted audit. Current authorization is rechecked during dispatch and queued work. Changes invalidate old plans and preserve JWT/family scope ceilings and business grants.
- Console and public consent show resource, scopes, tools and exact targets. Target editors preserve pending/dirty state, errors, keyboard operation and complete target pagination. Existing one-time client-secret acknowledgement remains. Sign-in and Console show the running backend version from `/healthz`.
- The four management tools reject Console cookies at generic invocation entries; dedicated Console REST keeps Origin/session/body-bound CSRF. Credential rotation is checked after lock waits and against the encrypted record before connection/probe decryption. Memory diagnostics omit command arguments and environments. Core installs Debian's exact `perl-base` 5.36.0-7+deb12u4 security revision without vulnerability exclusions or a lower scan threshold.

Only external Streamable HTTP manifests are supported by this workflow; commands, local paths, inline secrets and permission changes are rejected. Existing credential references, exact private-HTTP service/IP/port trust, HTTPS verification and blocked redirects retain separate boundaries. File persistence, runtime state and SQLite are not one transaction; interrupted or uncertain completion requires reconciliation rather than blind write replay. Deadlines are cooperative and retain existing OS DNS/SQLite limits.

Real-client management-scope requests and real HTTP peer/deployment acceptance remain unverified. This release does not implement group routing, a large-catalog search system, DCR/CIMD or a production `SafeNetworkExecutor`. Real Git acquisition, proxy tests, tool preparation and configured network installations remain blocked. Installing or configuring the release does not enable these operations or provision credentials.

[Validation record](../docs/release-validation-0.4.4.md) distinguishes synthetic backend/browser evidence from independent visual review and real-client acceptance. The existing formal release workflow must pass before publication is accepted. It produces five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image digests and SHA256SUMS: 11 assets with provenance. Every release job, checksum, SBOM, provenance and published title/body must be read back and verified. Historical tags and artifacts remain immutable.

## 简体中文 — 版本概述

0.4.4 通过 REST 与四个内置管理工具增加外部 HTTP MCP 的确认配置流程：`gate_mcp_config_plan`、`gate_mcp_config_apply`、`gate_mcp_config_status`、`gate_mcp_config_cancel`。自带 Delivery Skill 将外部 HTTP 配置与 ZIP 交付、仍阻断的 Git 执行路径分别路由。

- 计划默认离线。明确且有界的远程探测需要独立授权。应用绑定准确 manifest、计划摘要、原配置摘要、操作选择与已有凭据版本；计划五分钟到期且只能消费一次。操作保留本人归属、版本 CAS、幂等完成、取消、协作期限及连接所有权检查。
- 保存、连接与工具发现分别反馈。连接失败保留已保存配置。发现的新工具或变化工具进入分类审核，不自动发布分类或授予访问；Gate 的 HTTP 连接不启动远端服务进程。
- 独立内置 `/mcp/manage` OAuth 资源默认关闭，要求管理员明确启用、登记客户端资源、管理 scope、已同意配置工具及精确 server ID/创建更新目标。业务 `/mcp` 与外部 issuer 令牌不能获得管理权限；授权码和刷新令牌族不能跨资源使用。
- 私有本人目标修改要求当前管理员 Console 会话、严格 Origin/CSRF、复核后的单次确认、版本 CAS 及原子脱敏审计。派发和排队执行重验当前授权；修改使旧计划失效，保留 JWT/令牌族 scope 上限及业务授权。
- Console 和公共同意展示资源、scope、工具与精确目标。目标编辑器保留 pending/未保存保护、持续错误、键盘操作及完整目标分页；一次性客户端 secret 关闭确认保持。登录页与 Console 从 `/healthz` 显示运行中的后端版本。
- 四个管理工具在通用调用入口拒绝 Console cookie，专用 Console REST 保留 Origin/会话/请求体绑定 CSRF。锁等待后重验凭据版本，连接/探测解密前与加密记录核对版本。内存诊断不读取命令参数或环境。Core 安装 Debian 准确的 `perl-base` 5.36.0-7+deb12u4 安全版本，不排除漏洞或降低扫描门槛。

本流程仅支持外部 Streamable HTTP manifest，拒绝命令、本地路径、明文 secret 和权限变更。既有凭据引用、精确内网 HTTP 服务/IP/端口信任、HTTPS 验证及禁止重定向保持独立边界。文件持久化、运行状态和 SQLite 不是单一事务；中断或完成状态不明时须核对现场，不盲目重放写入。期限为协作式，保留现有 OS DNS/SQLite 限制。

真实客户端管理 scope 请求与真实 HTTP peer/部署验收仍未验证。本版不实现分组路由、海量目录检索、DCR/CIMD 或生产 `SafeNetworkExecutor`；真实 Git 拉取、代理测试、工具准备和指定网络安装仍阻断。安装或配置本版不会启用这些操作或登记凭据。

[验证记录](../docs/zh-CN/release-validation-0.4.4.md) 区分合成后端/浏览器证据、独立视觉复核与真实客户端验收。正式发布须通过既有发行工作流，构建五种原生目标（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像摘要与 SHA256SUMS，共 11 项资产及来源证明。须回读核验全部发行任务、校验和、SBOM、来源证明和发布标题/正文；历史 tag 与制品保持不可变。
