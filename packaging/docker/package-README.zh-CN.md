# Lingshu Gate @VERSION@ — Docker Compose 发行包

[English](README.md) · [开始使用](../../docs/zh-CN/getting-started.md) · [发行校验](../../docs/zh-CN/releases.md)

使用 Docker Engine 和 Docker Compose 运行本版本 Core 镜像。本包不需要源码仓库、宿主 Python 或 Node.js。Core 提供 Console 与外部 HTTP MCP 网关；可信本地 stdio 和项目执行使用原生包。

从 [v@VERSION@ 发行页](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v@VERSION@)下载 Compose 归档和 `SHA256SUMS`，核对同名行校验和，解压并进入 `lingshu-gate-v@VERSION@-docker-compose/`。[发行校验](../../docs/zh-CN/releases.md)包含归档与来源证明检查。

## 在本机试用

在解压后的目录执行：

```bash
cp .env.quickstart.example .env.quickstart
docker compose --env-file .env.quickstart -f compose.quickstart.yaml config --quiet
docker compose --env-file .env.quickstart -f compose.quickstart.yaml up -d --no-build --wait --wait-timeout 120 core
```

PowerShell 使用相同 Docker 命令，第一行改为 `Copy-Item .env.quickstart.example .env.quickstart`。镜像使用本发行版本标签；本机试用不需要构建源码、准备 TLS 域名或预先配置 bootstrap 秘密。

访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，在本机读取生成的一次性凭据：

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml exec core cat /data/initial-admin-credentials.json
```

用其中的用户名、密码登录，修改密码后重新登录。旧会话会被撤销，初始文件会删除。不要把文件内容放入共享记录或截图。

试用仅绑定宿主 `127.0.0.1`，认证开启，cookie 用于本机 HTTP。Core 使用 UID/GID `10001`，根文件系统和空工作区只读，不挂载容器引擎 socket。`lingshu-gate-quickstart` 项目持有独立的数据、配置卷，不复用生产卷。如果 8000 端口被占用，在 `.env.quickstart` 中修改 `LINGSHU_GATE_HTTP_PORT` 及对应的 loopback `LINGSHU_GATE_MCP_ALLOWED_ORIGINS`，访问修改后的地址。

## 启动可选 demo

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
```

demo 与 Core 共享网络命名空间，监听 `127.0.0.1:18880`，不额外发布宿主端口。命令等待 Core 和 demo 监听就绪。然后按[首次成功与拒绝调用](../../docs/zh-CN/first-call.md)在 Gate 中接入、审核、发布和授权。demo 启动本身不会自动创建用户、授权或发布工具。

只停止 demo 时，保留同样的 `--env-file` 和两个 `-f` 参数，最后使用 `stop demo`。恢复使用上面的启动命令。停止整个试用并保留数据：

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml down
```

下次 `up` 继续使用本试用的数据卷和修改后的密码。只有确实要删除试用数据时才添加 `--volumes`。

## 生产或离线使用

生产部署请按 [DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md)，或 [English deployment guide](DEPLOYMENT.md)。默认 `compose.yaml` 要求明确 bootstrap 用户名、密码文件，并在 HTTPS 后使用 Secure cookie。选择发布的镜像 digest，配置实际受信代理与浏览器 Origin。本机 HTTP 试用和生产使用明确分开的配置。

离线试用先按[部署指南](../../docs/zh-CN/deployment.md)校验并载入匹配的离线镜像。在 `.env.quickstart` 中设置 `LINGSHU_GATE_IMAGE=ghcr.io/zhigege666/lingshu-gate:@VERSION@-amd64-offline`（ARM64 主机使用 `arm64`）及 `LINGSHU_GATE_PULL_POLICY=never`，继续使用相同 quickstart 命令。`.env.offline-*.example` 配置的是生产 Compose，仍要求 bootstrap 与 HTTPS。

每个数据库只运行一个 Core。升级前一致备份数据、配置和凭据密钥。包内包含 `BUILD-INFO.json`、`SBOM.spdx.json`、法律声明和[全部指南](../../docs/zh-CN/README.md)。
