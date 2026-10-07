# Lingshu Gate 0.4.5

## English — release overview

0.4.5 consolidates the source changes since the immutable v0.4.4 release: explicit MCP groups and instance sessions, a bounded on-demand tool directory, private OAuth catalog/editor improvements, the root Console entry and fresh package staging. The runtime, CLI, package metadata and archive names use the single version source; the Console reads the running version from /healthz.

- The browser Console opens at /; /console, /console/ and /console/index.html keep compatible same-origin 307 redirects with query and browser-fragment behavior. Explicit JSON discovery remains available at / and stable metadata at /v1/meta. Root and old asset aliases retain identical bytes, confined paths and appropriate cache rules.
- Groups reference existing configurations without copying credentials or granting access. Matching complete contracts share logical entries; differing schemas/safety/version contracts remain separate. Explicit connection-bound sessions pin instances and reject changed authority, configuration/runtime drift, close/expiry and cross-instance reuse.
- Clients can explicitly select /mcp?tool_mode=on_demand for six bounded search/describe/invoke/instance/session entries. The incremental directory retains current authorization, actual-target audit, schema revisions and credential checks. Bounded killable schema workers and shared read leases support the corresponding runtime paths.
- Private OAuth selection adds whole-directory choices, MCP selection, paged schema-free candidates, full-current-selection resolution and compact bilingual editors. Refresh/errors preserve drafts; lost write responses require explicit saved-state readback before a new confirmation. Saved grants keep explicit IDs, 5,000-tool/100-MCP ceilings and existing scope/family limits.
- Repeated PEP 517 wheel builds use fresh owned staging and exact static-file/RECORD checks, including the sdist-to-wheel path. Native smoke follows the root HTML/JSON contract and verifies current JS/CSS plus old aliases. Ordinary Windows startup permits the Native executor to remain disabled. Reviewed acquisition retains a TLS 1.2 minimum and certificate/hostname verification.
- The merged frontend toolchain uses Vite 8/Rolldown with identifier mangling disabled for both static entries; Console base remains /. Frozen dependency export, parser/runtime packaging and protocol/OAuth error regressions remain checked against the exact candidate.

The optional Native/Linux rootless Podman executor is disabled by default. Its supported Git/proxy/tool preparation and bounded npm, pnpm 8/9 and Yarn Classic offline paths require separately approved absolute paths, a provisioned root, a digest-pinned image and real host readiness. Core remains gateway-only. Installing the release does not provision those resources, enable OAuth, create client credentials or expand permissions. Real Podman host, ChatGPT OAuth client and multi-machine acceptance remain incomplete; synthetic fixtures and local native startup are separate evidence. No DCR/CIMD or untrusted-code sandbox conformance is claimed.

Upgrading from the published v0.4.4 also includes the existing tool-directory/group migrations. Preserve configuration, data, credential/signing keys and the single-writer SQLite deployment, take a consistent backup and retain the prior package. The earlier “no new migration” root-entry comparison applied only to its already integrated source checkpoints.

The [0.4.5 validation record](../docs/release-validation-0.4.5.md) identifies the candidate source, isolated checks, newly built package hashes, CI checkout SHAs and release gates. Historical browser checkpoints are not reported as green: the parent-reported PR49 default run was 418 passed / 55 skipped / 2 failed out of 475; its optional run was 27 passed / 3 skipped / 7 failed. Failure attribution remains unproven. Required candidate failures block acceptance; residual browser scope and real-host/client limits remain explicit for owner review.

Pushing a version change to main automatically starts tag creation and the formal release workflow. The owner must first accept the candidate gate. Formal publication requires five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image reference and SHA256SUMS: 11 exact assets with provenance. Read back all mandatory jobs, checksums, inner inventories, SBOM, source/workflow attestations and the published title/body. PR artifacts and local candidates do not establish publication. Historical tags and artifacts stay immutable.

## 简体中文 — 版本概述

