# 测试外部 HTTP MCP 联通

[English](../http-mcp-connection-testing.md)

本文说明 0.5.6 的 HTTP 鉴权与联通测试。使用新增控件需要安装对应发行版本；源码更新和测试通过不会自动升级正在运行的实例。

## Console 操作

打开新建或编辑外部 HTTP MCP 配置，填写服务 ID 和 Endpoint，选择鉴权方式以及已有或新增凭据，再点击 **测试连接**。底部保留取消、测试连接、保存配置；保存前自动执行静态校验，手动校验入口位于高级配置（JSON 模式在工具栏）。网络测试可选，与保存、运行时连接和工具发布保持独立。网络请求从 Gate 所在机器发起，不是从浏览器发起。

结果分为五个阶段：配置、HTTP 联通、请求鉴权、MCP 握手、工具发现。每项明确显示通过、失败或未验证。收到 HTTP 200 不代表成功：返回登录网页或其他 HTML，不能证明 MCP 协议可用。列出工具也不证明实际调用每个业务工具时都有权限。

测试使用独立临时协议客户端，不保存草稿、不授予或撤销连接许可、不绑定待保存凭据、不启动受管进程、不改变正在运行的连接，也不发布工具。测试不会调用业务工具。修改草稿后，上次结果显示过期；尚未添加的键值行会阻止测试。测试期间阻止重复提交和常规弹窗离开。浏览器等待超时不代表远端请求已经取消。

默认测试预算为 15 秒，API 支持 1–30 秒，复用既有传输截止时间及响应大小、分页限制。单个 Core 同时最多执行两个测试；并发已满返回 `http_test_busy`，不会自动重放业务。操作系统 DNS 解析及连接清理仍受底层传输行为约束。

## 凭据与地址许可

直接选择 **无鉴权**、**Bearer Token**、**API Key**、**Basic** 或 **自定义**。选中已有凭据即将引用形式的鉴权头写入草稿，不再额外点击“添加”。无鉴权只移除可识别的鉴权头；多项、特殊结构或掩码形式保留在自定义模式，不猜测原值或静默清除。其他请求头在预设切换及表单/JSON 往返中保持不变。

**新增凭据**默认只展示名称和秘密输入；唯一凭据 ID 自动生成，可以在折叠区修改。Bearer 可以粘贴纯 Token 或带一次 `Bearer ` 前缀的内容。API Key 提供 `X-API-Key`、`Api-Key` 和自定义头名。Basic 直接填写用户名、密码，表单自动编码后通过原加密凭据接口保存；选用已有 Basic 凭据时，它应已包含编码值。Base64 不是传输加密，应使用受保护的连接。引导表单中的秘密不进入 manifest、浏览器持久存储或配置历史。写入失败保留输入，相同输入重试沿用操作标识；明确取消才清空。已保存凭据不会因取消配置编辑而删除。

凭据未完成时，保存配置和测试连接不可用，底部会明确说明是“凭据正在编辑”，不会再误报为键值未添加。切换鉴权/运行方式不能悄悄丢弃秘密输入，须先保存或明确取消凭据。选择无鉴权、自定义不会清除无关请求头。凭据列表加载失败时提供重新加载，不当成空列表。预设只允许选择服务 ID 和 origin 匹配的凭据，后端仍核对实际生命周期和实时权限。

**高级请求头**保留完整键值编辑器处理特殊配置。Content-Type、Accept 和 MCP 协议头由 Gate 生成。**Home**快捷模板选择 Bearer，展示令牌获取说明，仅对明确填写的根 URL 补充 `/mcp`。不会覆盖已有路径、猜测端口、获取令牌、修改权限或发出网络请求；通用表单不依赖特定厂商。

连接结果放在鉴权区下方，突出成功/失败、耗时和发现工具数；阶段状态同时使用图标与文字。协议版本、状态码等信息可展开查看。结果只对应本次草稿，修改后不会继续显示为当前成功。桌面弹窗最大宽度为 1200px，底部操作区独立于正文滚动区域。

凭据必须明确限定到当前服务 ID 和精确 HTTP origin。测试可以使用匹配的待保存凭据范围，但不封存该范围，也不修改凭据版本。已经绑定其他服务生命周期或地址的凭据不可复用。测试过程中，凭据版本、已保存配置或连接策略改变，会在下一次协议请求前中止。

未保存的内网 HTTP 草稿，可以通过管理员明确点击测试获得仅用于本次请求的目标许可，不会产生可复用的信任记录。已经撤销或需要复核的许可，不能通过测试恢复；删除后重建同名服务也不能绕过撤销。HTTPS 证书验证和禁止重定向保持有效。明文 HTTP 仍不加密，优先使用 HTTPS 或另外受保护的私网传输。

