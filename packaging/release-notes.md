# Lingshu Gate 0.5.12

## English

0.5.12 completes the Console redesign, keeps remote HTTP MCP catalogs synchronized and removes repeated tool review/publication while preserving explicit authorization boundaries. It also closes fail-open catalog, Token-scope and concurrent-policy-edit edge cases. The Cloudflare Tunnel and verified native updater capabilities from 0.5.11 are retained.

- Rebuild the management Console around the shadcn-admin layout direction. Navigation, page headers, filters, tables, forms, dialogs, status feedback and theme tokens are consistent across the management pages. Refresh bilingual screenshots for the dashboard, tools, services, builds and authorization pages.
- Newly discovered MCP tools synchronize automatically. Ordinary discovery and invocation do not require a separate review or publish step. Existing account grants, Token scopes, OAuth scopes and local tool policies remain enforced.
- Receive downstream tool changes on an independent notification stream, with approximately one-minute fallback discovery. Unsupported notifications fall back to polling; temporary failures retain the last complete catalog and use bounded retry backoff.
- Preserve saved local access policies across ordinary metadata updates, reconnects and restarts. A removed tool that returns under the same service identity uses conservative write defaults, without reviving an old exact grant or a disabled policy. Service replacement still requires an administrator's explicit local-policy decision.
- Separate connection health from tool synchronization in the Console and service API. Show the last successful sync, added/updated/removed counts and next retry. HTTP 401/403 or denied credential use enters `auth_required` and pauses automatic recovery until credentials are corrected and the operator reconnects or synchronizes again.
- Reinitialize expired HTTP sessions and rediscover tools without replaying writes. Only a trusted read policy, unchanged contract and renewed authorization checks permit a single read retry. Connected clients can receive changes to their authorized tool list through the protocol's notification stream; client refresh never expands OAuth or exact-tool scopes.
- A changed or unavailable MCP service identity fails closed. A replacement target does not silently inherit a default write policy; affected tools remain unavailable until an administrator explicitly chooses a local policy.
- Editing one exact Token tool selection preserves unchanged grants. If an existing selected tool's access snapshot changed or became unavailable, the save is rejected instead of silently rebinding that grant.
- A malformed tools/list page without result.tools is a protocol error. The last complete catalog remains intact; only an explicit valid empty tools array can clear the catalog.
- Configuration-list refresh is read-only and does not stop running MCP instances. An explicit runtime reload remains a separate, disruptive operation.
- System settings retain the optional Cloudflare Tunnel Compose profile and authenticated GitHub release checks. The release checker can pin an existing enabled HTTP/HTTPS proxy profile revision; this affects only the GitHub release request.
- Native Linux, macOS and Windows installations retain verified startup updates. The launcher checks asset size, SHA-256 and signed workflow provenance before activation, and keeps the previous binary available for rollback. Docker and Unraid image updates remain host-managed.
- Upgrade the OpenTelemetry API, SDK and OTLP HTTP exporter to 1.45.1 with compatible semantic conventions 0.66b1 to address quadratic parsing of untrusted `tracestate` headers ([GHSA-xcq7-p3pf-p88h / CVE-2026-114603](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h)). Adapt the exporter request entry while retaining the fixed OTLP destination, disabled redirects, TLS verification and sanitized responses.

The release adds an additive SQLite migration for fail-closed service-identity policy handling. Back up the database, configuration and credential keys together before upgrading. Rolling back the program after database migration also requires restoring a matching backup.

Source-candidate evidence includes the Console refactor's TypeScript checks, UX source contract, focused Vitest coverage, production build and four-viewport screenshots, plus focused authorization, migration and catalog regressions: 105 tests and 4 subtests passed on Python 3.14.4. This targeted run does not replace the supported-Python CI matrix, formal release quality shards, native/package verification or deployment acceptance. Formal release success must be checked on the final source revision. The Console build has a non-blocking large-chunk warning for the tooltip bundle.

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/cloudflare-tunnel.md) · [Check and install updates](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/release-updates.md) · [Release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/releases.md)

## 简体中文

