# Lingshu Gate 0.4.10

## English — release overview

0.4.10 fixes stdio configuration validation and the repository-identity failure that stopped the preceding release before packaging. It retains the existing MCP lifecycle, continuous authorization and on-demand discovery behavior without expanding permissions or changing deployment defaults.

- **Stdio configuration**: Empty or whitespace-only optional endpoints are normalized to no endpoint for stdio. Precheck, creation, editing and reload agree, while Form/JSON runtime switching remains lossless. Streamable HTTP still requires a valid URL; private-origin trust, redaction and non-empty endpoint validation remain enforced.
- **Release identity recovery**: Documentation and test helper names use neutral wording. The already-existing 0.4.8/0.4.9 snapshots are pinned by commit, path, Git blob, SHA-256 and exact findings rather than rewriting tags or disabling history checks.
- **Preserved artwork provenance**: Four reviewed concept PNGs keep their original bytes, including C2PA source metadata. Only their exact image and metadata-chunk digests distinguish source attribution from product identity; changed files, other metadata and other identity findings stay strict.
- **Upgrade boundary**: No new dependency or database migration is introduced. Configuration saving does not execute a downstream package, start a service or grant tool access. Existing native/Core restrictions and optional-executor defaults remain unchanged.

See the [0.4.10 validation record](../docs/release-validation-0.4.10.md) for executed candidate checks and the local Python-version boundary. A version change or successful identity check is not publication. Formal release still requires all quality checks and eleven verified assets: five native targets, Compose, two offline Core images, application SPDX SBOM, container image reference and SHA256SUMS, with build provenance. Existing tags remain immutable.

## 简体中文 — 版本概述

0.4.10 修复 Stdio 配置校验，以及上一版在打包前被仓库身份检查阻断的问题。既有 MCP 生命周期、持续授权与按需发现行为保持不变，不扩大权限或改变部署默认值。

- **Stdio 配置**：Stdio 的可选地址为空或纯空白时按未填写处理，预检、创建、编辑和重新读取一致；表单/JSON 运行方式切换仍保持无损。Streamable HTTP 仍须提供有效 URL，私网信任、脱敏与非空地址校验继续生效。
- **发行身份检查修复**：文档和测试辅助命名改用中性表述；已有 0.4.8/0.4.9 历史快照按提交、路径、Git Blob、SHA-256 和精确发现项固定，不重写标签或关闭历史检查。
- **保留概念图来源证明**：四张已审查 PNG 保留原始字节及 C2PA 来源元数据。仅针对精确图片和元数据块摘要区分来源身份与产品身份；修改文件、其他元数据和其他身份规则仍严格检查。
- **升级边界**：不新增依赖或数据库迁移。保存配置不会执行下游包、启动服务或授予工具访问权；原生/Core 限制及可选执行器默认值保持不变。

执行证据和本机 Python 版本边界见 [0.4.10 验证记录](../docs/zh-CN/release-validation-0.4.10.md)。版本变化或身份检查通过均不代表发布完成；正式发行仍要求完整质量检查及十一项经来源证明验证的资产：五平台原生包、Compose、两个离线 Core 镜像、应用 SPDX SBOM、容器镜像引用及 SHA256SUMS。已有标签保持不可变。
