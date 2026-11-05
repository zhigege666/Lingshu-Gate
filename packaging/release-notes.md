# Lingshu Gate 0.5.12

## English

0.5.12 completes the Console redesign and removes routine MCP tool review/publication while preserving explicit authorization boundaries. It also closes fail-open catalog, Token-scope and concurrent-policy-edit edge cases found during the final review. The Cloudflare Tunnel and verified native updater capabilities from 0.5.11 are retained.

- Rebuild the management Console around the shadcn-admin layout direction. Navigation, page headers, filters, tables, forms, dialogs, status feedback and theme tokens are consistent across the management pages. Refresh bilingual screenshots for the dashboard, tools, services, builds and authorization pages.
- Newly discovered MCP tools synchronize automatically. Ordinary discovery and invocation do not require a separate review or publish step. Existing account grants, Token scopes, OAuth scopes and local tool policies remain enforced.
- A changed or unavailable MCP service identity fails closed. A replacement target does not silently inherit a default write policy; affected tools remain unavailable until an administrator explicitly chooses a local policy.
- Editing one exact Token tool selection preserves unchanged grants. If an existing selected tool's access snapshot changed or became unavailable, the save is rejected instead of silently rebinding that grant.
- A malformed tools/list page without result.tools is a protocol error. The last complete catalog remains intact; only an explicit valid empty tools array can clear the catalog.
- Configuration-list refresh is read-only and does not stop running MCP instances. An explicit runtime reload remains a separate, disruptive operation.
- System settings retain the optional Cloudflare Tunnel Compose profile and authenticated GitHub release checks. The release checker can pin an existing enabled HTTP/HTTPS proxy profile revision; this affects only the GitHub release request.
- Native Linux, macOS and Windows installations retain verified startup updates. The launcher checks asset size, SHA-256 and signed workflow provenance before activation, and keeps the previous binary available for rollback. Docker and Unraid image updates remain host-managed.

The release adds an additive SQLite migration for fail-closed service-identity policy handling. Back up the database, configuration and credential keys together before upgrading. Rolling back the program after database migration also requires restoring a matching backup.

Validation completed for this source candidate: frontend TypeScript checks, UX source contract, focused Vitest coverage, production Console build and four-viewport screenshot evidence from the refactor work. The final authorization, malformed-catalog and migration regression tests were added after the previous Python test run; this environment does not currently have the locked Python test toolchain available, so those backend tests still require execution in CI before publication. The build reports a non-blocking large-chunk warning for the tooltip bundle.

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/cloudflare-tunnel.md) · [Check and install updates](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/release-updates.md) · [Release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/releases.md)

## 简体中文

0.5.12 完成控制台全站重构，移除 MCP 工具日常审核／发布流程，同时保留明确的授权边界。最终审查发现的目录、Token 精确授权和并发策略编辑问题也已补充修复。0.5.11 引入的 Cloudflare Tunnel 与原生包验证更新能力继续保留。

- 按 shadcn-admin 方向重构管理控制台，统一各管理页面的导航、标题、筛选、表格、表单、弹窗、状态反馈和主题。更新总览、工具、服务、构建和授权页面的中英文截图。
- 新发现的 MCP 工具自动同步。日常发现和调用不再要求单独审核或发布；账号资源授权、Token scope、OAuth scope 和工具本地策略仍然生效。
- MCP 服务身份变化或不可用时失败关闭。替换后的目标不会静默继承默认写权限；相关工具保持不可用，直到管理员明确选择本地策略。
- 编辑 Token 的某一项精确工具范围时保留其他未变更授权。如果原有工具的访问快照发生变化或不可用，保存会被拒绝，不会静默重新绑定。
- tools/list 分页缺少 result.tools 时按协议错误处理，保留最后一次完整目录；只有明确且有效的空 tools 数组才能清空目录。
- 配置列表刷新改为只读，不会停止运行中的 MCP 实例。明确的运行时重载仍是独立且会中断服务的操作。
- 系统设置保留可选 Cloudflare Tunnel Compose profile 和经过认证的 GitHub Release 检查。版本检查可固定使用已有且启用的 HTTP/HTTPS 代理配置修订，该配置只影响 GitHub Release 请求。
- Linux、macOS 和 Windows 原生安装保留经过验证的启动时更新。启动器在切换前检查制品大小、SHA-256 和签名工作流来源，并保留旧二进制供回退。Docker 和 Unraid 镜像仍由宿主平台升级。

本版增加服务身份策略失败关闭的增量 SQLite 迁移。升级前请一起备份数据库、配置和凭据密钥。数据库迁移后如需退回旧程序，还需恢复匹配的备份。

本源码候选已完成前端 TypeScript 检查、UX 源码契约、定向 Vitest、生产 Console 构建，以及重构阶段四种桌面分辨率的截图证据。上一轮 Python 测试之后才新增的授权、无效目录响应和迁移回归测试尚未执行；当前环境缺少锁定的 Python 测试工具链，因此发布前仍需由 CI 执行这些后端测试。构建另有 Tooltip 代码块偏大的非阻断提示。

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/cloudflare-tunnel.md) · [检查与安装更新](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/release-updates.md) · [发行校验](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.12/docs/zh-CN/releases.md)
