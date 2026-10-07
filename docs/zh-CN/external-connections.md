# 外部 OAuth 资源访问

[English](../external-connections.md)

Gate 提供[复用已有用户的内置 OAuth](builtin-oauth.md)与**默认关闭、仅用于 `/mcp` 的外部 JWT 资源服务器**。本文描述外部身份提供方模式。管理员配置可信签发者、公钥地址、客户端 ID、资源映射及身份绑定；用户启用受限的本地个人委托。启用外部模式记录不会签发 OAuth 令牌、完成 provider 同意流程、启动隧道，也不证明已连接 ChatGPT。`connected=false`、`provider_verified=false` 和 `oauth_authorized=false` 保留这些边界。没有外部身份提供方时选择内置 OAuth。

只有 `/mcp` 接受外部 JWT。`/v1/*`（包括个人摘要、令牌创建及本文管理 API）仍要求 Gate session 或 Gate API 令牌。无效或格式错误的 Authorization 不会回退到有效 session cookie。不支持 opaque 外部访问令牌或 introspection。

## 选择网络接入路径

Gate 仅有两种启用的外部接入类型：`secure_mcp_tunnel` 和 `direct` HTTPS；`disabled` 表示关闭。Cloudflare、frp、Nginx Proxy Manager 和 ngrok 都是**运维人员管理的网络方案**，不是额外 Gate 模式。Gate 不安装、配置、托管这些 daemon，也不轮换其凭据。下列示例是拓扑/配置占位说明，不是待执行命令；网络与身份检查完成前保持外部接入关闭。

| 网络方案 | Gate 模式 | 可达性与维护责任 |
|---|---|---|
| Secure MCP Tunnel | `secure_mcp_tunnel` | 官方客户端部署在私网 Gate HTTP 监听器旁，主动连接控制面；客户端和隧道生命周期由运维负责。 |
| Cloudflare named tunnel | `direct` | 运维管理 `cloudflared`，以稳定 HTTPS 主机名连接私有源站。 |
| frp 加公网 Nginx Proxy Manager | `direct` | 私网 `frpc` 连接公网 `frps`，公网 TLS 代理只将获准路径转发至受限映射端口。 |
| 已有公网反向代理 | `direct` | 公网 HTTPS 代理通过已有私网路由、VPN 或明确配置的端口转发访问 Gate。 |
| ngrok，可选 | `direct` | 运维管理的端点转发至私有 Gate；使用适合资源及 OAuth 注册配置的稳定 HTTPS 地址。 |

### 官方客户端的私有隧道

参考 [Secure MCP Tunnel 官方指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)与[官方客户端仓库](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)。适用拓扑为 `ChatGPT → 托管隧道 → 官方客户端 sidecar → Gate HTTP /mcp`。客户端所在主机需要出站 HTTPS 443 访问官方指南列出的 API 主机；启用控制面 mTLS 时使用指南对应的 mTLS 端点。这条路径不要求 Gate 开启公网入站监听。

同机 sidecar 的目标可写作 `http://127.0.0.1:<GATE_PORT>/mcp`，但这是**本地目标占位**，不是 Gate 对外资源 URL。不同容器拥有不同 loopback；应填写真实私网服务地址、限制网络，跨不可信边界时使用 TLS。从真实管理页取得 tunnel ID 与端点，选择并固定已审查兼容的客户端版本，不沿用旧 release 编号。不要公开客户端管理 UI。[客户端配置参考](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)说明 HTTP 目标、sidecar 启动等待、secret 引用及单独受信的 OAuth discovery origin。

隧道运行 API key 验证共享机器通道，**不代表 ChatGPT 最终用户**。由运维秘密存储管理，不能与个人 Gate API 令牌或下游凭据混用；Gate 仅保存配置引用。隧道改写受保护资源 URL 后，必须将实际公布的 audience 显式映射至 `canonical_resource_url`，不能关闭 audience 校验。provider 浏览器授权页仍须独立可达。不要假定 discovery 携带用户 bearer，也不能把隧道就绪当作用户已同意授权；应核对选定版本的[配置合同](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)。

### 直连 HTTPS 方案

