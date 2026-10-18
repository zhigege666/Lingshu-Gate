# 开始使用

[English](../getting-started.md) · [文档索引](README.md)

先启动 Gate 并登录，再用包内本地 demo 验证一次允许的读取和一次被拒绝的写入。选定安装方式后，继续[首次成功与拒绝调用](first-call.md)。该流程不需要另装桌面 MCP 客户端。

## 选择入口

| 目标 | 安装方式 | 宿主要求 |
|---|---|---|
| 试用发行版，之后使用可信本地 stdio | 匹配系统、CPU 的原生归档 | Gate 本身不需要 Python、Node.js 或 Git |
| 在容器中试用已发布 HTTP 网关 | Compose 归档，明确选择 `compose.quickstart.yaml` | Docker Engine，以及支持 `up --wait` 的 Docker Compose |
| 生产网关 | Compose 归档默认 `compose.yaml`，或托管的原生服务 | TLS、明确凭据、持久存储和备份，见[部署](deployment.md) |
| 开发 Gate | 源码仓库 | Git、Python 3.11–3.13、uv；Node.js 22.x 的 22.12+、24.x 或 26+，以及 npm |

每个数据库只使用一个 Gate 写入者。原生版可以执行可信本地进程；Docker Core 接入外部 HTTP 服务，不接收容器引擎 socket。

## 下载与校验

从 [Lingshu Gate v0.5.0](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v0.5.0)下载归档及 `SHA256SUMS`，选择一个匹配的文件：

| 平台 | 文件 |
|---|---|
| Linux x86-64 | `lingshu-gate-v0.5.0-linux-x86_64.tar.gz` |
| Linux ARM64 | `lingshu-gate-v0.5.0-linux-aarch64.tar.gz` |
| Windows x86-64 | `lingshu-gate-v0.5.0-windows-x86_64.zip` |
| macOS Intel | `lingshu-gate-v0.5.0-macos-x86_64.tar.gz` |
| macOS Apple silicon | `lingshu-gate-v0.5.0-macos-arm64.tar.gz` |
| Docker Compose | `lingshu-gate-v0.5.0-docker-compose.tar.gz` |

解压和运行前，用校验清单中唯一的同名行核对该文件。[发行校验](releases.md)提供 Linux、macOS、Windows 命令和构建来源证明检查。对应行缺失、重复或摘要不匹配时停止操作。每个解压包都有适合自身包型的中英文 README，以及这些指南的本地副本。

## 运行原生包

解压已校验归档，进入解压目录，在 Linux/macOS 执行 `./start.sh`，Windows 执行 `.\start.cmd`。目录名与归档去掉扩展名后一致，例如 `lingshu-gate-v0.5.0-linux-x86_64`。保持该终端运行。

访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。另开终端进入包目录，用 `cat` 或 PowerShell `Get-Content` 读取 `data/initial-admin-credentials.json`。登录、修改初始密码，然后重新登录。Gate 会删除初始文件并撤销旧会话。只在本机读取凭据，不放入共享记录、截图或报告。

启动器默认使用包目录内的 `data/`、`config/mcp.d/`、`workspace/`；已有 `LINGSHU_GATE_*` 环境变量优先，若修改数据目录或端口，请在实际目录读取凭据并访问对应 URL。启动器不会自动读取 `lingshu-gate.env.example`，该文件说明可选环境变量。然后继续[启动 demo](first-call.md)。

## 运行已发布的 Docker 试用

校验并解压 Compose 归档，进入 `lingshu-gate-v0.5.0-docker-compose`，执行：

```bash
cp .env.quickstart.example .env.quickstart
docker compose --env-file .env.quickstart -f compose.quickstart.yaml config --quiet
docker compose --env-file .env.quickstart -f compose.quickstart.yaml up -d --no-build --wait --wait-timeout 120 core
docker compose --env-file .env.quickstart -f compose.quickstart.yaml exec core cat /data/initial-admin-credentials.json
```

PowerShell 将 `cp` 改为 `Copy-Item`，Docker 命令相同。打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，用生成的凭据登录，修改密码后重新登录，初始文件随后删除。任何启动命令失败时，先查看并解决错误，再继续操作。

这个明确选定的 quickstart 直接使用发行镜像，无需构建；仅绑定本机 HTTP，开启认证，使用 UID/GID `10001`、只读根文件系统且无引擎 socket。`lingshu-gate-quickstart` 项目和数据卷独立于生产。如果端口被占用，在 `.env.quickstart` 中设置其他 `LINGSHU_GATE_HTTP_PORT` 及对应的 loopback `LINGSHU_GATE_MCP_ALLOWED_ORIGINS`，并使用新的 URL。试用镜像内 `/workspace` 为空且只读。

离线使用时，[载入匹配的离线镜像](deployment.md)，再在 `.env.quickstart` 中选择其精确标签及 `LINGSHU_GATE_PULL_POLICY=never`。生产部署使用包内配对的 `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md`，按要求配置默认 Compose 文件、digest、bootstrap 文件、TLS 和 Secure cookie。然后继续[启动 demo](first-call.md)。

## 从源码开发

安装表中宿主依赖后执行：

```bash
git clone https://github.com/zhigege666/Lingshu-Gate.git
cd Lingshu-Gate
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run lingshu-gate
```

如需源码 Docker 构建，在同一个仓库根目录改用：

```bash
mkdir -p runtime/workspace
docker compose up -d --build --wait --wait-timeout 120 core
docker compose exec core cat /data/initial-admin-credentials.json
```

按[本地开发](local-development.md)选择独立的开发数据、配置和工作区。空数据目录启动后，从所选数据目录读取一次性凭据，登录、改密并重新登录。开发实例不复用在线生产数据。

## 完成首次调用

[首次调用指南](first-call.md)依次说明独立内存 demo、明确审核/发布、普通 viewer 的授权、动态工具发现、真实调用、审计、写入拒绝、错误修订、demo 停止/恢复及撤销。Gate 健康并不代表下游工具已经发布或获得授权。
