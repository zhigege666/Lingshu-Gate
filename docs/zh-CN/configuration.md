# 配置

[English](../configuration.md) · [文档索引](README.md)

Lingshu Gate 从 `LINGSHU_GATE_*` 环境变量读取运行配置。原生包启动器提供包内目录；Docker Compose 提供容器路径和安全网络默认值。

## 常用设置

| 变量 | 原生默认值 | Docker 值 | 说明 |
|---|---|---|---|
| `LINGSHU_GATE_HOST` | `127.0.0.1` | 容器内 `0.0.0.0` | Docker 默认只在宿主回环地址发布端口 |
| `LINGSHU_GATE_PORT` | `8000` | `8000` | Console、API、探针和 `/mcp` 的 HTTP 端口 |
| `LINGSHU_GATE_DATA_DIR` | 平台应用数据目录 | `/data` | 数据库、加密凭据、上传、构建和操作状态 |
| `LINGSHU_GATE_CONFIG_DIR` | 平台应用配置目录 | `/config/mcp.d` | 下游 YAML 和 JSON Manifest |
| `LINGSHU_GATE_ALLOWED_ROOT` | 启动器的 `workspace` 目录 | `/workspace` | 可信本机文件和项目路径的边界 |
| `LINGSHU_GATE_DB_URL` | Data 目录下的 SQLite 数据库 | `sqlite:////data/gate.db` | 每个 SQLite 文件只运行一个 Gate 进程 |
| `LINGSHU_GATE_AUTH_ENABLED` | `true` | `true` | 只允许在隔离的本机调试环境关闭 |
| `LINGSHU_GATE_AUTH_COOKIE_SECURE` | `false` | 本机 Compose 为 `false` | 公共 Origin 使用 HTTPS 时设为 `true` |
| `LINGSHU_GATE_TRUSTED_PROXY_IPS` | `127.0.0.1` | `127.0.0.1` | 允许提供转发头的精确代理地址/CIDR；不得在不受控网络使用 `*` |
| `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` | 配置端口上的回环 Origin | 相同 | `/mcp` 的逗号分隔浏览器 Origin 白名单；非浏览器客户端通常不发送 `Origin` |
| `LINGSHU_GATE_LOG_LEVEL` | `INFO` | `INFO` | 标准 Python 日志级别 |
| `LINGSHU_GATE_LOG_PAYLOADS` | `false` | `false` | Payload 可能含敏感数据，应保持关闭 |
| `LINGSHU_GATE_REQUEST_TIMEOUT_SECONDS` | `30` | `30` | 下游请求时间上限 |
| `LINGSHU_GATE_STARTUP_TIMEOUT_SECONDS` | `30` | `30` | 下游启动和发现时间上限 |
| `LINGSHU_GATE_MCP_GATEWAY_ENABLED` | `true` | `true` | 控制 `/mcp` 路由 |

协议版本 `2026-07-28` 由发行版固定，不是运行时调优项。

布尔值使用应用已经实现的格式，建议写 `true`/`false`。无效数值或不支持的部署角色会阻止启动，不会被静默忽略。

## 原生目录布局

发行包启动器会在解压目录中创建可写目录：

```text
lingshu-gate/
  config/
    mcp.d/
  data/
  workspace/
  start.sh          # Unix 包
  start.cmd         # Windows 包
```

直接运行 `lingshu-gate` 时会使用平台应用目录，除非显式覆盖。为了让服务行为可预测，建议明确设置绝对路径的 `DATA_DIR`、`CONFIG_DIR` 和 `ALLOWED_ROOT`。

不要把 Data 目录放在 Web Root 或源码仓库中。凭据密钥材料和审计状态都位于其中，因此应只允许 Gate 服务账户访问。

## 初始管理员

认证开启且数据库没有用户时，Gate 会为 `admin` 生成一次性密码，保存在：

```text
<data-dir>/initial-admin-credentials.json
```

该文件只存在于本机；在支持的平台上使用严格权限创建；API 和日志不会返回密码。管理员首次登录后必须修改密码，Gate 随后删除该文件。

无人值守部署可以配置管理员用户名，并通过部署的 bootstrap password 设置从受保护的绝对路径文件注入初始密码。密码文件必须是普通 UTF-8 文件，只含一个非空行；在 POSIX 系统上不得允许 group/world 写入；也不得保存在仓库中。

## 下游 Manifest

Manifest 是存放在 `mcp.d` 中的 YAML 或 JSON 对象。文件名不是身份，`id` 才是。ID 必须匹配 `^[A-Za-z0-9_.-]+$`，并保持稳定，因为授权、凭据、运行状态和审计都会引用它。

### 外部 Streamable HTTP

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
  headers:
    Authorization: "Bearer ${credential:discovery-token}"
