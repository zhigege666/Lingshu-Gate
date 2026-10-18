# 连接私网 HTTP MCP

[English](../private-connector.md) · [文档索引](README.md)

连接器通过出站 WebSocket，把**固定的一组 HTTP MCP 目标**接入可达的 relay。私网主机运行 agent，relay 分别验证 agent 和 Gate consumer 身份。这是工具桥接，不是 SSH、SOCKS 或任意 TCP 代理。

## 三条独立信任关系

将 [relay.json](../../examples/connector/relay.json)、[agent.json](../../examples/connector/agent.json) 复制到源码仓库外，填写真实证书、CA 和令牌路径。

| 凭据 | 使用链路 | 权限 |
|---|---|---|
| Agent 令牌 | 私网 agent → relay | 只注册自己的目标 ID |
| Consumer 令牌 | Gate → relay | 只调用显式允许的目标 |
| 可选上游令牌 | Agent → 私网 HTTP MCP | 验证固定上游身份 |

为 agent、consumer 分别生成至少 32 个 ASCII 字符的随机令牌，各存独立受保护文件；relay 所有身份的令牌必须不同。POSIX 文件须属于运行用户，普通文件，权限 `0400` 或 `0600`，group/other 无权限；Windows 要求可验证的严格 ACL。这些是本地明文文件，不会自动进入 Gate 加密库，不能提交 Git。

每个目标只有一个 agent owner。Agent 和 consumer 都使用明确允许列表，调用者不能指定任意地址、选择别的 agent 或借用另一 consumer 的会话。保持 relay 与 agent 时钟同步：请求同时携带相对超时和绝对 UTC 到期时间。

## 启动

~~~bash
lingshu-gate connector relay --config /etc/gate-connector/relay.json
lingshu-gate connector agent --config /etc/gate-connector/agent.json
~~~

原生包使用可执行文件路径，源码使用 `uv run lingshu-gate`。远程监听必须配置 TLS 证书/私钥与精确 `allowed_hosts`，包含客户端使用的端口。远程连接使用 `wss://…/connector/agent`；浏览器 Origin 需要独立精确允许列表，普通后台进程通常不发送 Origin。

Agent 目标固定为 HTTPS、回环 HTTP，或通过 `allow_private_http` 明确允许的私网**字面 IP** HTTP。内网 DNS 名不会自动获得明文信任。私有 CA 显式配置，始终校验证书，不采用环境网络代理。

agent 和 status 命令的 CA 配置不作用于 Gate Core，relay 证书还必须被 Gate 进程信任。使用私有 CA 时须另外加入 Gate 主机/容器的信任库；Core Manifest 没有 CA 文件字段。将示例 relay/目标地址替换为实际地址；保留 18880 端口回环目标时，先在 agent 主机启动演示服务。

在 Gate 凭据库保存 consumer 令牌，依据[relay 目标配置](../../examples/mcp.d/connector.yaml)建立外部 Streamable HTTP 服务，把 `credential:connector-consumer` 换成实际凭据 ID。依次校验、保存、应用、启动、审核分类、发布及授权；连接器不代替任何 Gate 授权步骤。

通过 consumer 的受保护文件检查状态：

~~~bash
lingshu-gate connector status --url https://relay.example:18882/connector/status --token-file /run/gate/consumer-token --ca-file /etc/gate-connector/relay-ca.pem
~~~

只返回当前 consumer 的目标 ID、连接和心跳状态、进行中请求数、最近交换的状态/错误码及会话数，不返回令牌、参数和响应正文。修改配置需要重启对应服务进程，并刷新 Gate 下游连接。

## 协议与故障边界

Relay 提供 WebSocket `/connector/agent`、`POST` / `DELETE /connector/mcp/{target}`、`GET /connector/status`。支持 `server/discover`、`initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`，可处理有界、匹配请求的 SSE POST 回复；不提供通用 resources、prompts、反向服务器请求或 GET/SSE 隧道。

请求最多 **1 MiB**、响应 **8 MiB**、帧 **12 MiB**；每 agent 连接最多 **16** 个进行中请求，全局 **64** 个、最多 **64** 个目标。Opaque 会话绑定 consumer、目标、合同版本和连接代际，一小时空闲过期。超限或过期明确失败。

超时、断线可能代表**上游结果未知**。连接器不自动重试、重放业务请求；再次写入前应对账原操作。WebSocket 重连只恢复传输，新代际使旧会话失效。上游 DELETE 返回 405 时 relay 仍释放本地映射，但不声称已停止上游进程。

不透明转发凭据、Cookie 或任意请求头；拒绝重定向，累积正文前执行大小限制。伴随进程由管理员显式作为独立服务运行，Core 不暗中启动 agent 或创建公网入口。
