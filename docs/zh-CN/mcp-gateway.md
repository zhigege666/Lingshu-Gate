# MCP 网关与下游服务

[English](../mcp-gateway.md) · [文档索引](README.md)

Lingshu Gate 在 `POST /mcp` 提供统一的认证 Streamable HTTP MCP 入口，聚合经过复核的第一方操作和从已配置下游服务发现的工具。

## 连接契约

- 默认本机 Endpoint：`http://127.0.0.1:8000/mcp`。
- 协议版本：`2026-07-28`，由发行版固定。
- 认证：已认证的 Console Cookie，或 `Authorization: Bearer <api-token>`。
- 内容协商：遵循协议的 Streamable HTTP 要求。
- 请求模型：HTTP 无状态；每个请求都必须携带必需的协议和调用方元数据。

先调用 `server/discover`，使用当前协议实现，并从 `tools/list` 获取工具名称。不要根据服务 ID 推测下游工具名。不支持的协议版本和错误的请求元数据会返回协议错误。

每个 HTTP 请求都在 Header 和 JSON-RPC 参数中镜像路由信息：

| 位置 | 契约 |
|---|---|
| `MCP-Protocol-Version` Header | `2026-07-28` |
| `Mcp-Method` Header | 准确的 JSON-RPC Method |
| `Mcp-Name` Header | Tool Call 或其他具名操作的准确编码名称 |
| `params._meta.io.modelcontextprotocol/protocolVersion` | 与 Header 相同的协议版本 |
| `params._meta.io.modelcontextprotocol/clientCapabilities` | 调用方 Capability Object，即使为空也必须提供 |
| `params._meta.io.modelcontextprotocol/clientInfo` | 可用时提供调用方名称和版本 |

Header 与参数不一致时，Gate 会在 Dispatch 前拒绝请求，使 HTTP 边界可以独立校验路由元数据。

远程部署必须使用 HTTPS。Gate 应保留在 TLS 反向代理之后的私有接口。

## 从发现到授权

```mermaid
flowchart LR
    D["发现"] --> A["规则分析"]
    A --> R["人工复核"]
    R --> P["发布分类"]
    P --> G["授权并调用"]
```

发现不等于授权。下游工具只有在以下适用检查全部通过时才可调用：

1. 调用方已认证；
2. 调用方按需要拥有 `tools.read` 或 `tools.invoke`；
3. 工具有当前、经过人工复核且已发布的读写分类；
4. 调用方拥有对应服务或工具资源授权；
5. 使用 API Token 时，其 scope 足够；
6. 该调用方已配置必需的下游凭据。

新增、变化、消失和重新出现的定义都要重新进入复核。Gate 不会根据工具名称、描述、Schema 或 annotation 推断权限。

第一方分类操作为：

- `gate_tool_classification_list`
- `gate_tool_classification_analyze`
- `gate_tool_classification_review`
- `gate_tool_classification_publish`

分析只使用本地规则并生成复核输入。复核与发布是两个独立写操作，发布必须绑定当前 fingerprint。

## 下游 Streamable HTTP

使用 `launch.type=external` 和 `transport.type=streamable_http`。Gate 发送携带每请求元数据的无状态下游请求，应用请求及启动超时，并通过 Registry 路由发现和调用。

凭据分为两层：

- `transport.headers` 中的系统 Header 通常使用 `${credential:<id>}`，应用于 Gate 的下游连接；
- Manifest 声明的 `user_credentials` Slot，只把值注入实际发起调用的认证用户独立 HTTP 请求上下文。

Gate 不会把解析后的值写入 Manifest 或 API 响应。缺少必填绑定时，请求会在到达下游 Endpoint 前失败。

## 下游 stdio

原生部署使用 `launch.type=managed_process` 和 `transport.type=stdio`。Gate 直接启动配置的可执行文件，通过 stdin/stdout 交换协议消息，捕获受限诊断输出，并跟踪期望状态和观测状态。

