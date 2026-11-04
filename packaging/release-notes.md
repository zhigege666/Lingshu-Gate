# Lingshu Gate 0.5.11

## English

0.5.11 adds an optional Cloudflare Tunnel sidecar deployment and authenticated GitHub release discovery in the Console.

### Changes

- Add an opt-in cloudflare-tunnel Compose profile. cloudflared uses a remotely managed tunnel token from a read-only host file and connects to the private core:8000 service. The sidecar is isolated from Gate Core and has no Docker socket, host networking or Linux capabilities.
- Add System settings → Updates. The Console checks the latest stable GitHub Release when the tab opens and supports a manual check. It displays the running backend version, latest tag, release date, notes and release link.
- Add an independent GitHub check proxy selector. It reuses a version-pinned, enabled HTTP/HTTPS proxy profile; credentials stay encrypted and masked. Direct mode ignores process proxy environment variables. The selection does not affect other Gate network traffic.
- Add an additive SQLite migration and audit events for update proxy changes and checks.

### Upgrade and compatibility

The update checker is available after normal startup applies migration 0025_gate_release_updates. Existing network profiles and credentials are reused without migration or rewriting. Cloudflare Tunnel is opt-in and does not change existing port publishing or proxy defaults.

### Security and installation boundary

Gate Core remains unprivileged and disconnected from Docker Engine sockets. The Cloudflare token is mounted only into the separate cloudflared sidecar. Configure Cloudflare Access in addition to Gate authentication. Anyone holding a tunnel token can run that tunnel; protect and rotate it as a secret.

This release discovers updates but does not automatically replace the running container or native package. Apply the release using the deployment environment, then verify /readyz and the running version. This is intentional: a self-updater must not weaken the Core privilege boundary.

### Validation and known limits

The focused release-update regression tests cover proxy profile pinning, disabled and unsupported profiles, settings compare-and-swap, and newer release comparison. Full backend tests, frontend checks/build, Compose runtime validation and formal release asset verification must pass in the release pipeline before publication is considered complete.

The release checker currently supports HTTP and HTTPS proxy profiles, not SOCKS. Cloudflare Tunnel sidecar status is observed in the cloudflared logs and Cloudflare dashboard; Gate Core does not introspect the sidecar. Production deployments should the Compose default pins cloudflared 2026.10.7; operators may override it with a reviewed digest.

See [Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/cloudflare-tunnel.md), [release update checks](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/release-updates.md), [changes](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/CHANGELOG.md) and [release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/releases.md).

## 简体中文

0.5.11 增加可选的 Cloudflare Tunnel Sidecar 部署方式，以及控制台内经过认证的 GitHub 版本发现功能。

### 变更

- 增加可选的 cloudflare-tunnel Compose profile。cloudflared 从宿主机只读文件读取远程管理隧道 Token，并连接私有网络中的 core:8000。Sidecar 与 Gate Core 隔离，不挂载 Docker Socket、不使用 host 网络、不申请 Linux capabilities。
- 增加“系统设置 → 版本更新”。进入页面时自动检查最新正式 GitHub Release，也支持手动检查。展示运行中的后端版本、最新标签、发布日期、更新说明和发行链接。
- 增加独立的 GitHub 检查代理选择器。复用固定版本且已启用的 HTTP/HTTPS 代理配置；凭据继续加密保存并脱敏。直连模式忽略进程代理环境变量。此选择不影响 Gate 其他网络流量。
- 增加独立 SQLite 迁移，并审计更新代理配置变更和检查行为。

### 升级与兼容

正常启动应用迁移 0025_gate_release_updates 后即可使用更新检查。复用已有网络配置和凭据，不迁移或重写原有记录。Cloudflare Tunnel 默认关闭，不改变现有端口发布和代理默认值。

### 安全与安装边界

Gate Core 继续以非特权方式运行，不连接 Docker Engine Socket。Cloudflare Token 只挂载到独立的 cloudflared Sidecar。除 Gate 自身认证外，还应配置 Cloudflare Access。持有隧道 Token 的人可以运行该隧道，必须按密钥保护并在泄露时轮换。

本版本可以发现新版本，但不会自动替换运行中的容器或原生程序。请由部署环境应用发行版本，然后检查 /readyz 和实际运行版本。这是有意保留的安全边界，不能通过削弱 Core 权限实现自更新。

### 验证与已知限制

定向版本更新回归测试覆盖代理版本固定、禁用及不支持的代理、设置 CAS 和新版本比较。正式发布仍需由发行流水线完成后端全集测试、前端检查与构建、Compose 运行时校验以及全部正式发行资产验证，完成前不能认定发布成功。

当前版本检查器支持 HTTP/HTTPS 代理配置，不支持 SOCKS。Cloudflare Tunnel Sidecar 状态通过 cloudflared 日志和 Cloudflare 控制台查看；Gate Core 不读取 Sidecar 内部状态。Compose 默认固定 cloudflared 2026.10.7；运维者也可覆盖为经过审核的 digest。

参见 [Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/cloudflare-tunnel.md)、[版本更新检查](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/release-updates.md)、[更新记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/CHANGELOG.zh-CN.md)和[发行验证](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/releases.md)。