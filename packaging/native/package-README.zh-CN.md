# Lingshu Gate @VERSION@ — 原生发行包

[English](README.md) · [开始使用](../../docs/zh-CN/getting-started.md) · [发行校验](../../docs/zh-CN/releases.md)

本包包含 Gate、Web Console 和可单独启动的本地演示 MCP 服务。运行 Gate 本身不需要宿主安装 Python、Node.js 或 Git；下游服务和可信项目构建仍可能需要各自的运行环境。

## 校验、解压并启动

从[本版本发行页](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v@VERSION@)下载对应系统、CPU 的归档及 `SHA256SUMS`。解压前将归档 SHA-256 与清单中同名行比较；[发行校验](../../docs/zh-CN/releases.md)包含各平台步骤和来源证明核验。

例如 Linux x86-64，在下载目录执行：

```bash
awk '$2 == "lingshu-gate-v@VERSION@-linux-x86_64.tar.gz" {print; n++} END {if (n != 1) exit 1}' SHA256SUMS > SHA256SUMS.native &&
sha256sum --check SHA256SUMS.native &&
tar -xzf lingshu-gate-v@VERSION@-linux-x86_64.tar.gz &&
cd lingshu-gate-v@VERSION@-linux-x86_64 &&
./start.sh
```

macOS 选择匹配的 `macos-arm64` 或 `macos-x86_64` 包，用 `shasum -a 256` 校验，解压并进入目录后执行 `./start.sh`。Windows x86-64 先用 `Get-FileHash -Algorithm SHA256` 校验，再在 PowerShell 中执行：

```powershell
Expand-Archive .\lingshu-gate-v@VERSION@-windows-x86_64.zip -DestinationPath .
Set-Location .\lingshu-gate-v@VERSION@-windows-x86_64
.\start.cmd
```

如果已经解压并校验，直接运行本目录内的启动器。保持终端运行，访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。启动器默认将数据、配置和工作区保存在本目录的 `data/`、`config/mcp.d/`、`workspace/`。已有 `LINGSHU_GATE_*` 环境变量优先；若修改数据目录或端口，请在实际目录读取凭据并访问对应 URL。环境变量示例文件仅供参考，启动器不会自动读取它。

## 首次登录

空数据目录首次启动时，Gate 生成私有的一次性凭据。在另一个终端进入本包目录后，本机读取：

```bash
cat data/initial-admin-credentials.json
```

Windows 使用 `Get-Content .\data\initial-admin-credentials.json`。用其中的用户名、密码登录，按提示修改密码，再重新登录。改密会撤销旧会话并删除初始凭据文件。不要把凭据放入共享终端记录、截图或问题报告；改密后文件不存在属于正常情况。

## 完成首次授权调用

保持 Gate 运行，在第二个终端启动独立 demo：

```bash
./lingshu-gate demo-server --host 127.0.0.1 --port 18880
```

Windows：

```powershell
.\lingshu-gate.exe demo-server --host 127.0.0.1 --port 18880
```

接着按[首次成功与拒绝调用](../../docs/zh-CN/first-call.md)操作：接入包内 `examples/mcp.d/demo.yaml`，审核并发布三个工具，建立独立的只读调用者，再发现并调用读工具。核对成功审计、写入拒绝且计数不变、过期修订、停服恢复和 token 撤销。指南使用现有 HTTP 工具，不要求另装桌面 MCP 客户端。

demo 只修改自身的内存便签。其终端 Ctrl+C 会停止 demo 并清空便签，Gate 是另一个独立进程。在 Gate 的终端 Ctrl+C 停止 Gate，数据与配置会保留。

## 保留可用安装

每个数据库只运行一个 Gate。升级前一致备份数据、配置和凭据密钥，并保留可用于回退的旧版本匹配备份。不要把新版本直接覆盖到正在使用的数据目录。原生安装能够执行可信本地项目和 stdio 工具，应使用权限适当受限的用户运行。

[部署与升级](../../docs/zh-CN/deployment.md) · [配置](../../docs/zh-CN/configuration.md) · [安全](../../SECURITY.zh-CN.md) · [全部指南](../../docs/zh-CN/README.md)