- **Cloudflare named tunnel：**创建持久隧道，把稳定主机名路由到受限源站。运维运行 [cloudflared](https://github.com/cloudflare/cloudflared)，其[主动出站连接模型](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)不要求源站具有公网 IP。明确配置[应用路由](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/)和路径限制。独立的边缘登录页不能悄然替换 Gate MCP bearer 合同；增加边缘认证时须测试客户端兼容性。不要把临时 quick tunnel 地址当作持久 audience 或回调地址。
- **frp → 公网 Nginx Proxy Manager：**私网 `frpc` 连接运维控制的公网 `frps`，再由 [Nginx Proxy Manager](https://nginxproxymanager.com/) 的 HTTPS 主机转发至受限 upstream。[frp 仓库](https://github.com/fatedier/frp)说明 NAT 穿透和传输 TLS；这与浏览器/客户端面对的 HTTPS 证书是不同边界。映射后端端口只允许代理访问，两者管理入口保持私有，并在公网代理配置主机名/证书。NPM 自身安装参考[官方指南](https://nginxproxymanager.com/guide/)。监听端口、映射端口和容器网络值均需按部署填写，不是 Gate 提供的一键组合栈。
- **已有公网代理：**在已可达代理终止经过验证的 HTTPS，并提供代理到 Gate 的路由。反向代理本身不能穿越 NAT，必须已有公网地址、明确端口映射、VPN 或出站隧道；证书本身也不能提供网络可达性。
- **ngrok，可选：**[HTTPS 端点文档](https://ngrok.com/docs/gateway/endpoints/http)说明 agent 端点及托管 TLS 终止。将其地址作为受信资源前，确认主机名稳定性、适用限制、空闲超时和中间认证。Gate 不管理 ngrok 账号或 agent。

### 公网暴露面与代理合同

仅公开 MCP 资源及必要 discovery 路径：`/mcp`、`/.well-known/oauth-protected-resource`、`/.well-known/oauth-protected-resource/mcp`，只转发部署中 MCP transport 实际支持的方法。**不要**在该外部 MCP 主机公开 Console、`/v1/*` 管理 API、`/docs`、`/openapi.json`、诊断端点或代理/隧道管理面板。其他路径明确拒绝或默认 404；Console 保留独立私有管理路径。授权 provider 自己负责浏览器 authorize、token、JWKS 端点，不能为了 OAuth 而公开 Gate 管理面。

`direct` 的 `endpoint` 填写精确公网 HTTPS `/mcp` URL，将接受的 audience 显式映射到 Gate 规范 HTTPS 资源。保留 `Authorization`、使用中的 MCP 协议/会话 header、`WWW-Authenticate` 及 discovery 响应体；不要向所有请求注入一个共享 Gate API token。discovery 不能借用用户下游凭据。`LINGSHU_GATE_TRUSTED_PROXY_IPS` 只填写实际直接代理地址或最小可信 CIDR，不使用无限制 `*`；代理须替换可伪造的转发 header。参见[部署要求](deployment.md#反向代理要求)。

协商的 transport 使用流式响应时，关闭相关响应缓冲/缓存，实际验证 SSE 交付、断连和会话清理；普通 JSON 请求成功不能证明流式链路成功。连接、读取与空闲超时应有上限并容纳预期操作。写入超时后先检查记录结果，不盲目重试。公网及受信 provider 链路维持正常 TLS 证书校验。边缘限制与客户端版本兼容性需要部署测试，本指南不宣称第三方代理已通过 Gate 联调。

### 分阶段实测后再启用

1. 记录选定拓扑、精确公网资源、规范资源/audience 映射、受信 issuer/JWKS 和允许的 OAuth client ID。回调及注册值使用当前 provider/客户端真实管理页，不使用旧示例。初始保持 Gate 外部配置关闭。
2. 核验网络/TLS、无用户认证的 discovery 与认证 challenge，并确认 MCP 主机无法访问管理/Console 路径。provider 浏览器授权路径单独验证，不把真实 bearer 或秘密 header 写入证据日志。
3. 将经过验证的 provider `(issuer, subject)` 绑定专用 Gate 测试用户，分配有限 Gate 资源及**只读**个人外部授权。验证获准读调用和过滤后的 `tools/list`；猜测未授权工具 ID，证明拒绝且下游调用次数为零。
4. 读验证通过后，再为安全合成动作开启有限写授权。证明交集之外仍不能写入，包括管理员委托令牌：Gate 资源、个人委托与 JWT scope 都必须允许。验证不能使用另一用户的授权或下游凭据。
5. 停用、撤销、使测试授权到期，或移除其 Gate 资源权。复用旧 token/session，验证**下一次**请求被拒绝，不承诺取消已经派发的工作。测试配额拒绝、超时处理和流式恢复，不盲重放写入。
6. 分别记录传输、真实 provider OAuth 和真实 Gate 权限结果。本地 `enabled`/就绪状态不证明 provider 同意或连通。实际启动隧道、公开路由、注册 provider 与持久凭据仍是须独立授权的部署操作，本次文档更新未执行这些动作。

上述官方网络资料核实于 2026-10-01。未下载或运行客户端二进制，本指南不认证任何 release。

## 信任配置

`external_connections.manage` 控制 `GET/PUT /v1/auth/external-connection/config` 及身份绑定管理，内置管理员默认拥有该能力。需 Gate 身份的 `GET /v1/auth/external-connection` 仅返回就绪状态，不暴露共享运行秘密引用。Gate 鉴权必须保持启用。

配置持久化在 SQLite，通过已鉴权 API 修改。`LINGSHU_GATE_EXTERNAL_CONNECTION_ENABLED=true` 仍会使启动失败，不能通过环境变量绕过管理 API。PUT 要求 `expected_revision`（初始为 `0`），版本过期返回 `409`。未知字段及原始秘密/令牌字段会被拒绝。关闭状态允许配置不完整；`enabled=true` 要求完整信任合同。

以下为使用文档专用域名的**关闭状态**直连资源配置：

```json
{
  "expected_revision": 0,
  "enabled": false,
  "mode": "direct",
  "endpoint": "https://gate.example.test/mcp",
  "canonical_resource_url": "https://gate.example.test/mcp",
  "trusted_issuers": ["https://identity.example.test"],
  "issuer_jwks": [["https://identity.example.test", "https://identity.example.test/jwks"]],
  "client_allowlist": ["example-client"],
  "resource_mappings": [["https://gate.example.test/mcp", "https://gate.example.test/mcp"]]
}
```

| 字段 | 含义 |
|---|---|
| `mode` | `disabled`、`direct` 或 `secure_mcp_tunnel`；选择隧道模式不会运行隧道 |
| `endpoint` | 对外 HTTPS 资源地址；直连模式必填 |
| `canonical_resource_url` | Gate 的规范资源标识；省略时使用 `endpoint` |
| `trusted_issuers` / `issuer_jwks` | 精确 issuer 字符串及每个 issuer 对应的管理员固定 HTTPS JWKS 地址 |
| `client_allowlist` | 精确允许的 `client_id`/`azp` 值 |
| `resource_mappings` | 对外 audience 到规范资源的精确映射；所有目标须等于本部署的规范资源 |
| `tunnel_reference` / `runtime_secret_reference` | 隧道模式就绪要求的 `tunnel:ID` 和 `credential:ID` 引用，不接受原始运行秘密 |

资源、issuer 和 JWKS 地址必须使用 HTTPS，不能带用户名密码、query 或 fragment。重复或歧义资源映射会被拒绝。请求 Host 头或令牌内 URL 不能建立信任。配置就绪只校验本地合同，不是 provider 或网络探测。

启用且配置有效时，`/.well-known/oauth-protected-resource` 和 `/.well-known/oauth-protected-resource/mcp` 返回规范资源、配置的授权服务器及支持 scopes；关闭或未就绪时返回 `404`。MCP 鉴权 challenge 使用受信配置的资源 origin，不使用请求 Host 头。

## 身份绑定与个人委托

管理员接口：

- `GET/POST /v1/auth/external-subject-links` 查询/创建包含 `issuer`、`subject`、`user_id` 和 `enabled`（默认 `false`）的绑定。issuer 必须已受信任，目标 Gate 用户必须有效。

绑定列表支持服务端 `q`、`offset`、`limit` 搜索与分页，包含 Gate 显示名称、用户名和稳定 ID。每个绑定包含最小 `user` 摘要；无法解析的用户保留关联 ID，不推断名称。`GET /v1/auth/external-subject-links/user-options` 使用相同的 `external_connections.manage` 能力，仅返回用于绑定的有效用户标签，不返回角色或凭据数据。创建或启用绑定时重新检查目标用户状态。Console 优先显示名称和用户名，下方 ID 可复制。本变更不改变现有删除用户的级联行为。

- `PATCH /v1/auth/external-subject-links/{id}` 用 `expected_revision` 修改 `enabled`，不会静默改绑身份。
- `DELETE /v1/auth/external-subject-links/{id}` 停用绑定。重复身份分配、未知绑定和版本冲突会明确失败。

已验证的精确 `(iss, sub)` 通过当前已启用绑定解析到有效 Gate 用户。令牌自报的用户 ID、邮箱或 grant ID 不能选择身份。

`credentials.manage.self` 控制个人 `GET/POST /v1/auth/external-grants` 及 `GET/PATCH/DELETE /v1/auth/external-grants/{id}`。包括管理员在内，每个请求都仅访问本人记录，猜测他人 ID 返回 `404`。字段为 `enabled`（默认 `false`）、`client_id`、精确 `server_allowlist`/`tool_allowlist`、`access`（`read`/`write`）、带时区的未来 `expires_at`、`rate_per_minute` 和 `concurrency`。资源 ID 不允许通配符。

保存范围时，将当前已发布工具与当前 Gate 能力、资源授权及调用者的 token/委托上限求交集。未知或无权资源返回 `403`，不泄露名称。启用还要求完整且已启用的信任配置、允许的客户端和已启用身份绑定，缺少前提返回 `409`。每个用户/客户端只能匹配一个未过期、未撤销的启用授权。多个受信 issuer 中显式绑定到同一 Gate 用户的身份可共享该用户/客户端委托，不会按邮箱自动合并身份。PATCH 需要 `expected_revision` 并推进策略版本；停用专用 PATCH 只需 `enabled=false` 与版本，因此资源权限丢失不会阻止停用。DELETE 撤销授权，重复撤销幂等，已撤销记录不能编辑。

后续经批准的设置顺序为：配置受信关系、将 provider subject 绑定 Gate 用户、审核发布工具并分配普通 Gate 权限，再启用该用户面向指定客户端的委托。provider 同意与令牌签发由 Gate 外部完成。用 `activation_errors`、`scope_currently_authorized` 和记录 `state` 检查本地就绪状态；`limits_enforced=true` 表示当前有效启用的本地授权执行配额，非有效记录为 false；它不代表 provider 同意，启用记录也不等于外部登录或连接成功。

## JWT 验证与权限

验证器使用 [PyJWT 的签名与 claim 验证](https://pyjwt.readthedocs.io/en/stable/api.html)，固定算法允许列表。当前只接受 RS256 及至少 2048 位 RSA 签名公钥。要求 `kid`、精确 `iss`、非空 `sub`、`aud` 和 `exp`；存在 `nbf`、`iat` 时也校验。`typ` 须表明访问令牌用途：接受 `at+jwt`；`JWT`（包括省略 header type）还须有已签名的 `token_use=access` claim。显式 `token_use=id` 或其他用途会被拒绝。包含 `jku`、`x5u`、内嵌 `jwk` 或 `crit` 的 token header 会被拒绝。

令牌中的每个 audience 都必须精确映射到配置的规范资源。`client_id` 或 `azp` 必须是允许的客户端，两者同时出现时必须一致。`scope` 必须为空格分隔的字符串。发现元数据公布 `tools.read` 和 `tools.invoke`；兼容的 `mcp.read`/`mcp.write` 名称保留现有 Gate 语义。任何 scope（包括 `*`）都不能扩大普通 Gate 权限或本地委托。

JWKS 只从固定 HTTPS 地址获取，正常校验 TLS，获取操作设置覆盖 DNS/header/body 的五秒期限及 256 KiB/64 个 key 上限；等待 issuer 刷新锁另限五秒。最多运行两个 daemon 获取线程且不排队，槽位耗尽时拒绝；不发送 bearer、不跟随重定向、不继承代理配置，也不请求令牌提供的 URL。公钥缓存 300 秒，未知 key 最短隔 30 秒尝试刷新；过期缓存刷新失败时拒绝鉴权。这是公钥缓存策略，不承诺 issuer 端撤销密钥立即生效。

最终工具权限为**当前 Gate 角色/资源授权 ∩ 本地委托 ∩ 已验证 JWT scopes ∩ 已发布工具策略**。`tools.read` 允许获准只读调用，写调用要求 `tools.invoke`。OAuth 管理员不能绕过委托上限或未发布分类。发现结果先过滤无权工具，再返回名称和计数；猜测调用目标会在下游派发前拒绝。每个请求重新读取绑定、有效用户和授权，停用、到期和撤权影响下一次请求，不追溯取消已派发工作。

OAuth 调用配额按 grant 在下游派发前执行：已准入调用使用滑动 60 秒限流窗口，并发槽位在 `finally` 释放。超限返回协议工具错误且下游调用次数为零。计数仅在单 Core 进程内存中维护，重启后重置，也不跨进程协调；普通角色/资源判权与配额检查均必须通过。

## 外部接入边界

[Secure MCP Tunnel 指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) 描述私网传输。隧道运行 API key 不代表最终用户，须与个人 Gate API 令牌及个人下游凭据分开。用户 Authorization 用于 MCP 主路径，隧道 discovery 是独立通道。隧道资源 URL 改写要求显式受信 audience/规范资源映射；隧道不会自动托管 provider 浏览器授权页。共享下游连接成功也不能证明某个用户的下游凭据认证成功。

本实现不运营授权服务器、不签发 provider 令牌、不支持 opaque introspection、不托管 provider authorize/PKCE 流程、不执行 CIMD/DCR/客户端注册，也不会下载或启动隧道客户端。真实 provider discovery、回调/客户端配置、外部 HTTPS/TLS 部署及 ChatGPT/Tunnel 连接仍须另行联调验证。使用真实 provider/客户端管理页面值，不将示例回调视为已认证设置。引入 job、fileRef、结果和审计路径时仍须分别验证用户隔离；本改动不宣称新增 OAuth job/file API。写请求超时不得盲目重试。

## 可重复验证

```bash
timeout 120 uv run pytest -q tests/test_external_connection.py tests/test_external_connection_management.py tests/test_delegated_access_scope.py tests/test_external_jwt_verifier.py tests/test_external_oauth_http.py
```

策略与管理测试覆盖关闭默认值、版本前提、权限交集、身份/授权归属及撤权。`tests/test_external_jwt_verifier.py` 单独检查 RSA/JWT 验证与生产 JWKS 获取路径的资源边界。`tests/test_external_oauth_http.py` 使用合成签名 JWT、真实本地 Gate HTTP 服务、本地 JWKS HTTP 服务及带调用计数/个人凭据的下游 HTTP peer；注入的 JWKS fetcher 仅把固定受信 HTTPS 测试 URL 映射到本地 HTTP peer。它**不验证**生产 HTTPS 证书链、真实 OAuth provider、浏览器授权码交换或隧道。实际测试结果与已实现覆盖范围必须分别报告；mock Console 测试和此前导航截图不能替代 OAuth 验收。

其他参考：[ChatGPT 鉴权](https://developers.openai.com/plugins/build/auth)、[tunnel-client 配置](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)、[connectors](https://github.com/openai/tunnel-client/blob/master/docs/connectors.md) 及 [MCP 授权](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)。后续部署须固定并验证客户端兼容性；本次源码变更不认证任何客户端 release。

## 控制台接入引导

进入 **连接基础设施 → 接入引导**。四步将说明放在字段旁：接入方式、令牌验证、用户绑定/授权、检查验证。“保存配置并继续”明确保存草稿；启用外部令牌验证仍需独立确认。已保存配置以服务端为准；浏览器会话仅记住步骤编号，不悄悄保存表单或秘密，离开前保护未保存输入。已部署实例可直接“编辑验证配置”。

配置值从哪里取得：

- **Cloudflare：**控制台 → Networking → Tunnels → 目标隧道 → Routes → Add route → Published application。Service URL 填 Gate 内网地址；公开域名加 `/mcp` 填外部接入地址。参照[官方控制台指南](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)并限制公开路径。
- **Issuer/JWKS：**从身份提供方发现文档读取 `issuer`、`jwks_uri`。Keycloak 的 `/realms/{realm-name}/.well-known/openid-configuration` 见[端点指南](https://www.keycloak.org/securing-apps/oidc-layers)。客户端 ID 来自登记的集成应用，不是客户端密钥；核对 JWT 的 `client_id`/`azp`。Gate 要求 RS256 和固定受信 HTTPS JWKS 映射。
- **隧道：**通过[官方指南里的 Platform tunnel settings](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)取得实际隧道 ID，关联目标工作区并确认组织级 Read + Use 权限。运行秘密保存在运维秘密存储，Gate 只填写引用。
- **ChatGPT：**按 2026-10-01 核对的文档，开发者模式在 Settings → Security and login；从 ChatGPT Plugins 添加开发者应用，按方案选择 URL 或 Tunnel。账号或工作区策略影响入口时参照[当前连接指南](https://developers.openai.com/plugins/deploy/connect-chatgpt)。

最后一步只检查已保存配置，不探测提供方、不启动隧道、不签发令牌，也不宣称 OAuth 已连接。还需独立验证工具发现和只读工具调用，再关联审计记录。401 可从令牌/信任校验排查；403 检查身份绑定、个人授权、工具发布状态和用户有效权限。这些只是排查起点，不能据此断定某次失败的真实原因。
