# Lingshu Gate 0.4.3

## English — version overview

0.4.3 supports adding MCPs and tools to an existing OAuth connection through explicit owner confirmation **in Gate**, without another client OAuth flow for tools within already-consented scopes. The same bearer and refresh family follow the live grant on subsequent requests. Each JWT/family keeps its original OAuth scope ceiling: a read-only token cannot invoke newly added write tools, missing scopes are not invented, and other grants/users/connections remain unchanged. Client tool-list caches may need refreshing; actual ChatGPT cache-refresh behavior has not been integration-tested.

- Private owner options, server-derived difference review and short-lived target-bound confirmation protect additions, reconfirmations and removals. Saving rechecks current identity, permissions, client/resource/configuration/catalog and revisions under a writer transaction, performs CAS and commits the redacted audit atomically. Replaced, stale and replayed confirmations fail. Expiry and rate/concurrency limits only stay unchanged or decrease. The new editor preserves the grant's saved OAuth scope ceiling; the legacy shrink-only PATCH retains its behavior.
- Configuration Form/JSON editing and synchronization preserve unknown fields and exact drafts. Startup choices distinguish Gate start and restart intent. New MCP configurations default enabled while automatic startup stays off; saving/reloading/applying does not silently start a new service, and successful apply-without-start reports its real saved state.
- Built-in tool origins are resolved consistently in catalog, resource grants and classification review. Scope dialogs retain limits, filters, header, pagination and actions while tools scroll. MCP selectors show single-line IDs and support name search; personal grants retain owner-wide filtering/search and recorded history.
- Automatic HTTP negotiation handles only the precise initial JSON-RPC legacy initialization rejection, within a bounded handshake. Explicit protocol choices, TLS/auth/network errors and business calls retain their existing failure/no-replay boundaries. Server status shows the actual negotiated protocol after connection.

The development-only reauthorization-draft API/UI/migration is excluded. `0009_oauth_scope_confirmations` adds only bounded, expiring latest-confirmation digests; it does not delete old grant history or store tools, tokens or client secrets. Existing credential masking, revocation, permission checks and one-time-secret acknowledgement remain.

Built-in OAuth still requires explicit administrator enablement and confidential static clients. This release adds no DCR/CIMD support, production credentials or deployment permission. The production `SafeNetworkExecutor` remains unimplemented; real Git acquisition, proxy tests and configured network installations remain blocked. HTTP private-address trust from 0.4.2 remains explicitly service/IP/port-bound, unencrypted and intended for trusted internal networks. HTTPS verification and blocked redirects remain.

[Candidate validation](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.3/docs/development-validation.md) separates synthetic HTTP execution, unit/source checks and browser evidence from independent visual review and real ChatGPT integration. Platform packages and publication are accepted only after the existing formal release workflow succeeds.

The existing workflow produces five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image digests and SHA256SUMS: 11 assets with build provenance. Every release job and published asset must be verified. Downloaded packages require checksum and provenance verification. Historical releases and tags remain immutable.

## 简体中文 — 版本概述

0.4.3 支持本人**在 Gate 内明确确认增加现有连接的 MCP 和工具**，对已同意 OAuth scope 内的工具无需客户端再次 OAuth。同一 bearer 与刷新令牌族在后续请求中跟随 live grant。每个 JWT/family 保留原始 OAuth scope 上限：只读令牌不能调用新增写工具，不补造缺失 scope，其他授权、用户和连接不变。客户端缓存的工具列表可能需要刷新；真实 ChatGPT 缓存刷新行为尚未联调。

- 私有本人范围读取、服务器计算的差异核对和短期目标绑定确认保护新增、重新确认及移除。保存在写事务内重验当前身份、权限、客户端/资源/配置/目录及版本，以 CAS 更新并原子提交脱敏审计；已替换、过期及重放的确认失败。期限、调用次数及并发上限只能维持或收紧。新编辑器保留授权已保存的 OAuth scope 上限，旧只缩小 PATCH 保持原行为。
- 配置 Form/JSON 编辑与同步保留未知字段和精确草稿，明确区分 Gate 启动及重启意图。新 MCP 默认启用但不自动启动；保存、重载和应用不会悄悄启动新服务，应用但不启动准确反馈真实已保存状态。
- 工具目录、资源授权和分类审核正确解析内置工具来源。范围弹窗在工具滚动时保留配额、筛选、表头、分页与操作，MCP 选择展示单行 ID 并支持名称搜索；本人授权保留完整数据筛选/搜索和历史记录。
- HTTP 自动协商只处理精确的初始 JSON-RPC 旧版初始化拒绝，并使用有界握手。明确协议选择、TLS/认证/网络错误及业务调用保留原有失败和不重放边界，连接后展示实际协商版本。

此前仅开发的重新授权草稿 API/UI/迁移不纳入本版。`0009_oauth_scope_confirmations` 只新增有界、到期的最新确认摘要，不删除旧授权历史，不保存工具、令牌或客户端 secret。凭据脱敏、撤销、权限检查和一次性 secret 关闭确认保持。

内置 OAuth 仍需管理员明确启用并登记机密静态客户端。本版不增加 DCR/CIMD、生产凭据或部署权限。生产 `SafeNetworkExecutor` 尚未实现，真实 Git 拉取、代理测试和指定网络安装仍阻断。0.4.2 内网 HTTP 信任继续绑定精确服务/IP/端口，HTTP 不加密，仅用于受信任内网；HTTPS 验证与禁止重定向保留。

[候选验证](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.3/docs/zh-CN/development-validation.md) 分别记录合成 HTTP 执行、单元/源码检查和浏览器证据，区分独立视觉验收与真实 ChatGPT 联调。平台构建包与正式发布仅在既有发行工作流成功后验收。

既有工作流构建五种原生目标（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像摘要与 SHA256SUMS，共 11 项资产及构建来源证明。须核验全部发行任务及发布资产，下载后核验校验和与来源证明；历史发行和 tag 保持不可变。
