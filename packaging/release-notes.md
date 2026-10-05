# Lingshu Gate 0.4.4

## English — release overview

Development source addition, not part of the published 0.4.4 assets: per-client on-demand tool discovery exposes six bounded MCP discovery/session entries and matching catalog APIs. It uses an incremental SQLite FTS directory, existing permission evaluation and real-target invocation audit, revision/parameter/instance checks and credential revalidation before dispatch. Console offers a local client-mode dialog, and the Delivery Skill preserves its original confirmations and digests through the invoke envelope. Synthetic 5,000-service/50,000-tool regression/benchmark evidence and remaining real-client/session-isolation limits are documented in [on-demand tools](../docs/on-demand-tools.md).

The development integration adds explicit grouped-instance sessions, shared read leases for parallel instances, bounded killable schema validation and deidentified rejection audit. Saved built-in OAuth grants are revalidated against their explicit IDs instead of the owner's entire directory; selection ceilings remain unchanged. Exact copied commits and integration evidence are in [provenance](../docs/on-demand-integration.md). No release assets or tags were published by this source work.

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

开发源码补充，未包含在已发布的 0.4.4 制品中：每客户端按需发现通过六个有界 MCP 发现/会话入口及对应目录 API 提供工具访问，使用 SQLite FTS 增量目录、原权限判定及实际目标调用审计、版本/参数/实例校验和派发前凭据复核。Console 提供本地客户端模式弹窗；Delivery Skill 通过 invoke 封装保留原确认及摘要。5,000 服务/50,000 工具合成回归与基准证据，以及真实客户端/会话隔离的剩余边界，见[按需工具指南](../docs/zh-CN/on-demand-tools.md)。

开发集成另加显式分组实例会话、允许实例并发的共享读租约、有界且可终止的 schema 验证，以及脱敏拒绝审计。内置 OAuth 既有 grant 根据其显式 IDs 重新校验，不重建 owner 全目录；选择上限保持。精确复制提交与集成证据见[溯源](../docs/zh-CN/on-demand-integration.md)。此次源码工作未发布 release 制品或 tag。

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

## Pending release integration — OAuth scope selection / 待发行整合 — OAuth 范围选择

The independent test branch adds explicit full-catalog read-only/all/custom choices, MCP group checkboxes and always-available refresh. Refresh and failures retain the draft; unavailable choices require explicit removal. Owner-visible exclusion counts explain publication and scope ceilings without widening authorization. Admin API-token invocation does not establish OAuth publication eligibility. At tested code head `3a730f91e2caca5ad46a4ba227749fc8be049c12`, nx5 independently passed the build and 85 grants/consent browser cases; root inspected and accepted the compact 1600×900 Chinese layout with six complete MCP rows and a visible footer. See the [separate validation evidence](../docs/release-validation-0.4.4.md#pending-integration-business-oauth-scope-selection-2026-10-05). These changes await integration and real-client acceptance and are not part of the already tagged 0.4.4 artifacts. The real Plane classification state and ChatGPT authorization/tool-cache behavior remain unverified.

独立测试分支增加明确的全目录只读/全部/自定义选择、MCP 整组复选及常驻刷新。刷新和失败保留草稿；失效选择需显式移除。仅本人可见工具的排除计数说明发布门禁和 scope 上限，不扩大授权；管理员 API Token 调用成功不证明符合 OAuth 发布门禁。已测试代码 head `3a730f91e2caca5ad46a4ba227749fc8be049c12` 在 nx5 独立构建和 85 项授权/同意浏览器回归通过；root 实际查看并接受 1600×900 中文紧凑布局，确认 6 行完整 MCP 及可见页脚。见[分列验证证据](../docs/zh-CN/release-validation-0.4.4.md#待整合业务-oauth-范围选择2026-10-05)。这些变更仍待整合与真实客户端验收，不属于已打 tag 的 0.4.4 制品；真实 Plane 分类状态及 ChatGPT 授权/工具缓存行为仍未验证。
