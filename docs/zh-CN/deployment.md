# 部署

[English](../deployment.md) · [文档索引](README.md)

如果需要隔离控制平面和外部 Streamable HTTP 网关，选择 Docker Core。如果 Gate 需要启动可信本机 stdio 进程或执行可信项目构建，选择原生包。

## 部署矩阵

| 方式 | 建议用途 | 本机执行 | 持久化 |
|---|---|---|---|
| Docker Compose Core | 反向代理后的单机网关 | 不支持受管 stdio 或项目构建 | 命名 `config` 与 `data` Volume；只读 Workspace Bind |
| 原生发行包 | 可信工作站或专用服务主机 | 受管 stdio、显式本机受管容器和项目构建 | 明确的平台目录 |
| 源码仓库 | 开发和验证 | 与原生方式相同 | 开发者指定目录 |

所有方式都使用 SQLite，每个数据库只运行一个 Gate 进程。

## Docker Compose 快速开始

在源码仓库中：

```bash
mkdir -p runtime/workspace
docker compose up -d --build core
docker compose ps
curl --fail http://127.0.0.1:8000/readyz
```

服务默认只在宿主回环地址发布 `8000`。它以 UID/GID `10001` 运行，根文件系统只读，丢弃全部 Linux Capability，禁止权限提升，以只读方式挂载 Workspace，并限制临时存储和资源。

从私有 Data Volume 读取一次性管理员凭据，登录后立即修改密码：

```bash
docker compose exec core sh -c 'cat /data/initial-admin-credentials.json'
```

密码修改后，该文件会被删除。

### Compose 发行包

发行资产 `lingshu-gate-v<version>-docker-compose.tar.gz` 包含针对该部署的 `DEPLOYMENT.md` 和 `.env.example`。校验并解压后：

```bash
cp .env.example .env
```

复核每个值，选择固定 Digest 的镜像，准备 Workspace 和 Bootstrap Password 文件，通过 `docker compose config --quiet` 校验，再启动服务。包内部署指南是该发行版准确文件的权威说明。

## 生产 Compose

`compose.prod.yaml` 要求显式提供镜像、初始管理员和密码文件。Linux 上的最小准备流程为：

```bash
export LINGSHU_GATE_IMAGE='ghcr.io/zhigege666/lingshu-gate@sha256:<digest>'
export LINGSHU_GATE_BOOTSTRAP_ADMIN_USERNAME='bootstrap-admin'
export LINGSHU_GATE_WORKSPACE_ROOT='/srv/lingshu-gate/workspace'
export LINGSHU_GATE_TRUSTED_PROXY_IPS='127.0.0.1'
export LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE="$PWD/secrets/bootstrap-admin-password"

sudo install -d -o 10001 -g 10001 -m 0750 "$LINGSHU_GATE_WORKSPACE_ROOT"
install -d -m 0700 ./secrets
python -c 'import secrets; print(secrets.token_urlsafe(32))' > "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"
chmod 0600 "$LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"

docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d
curl --fail http://127.0.0.1:8000/readyz
```

调整密码文件所有权，让容器 UID `10001` 可以读取，同时不允许 group/world 写入。Rootless 容器引擎和桌面虚拟化使用不同 UID 映射，应在实际服务账户下验证可读性。

首次登录后修改管理员密码，并轮换 Provisioning Secret。只要 Compose 定义还引用该文件，就必须持续保护它。

### 反向代理要求

- 终止 TLS，并把明文 HTTP 重定向到 HTTPS。
- Gate 只发布在代理可访问的私有地址。
- 在服务环境中设置 `LINGSHU_GATE_AUTH_COOKIE_SECURE=true`。
- 把 `LINGSHU_GATE_TRUSTED_PROXY_IPS` 设为精确代理地址或最小内部 CIDR；禁止在不受控网络设为 `*`。
- 用代理生成的转发头覆盖客户端提供的值。
- 保持 `/mcp` 和事件流 Endpoint 的流式行为。
- 设置上传大小、Header 大小、空闲超时和速率限制，同时不截断合法的受限操作。
- 如果不应公开 API 发现，则限制 `/docs`。