Stdio 约束：

- 命令、参数和工作目录必须是经过复核的本机值；
- 工作目录必须位于配置的 Allowed Root 内；
- 进程只继承配置的环境和 Gate 服务账户权限；
- Secret 使用凭据引用，只在进程启动时解析；
- 进程由用户共享，因此不能注入按用户隔离的 Secret；
- Docker Core 会拒绝受管本机进程启动。

不要把 Shell 命令行写成一个字符串。保持 `command` 和 `args` 分离，让执行边界清晰可见。

## 下游受管容器

本机容器引擎显式可用时，原生模式可以组合 `launch.type=managed_container` 与 stdio。Gate 只会启动经过复核且固定 SHA-256 Digest 的镜像，再使用其 stdio 传输。

这是使用固定执行配置的高信任管理员能力：无网络、只读根文件系统、无 Linux Capability、禁止权限提升、限制内存/CPU/PIDs，并使用受保护的临时文件系统。Bind Mount 必须使用结构化 `mounts`，保持只读，并在执行时再次确认位于 Allowed Root 内。Manifest Environment 不能控制 Gate 或 Docker CLI。Docker Core 会拒绝该 Launch Type，也不得获得容器引擎 Socket。

## 配置生命周期

Console 和 `/v1/mcp/configs` API 支持列表、校验、创建、更新、应用、重新加载和删除。`/v1/mcp/servers` 下的运行时 Endpoint 提供当前状态、详情、生命周期操作和发现的工具。

建议顺序：

1. 保存凭据，不在 Manifest 暴露值。
2. 校验 Manifest。
3. 以 `auto_start=false` 保存。
4. 复核配置 Diff 和解析到的凭据 ID。
5. 应用或启动服务。
6. 检查健康状态和发现的定义。
7. 分析、复核并发布分类。
8. 添加最小资源授权。
9. 先验证一次只读调用，再开放写权限。

删除或替换服务 ID 会影响授权、凭据绑定、运行状态和审计。应将其作为受控写操作，并先备份配置和数据。

## Gate 第一方工具

Gate 只注册属于自身控制和交付边界的操作：

| 工具族 | 用途 |
|---|---|
| `gate_system_debug` | 受限只读的概览、服务详情、日志、事件和诊断 |
| `gate_file_upload_*` | 为明确接受文件引用的调用创建用户绑定、短期有效的 `fileRef` |
| `gate_tool_classification_*` | 工具分类的列表、规则分析、人工复核和发布 |
| 项目交付 `gate_*` 工具 | 上传、构建、部署、启动、状态和工具对账 |

完整交付工具列表见 [项目交付](project-delivery.md)。第一方工具与下游工具遵循相同的认证、权限、scope 和审计检查。

## 调用和文件

REST 调用方可以通过 `/v1/tools` 检查定义，并通过文档中的 Invoke Endpoint 调用已授权工具。MCP 调用方使用 `tools/list` 和 `tools/call`。

对于明确声明支持文件引用的工具，依次调用 `gate_file_upload_begin`、`gate_file_upload_chunk` 和 `gate_file_upload_commit` 完成受限大小上传，再传递返回的短期 `fileRef`。文件引用绑定上传用户和目标上下文；Gate 不会把调用方提供的任意路径转换为本机文件系统访问。

## 失败行为

- 认证和授权失败不会到达下游服务。
- 在操作支持的情况下，发现失败会保留上一次已接受的 Registry 快照。
- 下游超时不会被报告为成功调用。
- 协议、Schema、凭据和摘要错误使用结构化响应，且不含 Secret 值。
- 运行状态会区分期望状态与观测到的进程或连接状态。
- 进程标记为 Running 不能证明工具发现已经成功。

使用 [运维](operations.md) 关联服务状态、日志、事件、诊断和调用审计，不需要开启 Payload 日志。