0.4.5 整合不可变 v0.4.4 发行后的源码变化：显式 MCP 分组与实例会话、有界按需工具目录、私有 OAuth 目录/编辑改进、根路径 Console 入口及干净打包 staging。运行时、CLI、包元数据和归档名称使用唯一版本源；Console 从 /healthz 读取实际运行版本。

- 浏览器 Console 从 / 打开；/console、/console/、/console/index.html 保留同源 307 兼容跳转、查询串及浏览器片段行为。/ 保留显式 JSON 发现，/v1/meta 提供稳定元信息。根资源与旧别名保留相同字节、路径边界及适当缓存规则。
- 分组引用已有配置，不复制凭据、不自动授权。完整合同相同的工具共用逻辑条目；schema/安全声明/版本不同则保留独立分区。显式连接绑定会话固定实例，拒绝权限变化、配置/runtime 漂移、关闭/过期及跨实例复用。
- 客户端可明确选择 /mcp?tool_mode=on_demand，使用六个有界搜索/描述/调用/实例/会话入口。增量目录保留当前权限、实际目标审计、schema 版本及凭据检查；对应运行路径使用有界可终止 schema worker 和共享读租约。
- 私有 OAuth 选择增加全目录选项、MCP 选择、无 schema 候选分页、完整当前选择解析及紧凑双语编辑器。刷新/错误保留草稿；写响应丢失时须明确重读保存状态，再生成新的确认。既有 grant 保留明确 IDs、5,000 工具/100 MCP 上限及原 scope/令牌族限制。
- 连续 PEP 517 wheel 构建使用本次拥有的干净 staging，并准确检查静态文件与 RECORD，覆盖 sdist-to-wheel 链路。Native smoke 按根入口 HTML/JSON 合同验证当前 JS/CSS 及旧别名。Windows 主程序允许 Native 执行器保持禁用；受审获取保留 TLS 1.2 下限及证书/主机名验证。
- 已整合前端工具链使用 Vite 8/Rolldown，两份静态入口均关闭标识符 mangle；Console base 保持 /。冻结依赖导出、解析器/运行时打包及协议/OAuth 错误回归均按准确候选检查。

可选 Native/Linux rootless Podman 执行器默认关闭。受支持的 Git/代理/工具准备及有界 npm、pnpm 8/9、Yarn Classic 离线路径，要求另行批准的绝对路径、已准备 root、固定镜像摘要及真实宿主 readiness。Core 仍仅为 gateway。安装本版不会准备这些资源、启用 OAuth、创建客户端凭据或扩大权限。真实 Podman 宿主、ChatGPT OAuth 客户端及多机器验收仍未完成；合成 fixture 与本地 native 启动是独立证据。不声明 DCR/CIMD 或不可信代码 sandbox 合规性。

从正式 v0.4.4 升级另包含已有工具目录/分组迁移。保留配置、数据、凭据/签名密钥及 SQLite 单写实例，做好一致备份并保留旧包。根入口此前“无新增迁移”的比较只适用于其已整合源码检查点。

[0.4.5 验证记录](../docs/zh-CN/release-validation-0.4.5.md) 区分候选源码、隔离检查、新包摘要、CI checkout SHA 与发行门禁。历史浏览器检查点不计为全绿：父任务报告 PR49 默认运行 475 项中 418 通过/55 跳过/2 失败，optional 为 27 通过/3 跳过/7 失败；失败归因仍未证。必需候选检查失败会阻断验收；剩余浏览器范围及真实宿主/客户端限制保留供本人复核。

版本变化推入 main 会自动启动创建 tag 和正式发行工作流，须先由本人核验候选门禁。正式发行要求五种 native 目标（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像引用及 SHA256SUMS，共 11 项准确资产及来源证明。须回读全部必需任务、校验和、包内清单、SBOM、源码/工作流来源证明及发行标题/正文。PR artifact 和本地候选不代表正式发布；历史 tag 与制品保持不可变。
