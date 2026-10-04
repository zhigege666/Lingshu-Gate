## Lingshu Gate v0.4.2

### English

0.4.2 adds explicitly authorized downstream HTTP MCP connections for trusted
internal RFC1918 IPv4 addresses and exact ports.

- Permit declarations only in `10.0.0.0/8`, `172.16.0.0/12` and
  `192.168.0.0/16`, using canonical IPv4 literals. A manifest does not grant
  trust. The separate SQLite policy starts empty and binds the service ID,
  address and actual port, including port 80 when omitted.
- Require a live active Gate administrator with `operations.manage`, explicit
  confirmation and an expected policy revision. Ordinary operators and OAuth
  connections cannot self-approve. Record an audit event without credentials.
- Add an inline **Authorize this address** action to the existing configuration
  editor. Confirm the exact service, IP and port; retain the configuration draft.
  Editing the draft invalidates confirmation. Authorization uses a separate API,
  does not save or start the service, and rechecks the unchanged draft afterward.
- Recheck current policy before precheck/save/apply/connect/reconnect and every
  downstream request. Revoked or unreadable trust fails closed. Reject public,
  link-local, metadata, DNS and noncanonical HTTP targets. Keep all redirects
  blocked, HTTPS certificate verification and existing loopback behavior.

HTTP is unencrypted; use this feature only on a trusted internal network.
This release does not change startup policy or broaden tool, resource, OAuth
or API-token grants. The production `SafeNetworkExecutor` remains absent;
real Git acquisition, proxy tests and configured network installs remain blocked.
No production trust records, credentials or deployment permissions are created.
Validation and remaining limits are recorded in the paired
[0.4.2 validation record](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.2/docs/release-validation-0.4.2.md).

The existing release workflow builds all five native targets (Linux x86_64/ARM64,
Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application
SPDX, image digest metadata and `SHA256SUMS` (11 assets), with build-provenance
attestations. All release jobs must succeed before publication. Verify downloaded
packages against checksums and attestations. Historical releases stay immutable.

### 简体中文

0.4.2 支持明确授权的内网 HTTP MCP 连接，限定受信任 RFC1918 IPv4 地址与精确端口。

- 仅允许 `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16` 内的规范 IPv4
  字面地址声明。Manifest 不授予信任；独立 SQLite 策略默认空，绑定服务 ID、
  地址和实际端口，省略端口时使用 80。
- 要求实时有效的 Gate 管理员身份及 `operations.manage`、明确确认和预期策略
  版本。普通操作员与 OAuth 连接不能自行批准；审计事件不包含凭据。
- 在现有配置编辑器加入内联“授权此地址”，确认精确服务、IP 和端口，保留草稿。
  修改草稿即使旧确认失效；授权使用独立 API，不保存、不启动服务，成功后重检
  同一份草稿。
- 预检查、保存、应用、连接、重连与每次下游请求前重检当前策略。撤销或读取失败
  即拒绝；禁止公网、链路本地、metadata、DNS 和非规范 HTTP 目标。所有重定向
  仍禁止，HTTPS 证书验证及现有回环行为保留。

HTTP 不加密，仅用于受信任内网。本版不改变自启策略，也不扩大工具、资源、OAuth
或 API token 授权。生产 `SafeNetworkExecutor` 尚未实现，真实 Git 拉取、代理测试
和指定网络安装保持阻断。不创建生产信任记录、凭据或部署权限。验证与限制见成对的
[0.4.2 验证记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.2/docs/zh-CN/release-validation-0.4.2.md)。

沿用发行工作流构建五种原生目标（Linux x86_64/ARM64、Windows x86_64、macOS
x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX、镜像摘要与 SHA256SUMS，
共 11 项资产及构建来源证明；全部发行任务成功后才发布。下载后须核验校验和与
来源证明。历史发行保持不可变。
