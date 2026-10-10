# Lingshu Gate 0.4.7

## English — release overview

0.4.7 reduces avoidable work when a concurrent configuration writer invalidates a large MCP group-directory read. Snapshot retries reuse immutable prepared contracts bound to publication revision and frozen identity, while token scopes, grants and classifications remain current. Known-stale inputs are checked before policy projection and comparison. Shared cache limits, bounded inputs and the original three-attempt limit remain in place; no production latency or RSS ceiling is promised.

The patch also carries the source changes since the immutable v0.4.4 release: explicit MCP groups and instance sessions, a bounded on-demand tool directory, private OAuth catalog/editor improvements, account-menu recovery including the queued-frame focus fix, classification change explanations, the root Console entry and fresh package staging. The runtime, CLI, package metadata and archive names use the single version source; the Console reads the running version from /healthz.

- The browser Console opens at /; /console, /console/ and /console/index.html keep compatible same-origin 307 redirects with query and browser-fragment behavior. Explicit JSON discovery remains available at / and stable metadata at /v1/meta. Root and old asset aliases retain identical bytes, confined paths and appropriate cache rules.
- Groups reference existing configurations without copying credentials or granting access. Matching complete contracts share logical entries; differing schemas/safety/version contracts remain separate. Explicit connection-bound sessions pin instances and reject changed authority, configuration/runtime drift, close/expiry and cross-instance reuse.
- Clients can explicitly select /mcp?tool_mode=on_demand for six bounded search/describe/invoke/instance/session entries. The incremental directory retains current authorization, actual-target audit, schema revisions and credential checks. Bounded killable schema workers and shared read leases support the corresponding runtime paths.
- Private OAuth selection adds whole-directory choices, MCP selection, paged schema-free candidates, full-current-selection resolution and compact bilingual editors. Refresh/errors preserve drafts; lost write responses require explicit saved-state readback before a new confirmation. Saved grants keep explicit IDs, 5,000-tool/100-MCP ceilings and existing scope/family limits.
- Repeated PEP 517 wheel builds use fresh owned staging and exact static-file/RECORD checks, including the sdist-to-wheel path. Native smoke follows the root HTML/JSON contract and verifies current JS/CSS plus old aliases. Ordinary Windows startup permits the Native executor to remain disabled. Reviewed acquisition retains a TLS 1.2 minimum and certificate/hostname verification.
- The merged frontend toolchain uses Vite 8/Rolldown with identifier mangling disabled for both static entries; Console base remains /. Frozen dependency export, parser/runtime packaging and protocol/OAuth error regressions remain checked against the exact candidate.

The optional Native/Linux rootless Podman executor is disabled by default. Its supported Git/proxy/tool preparation and bounded npm, pnpm 8/9 and Yarn Classic offline paths require separately approved absolute paths, a provisioned root, a digest-pinned image and real host readiness. Core remains gateway-only. Installing the release does not provision those resources, enable OAuth, create client credentials or expand permissions. Real Podman host, ChatGPT OAuth client and multi-machine acceptance remain incomplete; synthetic fixtures and local native startup are separate evidence. No DCR/CIMD or untrusted-code sandbox conformance is claimed.

Upgrading from the published v0.4.4 also includes the existing tool-directory/group migrations. Preserve configuration, data, credential/signing keys and the single-writer SQLite deployment, take a consistent backup and retain the prior package. The earlier “no new migration” root-entry comparison applied only to its already integrated source checkpoints.

The [0.4.7 validation record](../docs/release-validation-0.4.7.md) separates exact-source checks, fresh patch candidates and formal publication. The [catalog retry evidence](../docs/benchmarks/gate-catalog-snapshot-retry-333862e.json) records the real 5,000-instance/50,000-tool scenarios, deterministic negative controls and current-authority checks. Local measurements demonstrate avoidable retry work, not the unique cause of the earlier hosted 20-second timeout. The occupied v0.4.5/v0.4.6 tags retain their original revisions; this corrected source uses a new patch identity and the full existing formal gate. Real-host/client and sandboxed-browser limits stay explicit.

Pushing a version change to main automatically starts tag creation and the formal release workflow. The owner must first accept the candidate gate. Formal publication requires five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image reference and SHA256SUMS: 11 exact assets with provenance. Read back all mandatory jobs, checksums, inner inventories, SBOM, source/workflow attestations and the published title/body. PR artifacts and local candidates do not establish publication. Historical tags and artifacts stay immutable.

## 简体中文 — 版本概述