## 离线 Docker 镜像

Tag 发行提供：

```text
lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz
lingshu-gate-v<version>-docker-core-linux-arm64.tar.gz
```

完成 checksum 和 attestation 校验后，加载匹配的归档：

```bash
gunzip -c lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz | docker load
```

加载后的镜像 Tag 为：

```text
ghcr.io/zhigege666/lingshu-gate:<version>-amd64-offline
```

ARM64 主机在两处名称中都使用 `arm64`。把 Compose Image 变量设为准确的本机 Tag。保留压缩资产和 `SHA256SUMS` 作为部署证据。

## 原生包

校验并解压对应主机架构的归档，再运行 `start.sh` 或 `start.cmd`。启动器使用解压目录内的路径，适合单用户安装。

作为系统服务运行时：

1. 把包放在 Root 拥有的应用目录；
2. 创建不可登录的 `lingshu-gate` 服务账户；
3. 创建独立可写的 Data、Config 和 Workspace 目录；
4. 设置绝对路径的 `LINGSHU_GATE_DATA_DIR`、`LINGSHU_GATE_CONFIG_DIR` 和 `LINGSHU_GATE_ALLOWED_ROOT`；
5. 绑定回环地址或面向代理的私有地址；
6. 让服务管理器在服务账户下直接运行可执行文件；
7. 只对必需目录授予写权限；
8. 配置重启限制，并使用 `/healthz`、`/startupz` 和 `/readyz` 监控。

不要仅为了让下游命令工作，就以管理员或 Root 运行 Gate。应修复所有权，或使用权限更窄的专用执行账户。

## 健康探针

| Endpoint | 含义 | 编排器操作 |
|---|---|---|
| `/healthz` | 进程和 HTTP Stack 可响应 | 仅在重复失败后重启 |
| `/startupz` | 初始化完成 | 成功前不接收流量 |
| `/readyz` | 核心存储和请求路径可服务 | 失败时从路由移除 |

单个下游服务异常不应让整个网关 Not Ready。请通过服务状态和诊断单独监控下游。

## 备份

把 Data 和 Config 作为一致的加密整体备份。Workspace 按被管理项目的策略备份。

SQLite 部署应：

1. 干净停止 Gate；
2. 复制完整 Data 和 Config 目录，包括凭据密钥文件；
3. 记录应用版本、镜像摘要或构建元数据、备份时间和文件 Hash；
4. 重启 Gate 并校验 Readiness；
5. 在隔离主机测试恢复，且不打印凭据。

不要把复制在线 SQLite 文件作为唯一备份。不要只备份密文而遗漏密钥，也不要让备份权限弱于线上服务。

## 升级

1. 阅读发行说明，并校验 `SHA256SUMS`、Artifact Attestation、SBOM 和 `BUILD-INFO.json`。
2. 记录当前版本和镜像摘要。
3. 停止 Gate 并完成一致备份。
4. 安装新的原生包，或设置固定 Digest 的新容器镜像。
5. 只启动一个 Gate 实例。
6. 检查 Startup 和 Readiness，登录，检查数据库与配置加载，列出下游状态，并执行一个已授权只读工具。
7. 检查审计写入和错误日志，再结束维护窗口。

禁止新旧二进制同时使用同一个 SQLite 数据库。

## 回滚

如果新版没有造成不兼容的持久化数据变化，可以恢复旧可执行文件或镜像 Digest，并重启一个实例。如果数据已经变化，应停止 Gate，保留失败状态用于调查，再恢复与旧版本匹配的升级前 Data 和 Config 备份。

回滚是破坏性运维决定。必须先确认准确的备份路径和版本；不要自动删除未知 Volume 或 Data 目录。
