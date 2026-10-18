# 将选定 OpenAPI 操作转换为 MCP 工具

[English](../openapi-adapter.md) · [文档索引](README.md)

适配器把本地 OpenAPI 快照及显式操作允许列表编译为 MCP 工具。它独立运行，Gate 作为外部 Streamable HTTP 下游接入，继续执行分类审核和授权流程。

## 校验固定合同

[最小 schema](../../examples/openapi/status.openapi.yaml) 与[配置](../../examples/openapi/adapter.json)选择占位 HTTPS 服务的一项操作。请替换为自己的真实服务地址；示例不会替你启动 HTTP API。

~~~bash
lingshu-gate openapi validate --schema examples/openapi/status.openapi.yaml --config examples/openapi/adapter.json
~~~

校验只读本地文件，返回生成名称、operation ID、方法/路径、输入 schema、所需凭据引用及合同摘要，不执行业务。选中操作不存在、未知配置、不支持的 schema 或未使用凭据绑定均拒绝。

字段为 `schema_version: 1`、`base_url`、`operations`、可选 `credentials` 和 `allow_private_http`。操作列表为 1–200 个不重复 operation ID。配置的 base URL 是唯一目标，不支持 server variables 或远程 schema 获取。远端要求 HTTPS；允许回环 HTTP，私网字面 IP 的 HTTP 需显式启用。

## 绑定凭据并启动

若 OpenAPI Bearer scheme 名为 `serviceAuth`，在 `credentials` 下填写：

~~~json
{
  "serviceAuth": {
    "type": "bearer",
    "reference": "status-service",
    "token_file": "/run/gate-adapter/status-token"
  }
}
~~~

只选择使用该 scheme 的操作；header API key 使用 `type: "api_key"`。文件遵循[连接器](private-connector.md)同样的 POSIX 属主专用权限或 Windows 可验证 ACL 约束。上游令牌与可选入站 MCP 令牌、Gate 凭据库相互独立。

启动已校验快照：

~~~bash
lingshu-gate openapi serve --schema examples/openapi/status.openapi.yaml --config examples/openapi/adapter.json --host 127.0.0.1 --port 18881
~~~

源码使用 `uv run lingshu-gate`。Gate 按[适配器配置](../../examples/mcp.d/openapi.yaml)接入，依次保存、应用、启动、审核、发布工具，再授予调用者权限。

非回环监听必须同时提供 **`--tls-cert`、`--tls-key`、`--token-file`、精确 `--allowed-host`**；host 和 origin 参数可重复。`--ca-file` 配置上游 API CA，不替代监听证书。入站与上游令牌独立，不公开未认证监听。

## 合同与支持范围

工具名由有界 operation ID 前缀和 SHA-256 执行合同摘要组成。Base URL、方法/路径、参数、响应或凭据引用变化形成新身份，需要重新发现与审核；轮换令牌文件内容不会把权限转移给另一引用。没有后台自动刷新 schema。

指定工具授权快照不会转移到新工具身份。审核/发布后，既有持续策略只能在原先确认的服务/读写范围、当前账号权限及相同服务生命周期内纳入新合同；信任目标变化须重新确认。

支持 **OpenAPI 3.0.x / 3.1.x** 的有限子集：

- 支持约定序列化的 path/query/header 参数与 `application/json` 正文。
- 本地非循环 `#/components/schemas/…` 引用；原始值、对象、数组及已支持的 type/property/required/enum/const、范围、长度、项数约束。
- 归一化 3.0 nullable 与 exclusive bounds。
- 声明的成功 JSON、text/plain、空响应；检查状态及媒体类型，不提供通用响应 schema 校验。
- 固定文件绑定的 Bearer 或 header API key。

不支持远程/循环引用、子集外 composition、任意 schema 方言、OAuth 协商、Cookie、form/multipart 上传、callbacks、webhooks。不支持的输入返回结构化错误，不静默忽略。

Schema 最多 **2 MiB**、配置 **64 KiB**、单工具定义 **128 KiB**、定义合计 **4 MiB**。调用固定目标，禁止重定向、环境代理和 Cookie 复用；最多 **16** 个并发、**30 秒**超时、响应 **8 MiB**。路径/query 参数不能替换来源地址或逃离 base path。失败/超时不自动重放，写入重试前先对账。

上游自身授权仍必需；注解和生成工具不会直接授予权限。没有上游 API 时，可先使用[第一次调用](first-call.md)完成可运行的本地网关演示。