timeout_seconds: 30
auto_start: false
```

该 Manifest 字段用于显式自说明，只接受 `2026-07-28`，不能选择其他协议模式。

静态 Header 可以包含 `${credential:<id>}` 引用。Gate 只在下游请求中解析它，并在 API 响应和日志中掩码显示。

### 受管本机 stdio

受管 stdio 只在原生模式可用，并以 Gate 操作系统账户运行：

```yaml
id: example-stdio
name: Example stdio server
enabled: true
launch:
  type: managed_process
  command: python
  args:
    - server.py
  cwd: /absolute/path/inside/the/allowed/root
  env:
    SERVICE_TOKEN: "${credential:runtime-token}"
transport:
  type: stdio
  protocol_version: "2026-07-28"
timeout_seconds: 30
auto_start: false
```

Stdio Manifest 同样只接受 `2026-07-28`。

使用经过复核且位于 Allowed Root 内的绝对 `cwd`。避免 Shell Wrapper，直接配置可执行文件和参数列表。在命令、凭据和工具定义完成复核前，应保持 Auto Start 关闭。

### 显式原生受管容器

原生 Gate 安装可以通过本机容器引擎启动经过复核的容器：

```yaml
id: example-container
name: Example container server
enabled: true
launch:
  type: managed_container
  image: registry.example/server@sha256:<digest>
  mounts:
    - source: /absolute/allowed/input
      target: /workspace
      read_only: true
  environment:
    SERVICE_TOKEN: "${credential:container-token}"
  resources:
    memory: 512m
    cpus: "1.0"
    pids_limit: 128
transport:
  type: stdio
  protocol_version: "2026-07-28"
auto_start: false
```

镜像必须使用小写 SHA-256 Digest。`mounts` 是唯一接受的 Bind Schema：每个 Source 都必须是 `LINGSHU_GATE_ALLOWED_ROOT` 内现存的普通文件或目录，每个 Target 都必须是容器内的非根绝对路径，且不能位于受保护的 `/dev`、`/proc`、`/run`、`/sys` 和 `/tmp` 目录树中；同时不能关闭 `read_only`。Gate 会在执行前再次解析和校验 Source。

每次启动都会强制使用 `--network none`、只读根文件系统、删除全部 Capability、禁止权限提升，以及受保护的 `/tmp` 和 `/run` tmpfs。资源限制始终生效；省略时默认使用 `512m`、`1.0` CPU 和 128 PIDs，硬上限为 `4g`、4 CPUs 和 512 PIDs。Manifest Environment 不能覆盖任何 `LINGSHU_GATE_*` 值或 Docker 进程控制。Docker Core 不提供该模式，也绝不能通过向 Core 服务挂载容器引擎 Socket 来启用。

### 按用户隔离的 HTTP 凭据

外部 HTTP Manifest 可以声明不含 Secret 的用户 Slot：

```yaml
user_credentials:
  - id: personal-token
    name: Personal access token
    description: Used only for this user's downstream calls
    required: true
    injection:
      type: http_header
      name: Authorization
      template: "Bearer {value}"
```

用户通过认证凭据 API 或 Console 绑定值。Gate 会单独加密，在该认证用户的独立 HTTP 请求上下文中注入，并且不会写回 Manifest。受保护的 MCP Header 不能被覆盖。共享 stdio 进程不支持按用户隔离的 Secret。

## 凭据

系统凭据通过 Console 或 `/v1/credentials` 管理。API 响应只显示 ID 和掩码状态，不返回明文。在 `launch.env`、`launch.environment` 或 `transport.headers` 中按以下方式引用：

```text
${credential:credential-id}
```

加密存储和对应密钥文件必须一起备份。加密可避免 Secret 意外进入 Manifest 和 API 输出，但不能防御能够读取整个 Data 目录的主机账户。

## 反向代理

远程访问应：

1. 让 Gate 绑定私有或回环接口。
2. 在可信反向代理终止 TLS。
3. 设置 `LINGSHU_GATE_AUTH_COOKIE_SECURE=true`。
4. 把 `LINGSHU_GATE_TRUSTED_PROXY_IPS` 设置为实际代理 IP 或最小内部 CIDR；默认值为 `127.0.0.1`。
5. 让代理覆盖而不是追加客户端传入的 `Forwarded` 和 `X-Forwarded-*` Header。
6. 为上传和流式端点设置合适的请求大小及超时限制。

不要在不受控网络把可信来源设为 `*`，也不要在代理之外同时暴露 Gate 私有端口。

## 校验

保存 Manifest 前，使用 Console 或 `POST /v1/mcp/configs/validate` 校验。校验只覆盖 Schema 和本地策略；通过校验不能证明远程 Endpoint 可信或健康。保存后应检查服务状态、发现的工具、分类和授权，再允许调用。
