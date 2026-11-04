# Lingshu Gate 0.5.11

## English

0.5.11 adds Cloudflare Tunnel deployment, per-route GitHub release checks and verified updates for native installations.

- Open **System settings → Cloudflare Tunnel** for the tunnel setup and host commands. The optional Compose profile runs cloudflared as a separate container. Only that container receives the tunnel token file. Configure the private origin and access rules in Cloudflare.
- **System settings → Updates** shows the running version and the latest stable GitHub Release. Choose an enabled HTTP/HTTPS proxy profile to save its revision and check immediately. This setting applies only to the Console's release check. Configuration changes and successful checks are audited.
- Native Linux, macOS and Windows installations can opt into updates on startup with `lingshu-gate native-update update-start`. The launcher downloads the public asset anonymously, checks its SHA-256 and verifies the signed workflow, source commit and timestamp with the host GitHub CLI before activation. The `update`, `start` and `rollback` actions also work individually. Container image upgrades stay with the deployment platform.
- Startup applies the additive migration `0025_gate_release_updates`. Back up the database, configuration and credential keys together before upgrading. Rolling back the program after a database migration also requires restoring a matching backup.

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/cloudflare-tunnel.md) · [Check and install updates](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/release-updates.md) · [Release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/releases.md)

## 简体中文

0.5.11 新增 Cloudflare Tunnel 部署入口、可单独指定代理的 GitHub 版本检查和原生包自动更新。

- 打开 **系统设置 → Cloudflare Tunnel** 可查看安装与宿主机操作命令。可选 Compose profile 使用独立容器运行 cloudflared，仅该容器挂载隧道 Token 文件。在 Cloudflare 配置内网源站和访问规则。
- **系统设置 → 版本更新** 展示运行版本和最新的正式 GitHub Release。选择已启用的 HTTP/HTTPS 代理后可以一次保存并检查，固定所选代理修订。该配置只作用于控制台的版本检查。设置变更和成功检查会记录审计事件。
- Linux、macOS 和 Windows 原生包可用 `lingshu-gate native-update update-start` 开启启动时自动更新。启动器匿名下载公开制品，检查 SHA-256，再通过宿主 GitHub CLI 核验签名工作流、源码提交和时间戳，验证通过后切换版本。也可单独执行 `update`、`start` 和 `rollback`。容器镜像由部署平台升级。
- 启动时应用增量迁移 `0025_gate_release_updates`。升级前请一起备份数据库、配置和凭据密钥。数据库迁移后如需退回旧程序，还需恢复对应备份。

[Cloudflare Tunnel](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/cloudflare-tunnel.md) · [检查与安装更新](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/release-updates.md) · [发行校验](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/zh-CN/releases.md)
