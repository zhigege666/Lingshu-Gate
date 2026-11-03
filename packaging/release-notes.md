# Lingshu Gate 0.5.9

## English

0.5.9 improves evidence for storage startup failures and makes configuration-directory readiness consistent with administrator diagnostics. It preserves empty-instance startup and separates the last configuration scan from the directory's current state.

### Changes

- Emit bounded `gate.startup.path_failed` diagnostics at the failed storage/configuration boundary, with `component`, `phase`, `reason_code`, path and effective runtime identity facts. Preserve the original failure; do not retry with broader permissions or repair host ownership automatically.
- Keep credential values, database URLs, SQL, database contents, unrelated environment values and raw exception text out of the added diagnostic metadata. Report SQLite `CANTOPEN` as `database_open_failed` without inferring its cause.
- Reuse directory checks for configuration readiness and administrator diagnostics. A missing but creatable directory remains acceptable for a new empty instance; public probe metadata does not expose filesystem paths or identity details.
- Report the last full configuration scan as `not_scanned`, `missing`, `loaded` or `failed`, with service and load-error counts. A skipped missing-directory scan is distinct from a successfully loaded empty directory. Readiness reads, manual directory creation and a single configuration apply do not silently become a full rescan.
- Document preparation of the actual host bind-mount paths, checks under the service user, the limited meaning of `--version`, and full startup acceptance. Add focused regressions and real-user container smoke cases for allowed and denied data mounts with UID/GID `10001` and a read-only root.

### Upgrade and compatibility

No runtime dependency or database migration is introduced over 0.5.8. Existing data, configuration and credential paths remain in use. Preserve the normal consistent backup of data, configuration, encrypted credential stores and their keys before upgrading.

Core remains non-root, with a read-only root filesystem and no container-engine socket. Host bind mounts can hide directories and ownership prepared in the image; deployment operators remain responsible for the final host paths. Review existing ownership, modes and ACLs before targeted repairs. Do not recursively relax permissions or run Core as root to bypass a diagnosed access problem.

The MCP timeout and bounded late-response recovery introduced in 0.5.7 are retained, including the original identity, authorization and runtime-connection boundaries. The seven-entry on-demand catalog and release-contract fixes from 0.5.8 are preserved. No automatic manifest watcher is added. Existing explicit reload can stop and replace downstream runtime connections; it remains a separate operator action.

### Support and validation boundaries

Directory access inspection is read-only and does not guarantee that a later database write succeeds. A ready empty instance does not prove that an existing deployment selected the correct configuration path or loaded its expected downstream services. Storage startup failures can occur before HTTP probes are available; use the safe startup diagnostics in that case.

Focused coverage targets path types and access failures, safe diagnostics, missing/empty/failed configuration scans, readiness/administrator-check consistency, and complete container startup with correct or denied host data permissions. HTTP resource checks do not establish browser rendering, and a rendered sign-in page does not establish login or downstream-call success. These scopes remain separate from acceptance on a particular operator's host.

Formal release publication separately requires all four quality shards, five native packages, Compose, two offline Core images, application SBOM, exact container reference, aggregate checksums and provenance verification. A source check, tag or partially completed workflow is not a finished release.

See [deployment](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/deployment.md), [operator diagnostics](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/operations.md), [changes](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/CHANGELOG.md) and [release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/releases.md).

## 简体中文

0.5.9 补充存储启动失败的证据，让配置目录就绪检查与管理员诊断保持一致。继续允许空实例启动，并将最近一次配置扫描与目录当前状态分开报告。

### 变更

- 在存储或配置失败边界记录受限的 `gate.startup.path_failed` 诊断，包含 `component`、`phase`、`reason_code`、路径及有效运行身份事实。保留原失败，不扩大权限重试或自动修正宿主属主。
- 新增诊断元数据不包含凭据值、数据库 URL、SQL、数据库内容、无关环境值或原始异常全文。SQLite `CANTOPEN` 仅报告为 `database_open_failed`，不据此推断根因。
- 配置就绪检查与管理员诊断复用目录检查。新空实例目录缺失但可创建时仍然有效；公开探针元数据不暴露文件系统路径或身份详情。
- 用 `not_scanned`、`missing`、`loaded`、`failed` 报告最近一次完整配置扫描，并提供服务数和加载错误数。区分因缺失目录跳过扫描与成功加载空目录；读取就绪、手动创建目录或应用单项配置均不会被误报成完整重扫。
- 补充实际宿主 bind mount 准备、运行用户检查、`--version` 的验证边界及完整启动验收文档；增加定向回归与实际用户容器冒烟，覆盖 UID/GID `10001`、只读根和允许或拒绝访问的数据挂载。

### 升级与兼容

相对 0.5.8 不新增运行依赖或数据库迁移，继续使用既有数据、配置与凭据路径。升级前沿用数据、配置、加密凭据存储和全部密钥的一致备份要求。

Core 保持非 root、根文件系统只读、不接触容器引擎 socket。宿主 bind mount 可以遮盖镜像中准备的目录和属主，最终宿主路径仍由部署者准备。既有数据应先检查属主、模式和 ACL，再进行针对性修复，不递归放宽权限或改用 root 绕过访问错误。

保留 0.5.7 引入的 MCP 超时与有界迟到响应回读，以及原身份、授权和运行时连接边界；同时保留 0.5.8 的七入口按需目录与发行契约修正。不新增 Manifest 自动监听；既有显式重载可能停止并替换下游连接，仍是单独的运维操作。

### 支持与验证边界

目录访问检查只读执行，不能保证后续数据库写入一定成功。空实例就绪不能证明既有部署选中了正确配置路径或加载了预期下游服务。存储失败可能发生在 HTTP 探针可用之前，此时应依据安全的启动诊断。

定向覆盖包括路径类型与访问失败、诊断脱敏、缺失／空／失败配置扫描、就绪与管理检查一致性，以及实际宿主数据权限正确或被拒绝时的完整容器启动。HTTP 资源检查不证明浏览器渲染，登录页渲染不证明登录或下游调用成功；这些范围与特定运维宿主的验收保持区分。

正式发布另需四个质量分片、五个平台原生包、Compose、两个离线 Core 镜像、应用 SBOM、精确容器引用、总校验和及来源证明全部通过。源码检查、标签或部分流水线成功均不代表完整发布。

参见[部署](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/zh-CN/deployment.md)、[运维诊断](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/zh-CN/operations.md)、[变更记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/CHANGELOG.zh-CN.md)及[发行验证](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.9/docs/zh-CN/releases.md)。
