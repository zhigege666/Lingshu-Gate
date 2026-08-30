# Lingshu Gate

一个可自托管的 MCP 网关与控制平面，通过明确的访问、审计和交付边界管理下游服务。

[English](README.md) · [中文文档](docs/zh-CN/README.md) · [安全策略](SECURITY.zh-CN.md) · [贡献指南](CONTRIBUTING.zh-CN.md)

Lingshu Gate 提供统一的认证 MCP 入口、Web Console、配置与运行时管理、加密凭据、工具分类、调用审计、诊断，以及受控的项目上传、构建、部署和启动工作流。

## 核心能力

- `POST /mcp` 上的统一 Streamable HTTP MCP 网关。
- 使用协议版本 `2026-07-28` 的通用下游 Streamable HTTP 与 stdio 传输。
- 用于服务配置和运行状态管理的 Web Console 与 REST 控制 API。
- 认证、RBAC、资源授权、API Token scope、工具分类和调用审计。
- 加密的系统凭据与按用户隔离的下游请求绑定。
- 日志、事件、健康探针、诊断和受限的运行时缓存管理。
- 项目上传、预检、确定性构建计划、构建、部署、启动和工具刷新。
- 仓库自带的 Delivery Skill：`.agents/skills/lingshu-gate-upload-build-start/`，通过 `gate_*` 交付工具执行有确认边界的自动化。

## 快速开始

### Docker Compose

Docker Compose 是启动隔离控制平面和 HTTP 网关的最短路径：

```bash
mkdir -p runtime/workspace
docker compose up -d --build core
docker compose ps
```

打开 <http://127.0.0.1:8000/console>。空数据卷首次启动时，Gate 会把一次性管理员密码写入 `/data/initial-admin-credentials.json`：

```bash
docker compose exec core sh -c 'cat /data/initial-admin-credentials.json'
```

登录后立即修改密码，再创建最小权限的用户或 API Token。密码修改成功后，一次性凭据文件会自动删除。

默认 Compose 服务只绑定 `127.0.0.1`，以 UID/GID `10001` 运行，根文件系统只读，并保持认证开启。Core 镜像用于连接外部 Streamable HTTP 服务；当 Gate 需要启动本机 stdio 进程或执行项目构建时，请使用原生安装。

### 预构建原生包