0.4.7 减少并发配置 writer 使大型 MCP 分组目录读取失效后产生的额外工作。快照重试复用绑定发布 revision 与冻结对象身份的不可变已准备合同，同时继续以当前 token scope、grant 与分类为准。已知过期输入在权限投影和比较前核对；共享缓存、输入边界及原最多三轮尝试保持，不承诺生产时延或 RSS 上限。

本 patch 也包含不可变 v0.4.4 发行后的源码变化：显式 MCP 分组与实例会话、有界按需工具目录、私有 OAuth 目录/编辑改进、含排队动画帧焦点修复的账户菜单恢复、分类变化原因、根路径 Console 入口及干净打包 staging。运行时、CLI、包元数据和归档名称使用唯一版本源；Console 从 /healthz 读取实际运行版本。

- 浏览器 Console 从 / 打开；/console、/console/、/console/index.html 保留同源 307 兼容跳转、查询串及浏览器片段行为。/ 保留显式 JSON 发现，/v1/meta 提供稳定元信息。根资源与旧别名保留相同字节、路径边界及适当缓存规则。
- 分组引用已有配置，不复制凭据、不自动授权。完整合同相同的工具共用逻辑条目；schema/安全声明/版本不同则保留独立分区。显式连接绑定会话固定实例，拒绝权限变化、配置/runtime 漂移、关闭/过期及跨实例复用。
- 客户端可明确选择 /mcp?tool_mode=on_demand，使用六个有界搜索/描述/调用/实例/会话入口。增量目录保留当前权限、实际目标审计、schema 版本及凭据检查；对应运行路径使用有界可终止 schema worker 和共享读租约。
- 私有 OAuth 选择增加全目录选项、MCP 选择、无 schema 候选分页、完整当前选择解析及紧凑双语编辑器。刷新/错误保留草稿；写响应丢失时须明确重读保存状态，再生成新的确认。既有 grant 保留明确 IDs、5,000 工具/100 MCP 上限及原 scope/令牌族限制。
- 连续 PEP 517 wheel 构建使用本次拥有的干净 staging，并准确检查静态文件与 RECORD，覆盖 sdist-to-wheel 链路。Native smoke 按根入口 HTML/JSON 合同验证当前 JS/CSS 及旧别名。Windows 主程序允许 Native 执行器保持禁用；受审获取保留 TLS 1.2 下限及证书/主机名验证。
- 已整合前端工具链使用 Vite 8/Rolldown，两份静态入口均关闭标识符 mangle；Console base 保持 /。冻结依赖导出、解析器/运行时打包及协议/OAuth 错误回归均按准确候选检查。

可选 Native/Linux rootless Podman 执行器默认关闭。受支持的 Git/代理/工具准备及有界 npm、pnpm 8/9、Yarn Classic 离线路径，要求另行批准的绝对路径、已准备 root、固定镜像摘要及真实宿主 readiness。Core 仍仅为 gateway。安装本版不会准备这些资源、启用 OAuth、创建客户端凭据或扩大权限。真实 Podman 宿主、ChatGPT OAuth 客户端及多机器验收仍未完成；合成 fixture 与本地 native 启动是独立证据。不声明 DCR/CIMD 或不可信代码 sandbox 合规性。

从正式 v0.4.4 升级另包含已有工具目录/分组迁移。保留配置、数据、凭据/签名密钥及 SQLite 单写实例，做好一致备份并保留旧包。根入口此前“无新增迁移”的比较只适用于其已整合源码检查点。

[0.4.7 验证记录](../docs/zh-CN/release-validation-0.4.7.md) 区分准确源码检查、新 patch 候选与正式发布。[目录重试证据](../docs/benchmarks/gate-catalog-snapshot-retry-333862e.json) 记录真实 5,000 实例/50,000 工具场景、确定性负对照及当前权限检查。本地测量证明存在额外重试工作，不证明此前托管 20 秒超时的唯一原因。已占用的 v0.4.5/v0.4.6 标签保留原修订；修正源码使用新 patch 身份并完整通过既有正式门禁，真实宿主/客户端和 sandbox 浏览器限制仍保留。

版本变化推入 main 会自动启动创建 tag 和正式发行工作流，须先由本人核验候选门禁。正式发行要求五种 native 目标（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像引用及 SHA256SUMS，共 11 项准确资产及来源证明。须回读全部必需任务、校验和、包内清单、SBOM、源码/工作流来源证明及发行标题/正文。PR artifact 和本地候选不代表正式发布；历史 tag 与制品保持不可变。