声明个人下游凭据槽位的配置，不使用此共享管理员测试路径，而是返回 `personal_credentials_required`。应使用调用者自己的个人连接流程，不能借用管理员或其他用户的身份。

## MCP 与 REST

新增工具为 `gate_http_mcp_test`。它是会访问网络但不修改业务数据的管理动作，需要当前管理员身份、`operations.manage` 和 `tools.invoke`；通过管理 OAuth 使用时，还需明确同意新工具及精确目标动作 `test`。旧同意不会自动扩大为测试权限；已有明确通配 scope 的管理员 API token 继续遵守原有授权语义。

以下参数使用已经创建、且使用范围正确的凭据：

```json
{
  "manifest": {
    "id": "example-home",
    "enabled": true,
    "launch": {"type": "external"},
    "transport": {
      "type": "streamable_http",
      "endpoint": "https://home.example.test/mcp",
      "headers": {"Authorization": "Bearer ${credential:example-home-token}"}
    }
  },
  "confirmed": true,
  "timeout_seconds": 15
}
```

编辑已有配置时，还要提供 `existing_server_id` 和最初读取的 `expected_config_digest`。省略它们不能把已经存在的 ID 当作新草稿。MCP 工具与 `POST /v1/mcp/external-configs/test` 复用相同应用服务和脱敏结果合同。

Console 会话需要同源、一次性且绑定整个请求体的 CSRF 票据。Console 将相同请求体先发给 `/v1/mcp/external-configs/test/csrf`，由服务端计算规范化摘要，因此内网 HTTP 页面不依赖浏览器 WebCrypto。随后将票据放入 `X-CSRF-Token` 发起测试。原有 `/external-configs/csrf?action=test&request_digest=...` 入口也可用。票据、结果和错误不得跨会话复用；专用成功响应设置 `Cache-Control: no-store`。

结果仅包含有限的阶段/错误码、HTTP 状态、耗时、协商协议和工具数量，不返回下游原始响应体或解析后的凭据。`config_saved`、`trust_changed`、`registry_changed`、`business_permissions_verified` 始终为 false。Bearer challenge 不代表服务支持 OAuth。测试可以报告服务声明了 OAuth 资源元数据，但不会自动访问不可信元数据地址、登录或获取令牌。

## 排查提示

| 结果 | 应检查的内容 |
| --- | --- |
| `authentication_required` / 401 | 令牌是否由目标服务签发、格式是否正确、是否过期或撤销；challenge 只提供鉴权方式线索。 |
| `access_denied` / 403 | 账号、动作、空间权限、Origin 规则及反向代理；不能仅凭 403 认定令牌过期。 |
| `endpoint_not_found` / 404、`http_method_not_allowed` / 405 | 真正的 MCP 路径与 POST 转发规则。 |
| `redirect_blocked` | 填写经审核的最终 Endpoint，不能通过重定向转发凭据。 |
| `tls_failed` | 修正证书链或主机名，不关闭证书验证。 |
| `network_failed` / `timeout` | 从 Gate 主机检查路由、DNS、防火墙、容器网络及下游服务。 |
| `mcp_protocol_failed` | 核对 Streamable HTTP 支持和协议协商，普通网页不等于 MCP 服务。 |
| `credential_scope_denied` / `credential_changed` | 使用当前目标范围内的凭据；状态改变后重新读取再测试。 |
| `config_changed` / `http_trust_revoked` | 重新读取原配置；需要恢复许可时，使用明确的恢复与保存操作。 |

### Home 示例

Home 0.0.2 仓库手册提供的入口是 **管理中心 → 数据源与 MCP → MCP 与访问令牌 → 创建令牌**。维护书签和页面时选择当前空间范围，不要选择仅用于推送的单一数据源令牌。Endpoint 使用 Home 实例实际显示、以 `/mcp` 结尾的地址；凭据使用该 Home 签发的 PAT。网页登录 Cookie、账号密码、GitHub Traffic 令牌都不能替代。

`navigation:read` 用于读取书签；读取首页另需 `pages:read`，包含外部数据时再需 `sources:read`。确实需要编辑书签时才增加 `navigation:write`；编辑页面另有 `pages:write` 及绑定数据的读取要求。Home 会在实际调用时检查账号、空间和操作范围，发现工具不能证明全部权限已经通过。

依据：[Home 使用手册](https://github.com/zhigege666/Lingshu-Home/blob/main/docs/USER_GUIDE.zh-CN.md)、[Home API 合同](https://github.com/zhigege666/Lingshu-Home/blob/main/docs/API.md)、[Home MCP 实现](https://github.com/zhigege666/Lingshu-Home/blob/main/server/internal/home/integrations_mcp.go)。部署版本需另行核对；源码核对和隔离测试服务成功，不等于真实生产 Home 已完成登录验收。
