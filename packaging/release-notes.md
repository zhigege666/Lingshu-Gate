# Lingshu Gate 0.4.8

## English — release overview

0.4.8 delivers unified personal credential management under "My Authorizations", continuous MCP authorization scoping, persistent per-authorization tool discovery modes defaulting to on-demand, configurable invocation quotas, and group purpose distinction. The release unifies personal API tokens, Gate OAuth grants, and external identity authorizations into a single management interface, removing disconnected token pages and redundant documentation bars.

- **Unified personal authorizations**: Personal API tokens, Gate OAuth authorizations, and external provider grants are managed from a unified table with search, kind/purpose/status filters, quota readouts, and scoped actions. Tokens reveal their plaintext secret only once at creation; OAuth grants originate from client flows; revocations target exact records without merging or cross-revoking distinct credentials.
- **Continuous MCP authorization**: Personal API tokens and Gate OAuth grants support continuous whole-service authorization in read-only or read-write mode. Newly discovered and published tools under that MCP automatically become available without re-selecting individual tools. Policies bind to service lifecycle identity; deleting and recreating a service or replacing its trust target invalidates continuous authorization and requires re-confirmation.
- **Authorization-level tool discovery**: Tool discovery mode (`on_demand` vs `direct`) is persisted per authorization for API tokens, Gate OAuth grants, and external OAuth records, defaulting both new and existing business authorizations to on-demand. Request-level query parameters and headers are ignored, and generated client configs omit `tool_mode`.
- **Configurable invocation quotas**: Business authorizations support editable per-minute rate limits (1–10,000, default 6,000) and concurrency limits (1–100, default 100), enforced in dispatch memory with CAS revision checks, preview differences, and atomic rollback audit.
- **Group purpose distinction**: Multi-instance execution (`execution`) and multi-data-source query (`data_source`) groups are explicitly identified, while existing groups remain `unspecified` with upgrade compatibility.
- **Persistence & migrations**: Three database migrations (`authorization_discovery`, `mcp_authorization_identity`, `token_authorizations`) upgrade existing databases while preserving SQLite single-writer and isolated Core boundaries.

The optional Native/Linux rootless Podman executor remains disabled by default; real Podman host, ChatGPT OAuth client, and multi-machine acceptance remain incomplete. Core remains gateway-only. Installing the release does not automatically provision these resources, enable OAuth, or expand permissions.

The [0.4.8 validation record](../docs/release-validation-0.4.8.md) documents exact-source checks, candidate test evidence, and formal publication boundaries. Pushing a version change to main automatically starts tag creation and the formal release workflow. Formal publication requires 11 verified assets with provenance: five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image reference, and SHA256SUMS.

## 简体中文 — 版本概述

0.4.8 提供统一个人凭据管理的“我的授权”入口、MCP 持续授权范围、持久化到每条授权且默认按需的工具发现模式、可编辑调用配额以及显式分组用途区分。本版本将个人 API 令牌、Gate OAuth 授权和外部身份提供方授权整合至统一管理界面，移除分散的独立令牌页与常驻长说明条。

- **统一“我的授权”管理**：个人 API 令牌、Gate OAuth 授权和外部提供方授权在同一表格中集中管理，提供名称/客户端搜索、授权方式/用途/状态筛选、实际配额展示及作用域操作。API 令牌明文仅在创建时展示一次；OAuth 授权仍由客户端流程发起；撤销操作精确作用于目标来源记录，不串联或误撤销其他凭据。
- **MCP 持续授权**：个人 API 令牌与 Gate 业务 OAuth 支持整服务级持续授权（只读或读写模式）。被持续授权的 MCP 下后续新发现且审核发布的工具自动获得使用权限，无需逐项重选。策略严格绑定服务生命周期身份；删除重建同名服务或替换信任目标必须重新确认，不继承旧授权。
- **授权级工具发现**：工具发现模式（按需发现 `on_demand` 与完整工具列表 `direct`）持久化至每条业务授权（API 令牌、Gate 业务 OAuth 与外部 OAuth 本地授权），新旧授权均默认按需。忽略客户端请求参数与请求头覆盖，客户端生成配置去掉 `tool_mode` 参数。
- **可编辑调用配额**：业务授权支持可配置的每分钟调用上限（1–10000，新建默认 6000）与并发上限（1–100，新建默认 100），派发时由内存计数器校验，保存经过版本 CAS、差异确认及原子审计回滚。
- **分组用途区分**：显式区分多实例执行（`execution`）与多数据源查询（`data_source`），历史分组保持 `unspecified` 并保留升级兼容性。
- **持久化与迁移**：增加 `authorization_discovery`、`mcp_authorization_identity` 与 `token_authorizations` 三项数据库迁移，继续保留 SQLite 单写入者及 Core 网关边界。

可选 Native/Linux rootless Podman 执行器默认关闭；真实 Podman 宿主、ChatGPT OAuth 客户端及多机器验收仍未完成。Core 仍仅为 gateway。安装本版不会自动准备这些资源、启用 OAuth 或扩大权限。

[0.4.8 验证记录](../docs/zh-CN/release-validation-0.4.8.md) 记录准确源码检查、候选测试证据与正式发布门禁。版本变化推入 main 会自动启动创建 tag 与正式发行工作流。正式发布要求 11 项经来源证明验证的资产：五平台 native（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像引用及 SHA256SUMS。