0.5.12 完成控制台全站重构，持续同步远端 HTTP MCP 目录，移除重复的工具审核／发布流程，同时保留明确的授权边界。目录、Token 精确授权和并发策略编辑问题也已补充修复。0.5.11 引入的 Cloudflare Tunnel 与原生包验证更新能力继续保留。

- 按 shadcn-admin 方向重构管理控制台，统一各管理页面的导航、标题、筛选、表格、表单、弹窗、状态反馈和主题。更新总览、工具、服务、构建和授权页面的中英文截图。
- 新发现的 MCP 工具自动同步。日常发现和调用不再要求单独审核或发布；账号资源授权、Token scope、OAuth scope 和工具本地策略仍然生效。
- 通过独立通知流接收下游工具变更，并以约一分钟的周期发现补充同步。不支持通知时回到周期同步；临时失败保留最后一次完整目录，并使用有界退避重试。
- 普通元数据更新、重新连接和重启保留已保存的本地访问策略。同一服务身份下删除后重现的工具恢复保守的读写默认要求，不复活旧精确授权或已禁用策略；服务身份替换仍须由管理员明确选择本地策略。
- 控制台和服务 API 分别展示连接健康与工具同步，提供最近成功时间、新增／更新／移除数量及下次重试。HTTP 401/403 或凭据使用被拒绝时进入 `auth_required`，暂停自动恢复，待修正凭据后重新连接或同步。
- HTTP 会话过期后重新初始化并发现工具，不重放写调用。只有受信本地策略为只读、契约未变且重新鉴权通过时，才允许一次只读重试。客户端可通过协议通知流获知其有权工具列表变化；刷新客户端缓存不会扩大 OAuth 或精确工具范围。
- MCP 服务身份变化或不可用时失败关闭。替换后的目标不会静默继承默认写权限；相关工具保持不可用，直到管理员明确选择本地策略。
- 编辑 Token 的某一项精确工具范围时保留其他未变更授权。如果原有工具的访问快照发生变化或不可用，保存会被拒绝，不会静默重新绑定。
- tools/list 分页缺少 result.tools 时按协议错误处理，保留最后一次完整目录；只有明确且有效的空 tools 数组才能清空目录。
- 配置列表刷新改为只读，不会停止运行中的 MCP 实例。明确的运行时重载仍是独立且会中断服务的操作。
- 系统设置保留可选 Cloudflare Tunnel Compose profile 和经过认证的 GitHub Release 检查。版本检查可固定使用已有且启用的 HTTP/HTTPS 代理配置修订，该配置只影响 GitHub Release 请求。
- Linux、macOS 和 Windows 原生安装保留经过验证的启动时更新。启动器在切换前检查制品大小、SHA-256 和签名工作流来源，并保留旧二进制供回退。Docker 和 Unraid 镜像仍由宿主平台升级。
- 将 OpenTelemetry API、SDK 和 OTLP HTTP 导出器升级至 1.45.1，配套语义约定包升级至 0.66b1，修复解析不可信 `tracestate` 请求头时的二次复杂度问题（[GHSA-xcq7-p3pf-p88h / CVE-2026-114603](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h)）。同步适配导出器请求入口，保留固定 OTLP 端点、禁止重定向、TLS 验证和响应清洗约束。

本版增加服务身份策略失败关闭的增量 SQLite 迁移。升级前请一起备份数据库、配置和凭据密钥。数据库迁移后如需退回旧程序，还需恢复匹配的备份。

本源码候选已有控制台重构阶段的 TypeScript 检查、UX 源码契约、定向 Vitest、生产构建和四种桌面分辨率截图证据；授权、迁移与目录定向回归在 Python 3.14.4 上通过 105 项测试和 4 个子测试。该定向结果不替代受支持 Python 版本的 CI 矩阵、正式发行质量分片、原生制品校验或部署验收；正式发行是否成功须核对最终源码修订的工作流结果。Console 构建仍有 Tooltip 代码块偏大的非阻断提示。

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/cloudflare-tunnel.md) · [检查与安装更新](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/release-updates.md) · [发行校验](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/releases.md)