从 [GitHub Releases](https://github.com/zhigege666/Lingshu-Gate/releases) 下载对应平台的压缩包和 `SHA256SUMS`，完成校验并解压，然后运行：

```bash
./start.sh
```

Windows：

```powershell
.\start.cmd
```

启动器会创建包内的 `data`、`config` 和 `workspace` 目录。也可以直接运行 `lingshu-gate`（Windows 为 `lingshu-gate.exe`），此时应通过 `LINGSHU_GATE_*` 环境变量提供所需路径。

### 从源码运行

要求 Python 3.11、3.12 或 3.13、Node.js 22、npm 和 `uv`。

```bash
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run lingshu-gate
```

Gate 默认监听 `127.0.0.1:8000`。Web Console 位于 `/console`，OpenAPI 文档位于 `/docs`，就绪探针位于 `/readyz`。

## 第一个服务

在配置的 `mcp.d` 目录中创建通用 Manifest，或使用 Console：

```yaml
id: example-http
name: Example HTTP server
enabled: true
launch:
  type: external
transport:
  type: streamable_http
  endpoint: https://service.example/mcp
  protocol_version: "2026-07-28"
auto_start: false
```

`protocol_version` 用于显式自说明；只接受 `2026-07-28`，它不是版本选择开关。

校验并保存 Manifest，检查发现的工具，将其分类为只读或写入，人工复核后只发布允许调用的分类。最终访问权限是控制权限、资源授权、已发布分类和 API Token scope 的交集。

本机 stdio 配置、凭据引用、生命周期行为和网关请求见 [MCP 网关与下游服务](docs/zh-CN/mcp-gateway.md)。

## 项目交付

Gate 提供有确认边界的 `gate_*` 工具，用于可续传上传、预检、构建计划、构建执行、部署、启动和启动后的工具对账。每项写操作都绑定幂等键；源文件、计划、配置、凭据和工具快照摘要用于阻止静默漂移。

仓库自带的 [Delivery Skill](.agents/skills/lingshu-gate-upload-build-start/SKILL.md) 在这些工具之上增加确定性本地打包和操作流程。上传、代码执行、部署、覆盖、启动、取消或放弃会话之前，仍必须获得明确确认。

完整边界和工具列表见 [项目交付](docs/zh-CN/project-delivery.md)。

## 安全默认值

- 认证默认开启；初始凭据随机生成且只保存在数据目录。
- 网络默认绑定回环地址；远程访问应放在 HTTPS 反向代理之后。
- 会话 Cookie 使用 `HttpOnly` 和 `SameSite=Lax`；HTTPS 部署应设置 `LINGSHU_GATE_AUTH_COOKIE_SECURE=true`。
- MCP payload 日志默认关闭。
- Secret 加密保存，响应中仅返回掩码元数据；Manifest 应使用 `${credential:<id>}` 引用。
- Tool annotation 只是提示。人工复核并发布的分类和显式授权共同决定有效访问权限。
- Docker Core 服务会丢弃 Linux capabilities、禁止权限提升，并以只读方式挂载 workspace。

在单台受信任主机之外暴露 Gate 前，请先阅读 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## 发行下载

发行自动化构建以下归档：

| 目标 | 归档 |
|---|---|
| Linux x86-64 | `lingshu-gate-v<version>-linux-x86_64.tar.gz` |
| Linux ARM64 | `lingshu-gate-v<version>-linux-aarch64.tar.gz` |
| Windows x86-64 | `lingshu-gate-v<version>-windows-x86_64.zip` |
| macOS x86-64 | `lingshu-gate-v<version>-macos-x86_64.tar.gz` |
| macOS ARM64 | `lingshu-gate-v<version>-macos-arm64.tar.gz` |
| Docker Compose | `lingshu-gate-v<version>-docker-compose.tar.gz` |

Tag 发行还提供 `amd64` 和 `arm64` 的 Linux Core 离线镜像，以及应用 SPDX SBOM。每个原生包都包含 `SBOM.spdx.json`、`BUILD-INFO.json`、`LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和本 README。解压前应按 `SHA256SUMS` 校验所选归档，详见 [发行产物](docs/zh-CN/releases.md)。

## 支持矩阵

| 能力 | Linux 原生 | Windows 原生 | macOS 原生 | Docker Core |
|---|:---:|:---:|:---:|:---:|
| Console、REST API、`/mcp` 网关 | 是 | 是 | 是 | 是 |
| 外部 Streamable HTTP 下游 | 是 | 是 | 是 | 是 |
| 受管本机 stdio 下游 | 是 | 是 | 是 | 否 |
| 显式受管容器下游 | 本机容器引擎可用时 | 本机容器引擎可用时 | 本机容器引擎可用时 | 否 |
| 本机项目构建执行 | 需要对应宿主工具链 | 需要对应宿主工具链 | 需要对应宿主工具链 | 否 |
| SQLite 持久化 | 是 | 是 | 是 | 是，仅单个 Core 副本 |
| 发行架构 | x86-64、ARM64 | x86-64 | x86-64、ARM64 | Linux amd64、arm64 |

原生归档只捆绑 Gate，不会捆绑所有项目运行时。下游启动和构建能否跨平台运行，仍取决于项目自身的工具链、命令、路径和依赖；预检会在执行前报告缺失项。

## 文档

- [架构](docs/zh-CN/architecture.md)
- [配置](docs/zh-CN/configuration.md)
- [MCP 网关与下游服务](docs/zh-CN/mcp-gateway.md)
- [项目交付](docs/zh-CN/project-delivery.md)
- [部署](docs/zh-CN/deployment.md)
- [运维](docs/zh-CN/operations.md)
- [本地开发](docs/zh-CN/local-development.md)
- [发行产物](docs/zh-CN/releases.md)

## 开源协议

Lingshu Gate 使用 Apache License 2.0 发布，见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。第三方组件继续受各自协议约束；打包所需声明记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
