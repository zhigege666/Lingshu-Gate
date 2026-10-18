# 标准指标与链路追踪

[English](../telemetry.md) · [文档索引](README.md)

Gate 可提供进程内 Prometheus 聚合指标，并把标准 OTLP/HTTP protobuf trace 导出到现有观测服务。指标与 trace 独立开关，**默认均关闭**，不需要 GitHub Traffic 采集器或客户端插件。

## 配置 Gate 进程

将 `LINGSHU_GATE_TELEMETRY` 设置为 JSON 对象并重启。仅启用指标：

~~~bash
export LINGSHU_GATE_TELEMETRY='{"metrics_enabled":true}'
~~~

同时启用 trace：

~~~bash
export LINGSHU_GATE_TELEMETRY='{"metrics_enabled":true,"traces_enabled":true,"otlp_endpoint":"https://telemetry.example/v1/traces","otlp_token_file":"/run/gate/otlp-token","otlp_ca_file":"/run/gate/telemetry-ca.pem","sample_ratio":1.0}'
~~~

| 字段 | 默认 | 约束 |
|---|---|---|
| `metrics_enabled` | `false` | 布尔值，启用本进程聚合 |
| `traces_enabled` | `false` | 布尔值，在应用生命周期中创建私有 SDK 导出线程 |
| `otlp_endpoint` | 空 | trace 启用时必填完整路径；远端 HTTPS 或明确回环 HTTP |
| `otlp_token_file` | 未配置 | 可选采集端 Bearer 令牌的绝对文件路径 |
| `otlp_ca_file` | 未配置 | PEM CA 绝对路径，未配置使用正常证书校验 |
| `sample_ratio` | `1.0` | 0 到 1 的有限数字 |

未知字段、重复 JSON 键及非法值使配置加载失败，错误文本固定。地址不能包含用户凭据、query 或 fragment。Gate 不自动追加 `/v1/traces`，也不发现采集端。启用观测不会增加或触发业务重试；既有单次只读会话恢复重试规则保持不变。

POSIX 令牌文件须为当前用户拥有的普通文件，group/other 权限为零，使用 `0400` 或 `0600`；Windows 要求可验证的受限 ACL。它是受保护的本地明文文件，不会自动进入 Gate 加密凭据库。

Compose 模板已显式透传变量。在部署环境文件中填写相同的单引号 JSON，并通过覆盖文件只读挂载 token/CA 到对应容器路径：

~~~yaml
services:
  core:
    volumes:
      - /srv/gate/otlp-token:/run/gate/otlp-token:ro
      - /srv/gate/telemetry-ca.pem:/run/gate/telemetry-ca.pem:ro
~~~

token 的宿主属主应匹配 Core UID `10001`，权限为 `0400`；默认 `0444` Docker secret 不符合此令牌边界。只启用指标无需导出凭据，不必挂载 secret。

## 抓取与状态

| 入口 | 返回 |
|---|---|
| `GET /v1/observability/metrics` | Prometheus 0.0.4 文本，`Cache-Control: no-store` |
| `GET /v1/observability/telemetry` | 安全的队列/导出状态 JSON，`Cache-Control: no-store` |

必须真实认证，并且同时拥有 **`operations.manage` 与 `observability.read.all`**，继续受 token/委托 scope 限制。指标关闭时在认证前返回 404；两项均关闭时状态也返回 404。关闭 Gate 认证不会公开全局指标。

使用仅含所需两项 scope 的专用凭据。它**并非全局只读令牌**，因为 `operations.manage` 还允许既有运维写操作。指标入口应留在私有控制面；外部 MCP OAuth 凭据不会因此获得 REST 认证能力。

## 指标含义

| 指标族 | 含义 |
|---|---|
| `gate_http_total` / `gate_http_duration_seconds` | 完成的 HTTP 请求，固定路由模板、方法、结果 |
| `gate_tool_total` / `gate_tool_duration_seconds` | 进入 Access 的逻辑工具调用，入口、传输、结果 |
| `gate_execution_total` / `gate_execution_duration_seconds` | 实际 handler/下游尝试，首次或重试、传输、结果 |
| `gate_telemetry_pending`、`gate_telemetry_inflight` | 排队和正在导出的 span 数 |
| `gate_telemetry_spans_total` | HTTP 接受、失败或丢弃数 |
| `gate_telemetry_traces_ready`、`gate_telemetry_shutdown_timed_out` | 追踪可用状态和关闭超时 |

耗时为秒制 histogram，计数随进程重启归零。拒绝调用可能没有实际执行；一次读取恢复可能包含两次尝试、一次成功逻辑调用。MCP 协议错误及 `isError` 即使 HTTP 200 也不会计为成功。三类调用数不能相加。

未知路由统一为 `unmatched`，未知方法为 `other`。工具、用户、服务 ID、凭据、参数、结果、任意 URL 和关联 ID 均不作为标签。span 使用固定阶段名和小型属性白名单，不记录自动异常文本、堆栈、请求正文、query、token 或结果；审计正文仍由独立的调用保留设置管理。

## 上下文与故障行为

Gate 接收单个有界 W3C `traceparent`，向直接 Streamable HTTP 下游注入当前 traceparent，不转发 `baggage` 和 `tracestate`。单个 UUID 或 32 位十六进制 `X-Correlation-ID` 与审计共用并回传；非法、重复值会替换。配置中的请求头不能覆盖 Gate 上下文头；伴随服务的转发范围由其自身协议决定。

每个实例拥有私有 SDK provider，不设置全局 provider，也不采用环境中的 exporter 地址、认证、代理、CA、Resource 或 sampler。标准 SDK 的 `OTEL_SDK_DISABLED=true` 仍会禁用 trace，并明确显示 `sdk_environment_disabled`，不会误报 ready。

固定容量为**排队与导出中合计 1,024 个 span**，批次 **64**、调度间隔**一秒**。满时丢弃新观测并计数。连接失败、异常采集端响应和初始化失败不会拒绝、重放或改变业务调用；状态入口提供固定失败代码。

导出启用证书校验、禁止重定向、环境代理/netrc 和 Cookie 复用，HTTP timeout 配置为两秒；这不是 DNS 或总墙钟时间的严格截止。关闭最多等待一秒，超时后返回并报告状态；关闭尽力而为，可能丢失待导出数据。

`export_accepted_spans` 仅表示接受了 HTTP 2xx，不证明永久存储；本实现不解析 OTLP `partial_success` 正文。数据保留、看板和告警在外部观测服务配置。
