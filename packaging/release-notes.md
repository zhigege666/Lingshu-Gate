# Lingshu Gate 0.4.9

## English — release overview

0.4.9 preserves tool classifications, original review timestamps, and OAuth authorization snapshots across MCP service restarts, temporary connection failures, and smooth upgrades for unchanged tool definitions. Offline tools leave the callable tool catalog immediately upon disconnect, ensuring offline safety while avoiding redundant re-authorization or re-review cycles when the service recovers.

- **MCP review & authorization lifecycle preservation**: When an MCP server restarts, reconnects after temporary network/health-check outages, or undergoes an upgrade, tools whose definitions remain unchanged retain their existing classification status and review timestamps. Callers retain their granted access without requiring new OAuth consent or manual scope adjustment.
- **Callable catalog offline boundary**: Tools belonging to a stopped, failed, or disconnected MCP server are unlisted from the callable tool catalog immediately. Retaining classification and review records does not make an offline tool invocable.
- **Upgrade reconciliation against complete tools/list**: When a service restores and reports its full tool list, unchanged tools preserve their existing authorization snapshots. Newly introduced tools are registered as `pending` with `unknown` access requiring explicit review and publication. Old tools omitted from the complete tool list remain invalidated, even if they reappear at a later date.
- **Strict security & lifecycle boundaries**: Modifications to tool definitions, explicit unregistrations, service deletion/recreation, and token/grant revocations retain their existing invalidation behavior. This behavior is standard lifecycle policy and introduces no new configuration flags.

The optional Native/Linux rootless Podman executor remains disabled by default; real Podman host, ChatGPT OAuth client, and multi-machine acceptance remain incomplete. Core remains gateway-only. Installing the release does not automatically provision these resources, enable OAuth, or expand permissions.

The [0.4.9 validation record](../docs/release-validation-0.4.9.md) documents exact-source checks, candidate test evidence, and formal publication boundaries. Pushing a version change to main automatically starts tag creation and the formal release workflow. Formal publication requires 11 verified assets with provenance: five native targets (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application SPDX SBOM, image reference, and SHA256SUMS.

## 简体中文 — 版本概述

0.4.9 在同一 MCP 服务重启、临时连接断开或平滑升级时，只要工具定义保持未变，即可保留其分类、原审核时间戳以及已确认的 OAuth 授权快照。服务离线后工具立即退出可调用目录，在保障离线安全性的同时，免除服务恢复后重复授权与重新审核的负担。

- **MCP 审核与授权生命周期保留**：当 MCP 服务发生普通重启、网络/健康检查临时中断恢复或服务平滑升级时，与之前定义完全一致的工具继续保留其原分类和审核时间戳。客户端与使用者无需重新进行 OAuth 授权确认或手动更新权限范围。
- **可调用目录严格离线**：服务停止、失败或断开连接后，所属工具立即从网关可调用目录中下架；保留审核信息绝不会使不可用工具仍处于可调用状态。
- **恢复与升级完整快照对齐**：服务恢复并提供完整工具列表（`tools/list`）后，未变更工具恢复既有授权快照；新增工具进入待审核状态（`pending` / `unknown`），须经管理员明确审核与发布；被完整列表实际移除的旧工具维持失效，即便日后再次出现亦须重新审核。
- **严格安全与生命周期边界**：工具定义变更、显式注销、服务删除重建及凭据/授权撤销严格保留原有失效机制。本生命周期规则为开箱即用默认行为，不引入额外配置开关。

可选 Native/Linux rootless Podman 执行器默认关闭；真实 Podman 宿主、ChatGPT OAuth 客户端及多机器验收仍未完成。Core 仍仅为 gateway。安装本版不会自动准备这些资源、启用 OAuth 或扩大权限。

[0.4.9 验证记录](../docs/zh-CN/release-validation-0.4.9.md) 记录准确源码检查、候选测试证据与正式发布门禁。版本变化推入 main 会自动启动创建 tag 与正式发行工作流。正式发布要求 11 项经来源证明验证的资产：五平台 native（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX SBOM、镜像引用及 SHA256SUMS。
