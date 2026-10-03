## Lingshu Gate v0.4.1

### English

0.4.1 fixes authorization requests carrying `ui_locales` and improves sign-in
version visibility, built-in OAuth setup and personal grant review.

- Accept a bounded optional `ui_locales` preference list, choose a supported
  English/Simplified Chinese UI hint, and preserve the existing preference for
  unsupported languages. Keep this hint outside the authorization ticket;
  unknown/duplicate parameters, query/field limits, exact client/callback,
  issuer/resource/scope and PKCE checks retain their existing boundaries.
- Show the running backend version on sign-in/registration and in Console using
  the existing public health metadata. A bounded, credential-free read has
  localized loading/failure states and never blocks sign-in or substitutes a
  frontend build version.
- Explain that the MCP resource URL is the client's connection address, not an
  OAuth callback. Suggest issuer + `/mcp` only while editing an empty or previous
  automatic value; preserve manual edits and loaded configuration.
- Show four setup steps and prevent new enablement without freshly read active
  signing-key metadata. Saving disabled URLs remains available without a key.
  The key shortcut only focuses the existing confirmed operation. Re-read
  server state after key operations, preserve dirty drafts on retry, and keep
  explicit disablement available when an enabled service's metadata fails.
- Replace page-wide success banners with the existing dismissible, four-second,
  polite status message. Persistent errors and one-time-secret confirmations
  remain; no secret is included in a message.
- Default personal grants to active, with expired/revoked/all filters and
  search before pagination over the loaded owner-scoped dataset. Separate
  scope, UTC expiry, limits, state and actions. Keep history viewable in
  searchable, paginated read-only details; active reductions and revocations
  still require confirmation and backend owner/revision checks.

Validation is recorded in the paired
[0.4.1 validation record](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.1/docs/release-validation-0.4.1.md).
Synthetic authorization/browser coverage does not establish full real ChatGPT,
external-client, public TLS or production-upgrade acceptance. The complete optional
layout/visual suite was not run. An initial unfiltered invocation stopped on
two optional reset-layout cases (2 px movement against a < 2 px limit); those
failures remain recorded. No baselines were regenerated, and previously
recorded 0.4.0 optional failures are not represented as passing.

**Git/network execution remains partial:** the production `SafeNetworkExecutor`
is absent. Real Git acquisition, proxy tests, package-tool preparation and
configured network installs fail closed. No real proxy, SSH key, token, tunnel
or remote-control configuration was created. DCR/CIMD remain unsupported.

The normal release workflow produces five native targets (Linux x86_64/ARM64,
Windows x86_64, macOS x86_64/ARM64), Compose, two offline Core images, application
SPDX, container digest metadata and `SHA256SUMS` (11 assets). Verify downloads
against checksums and repository build-provenance attestations. Existing 0.4.0
release assets and historical screenshot evidence remain unchanged.

### 简体中文

0.4.1 修复携带 `ui_locales` 的授权请求，并改善登录版本展示、内置 OAuth 配置
及本人授权查看流程。

- 接受有界的可选 `ui_locales` 偏好列表，选择支持的英语/简体中文提示；不支持的
  语言保留既有界面偏好。提示与授权票据分离；未知/重复参数、查询/字段限制、
  精确客户端/回调、Issuer/resource/scope 和 PKCE 校验保留原边界。
- 登录/注册页与 Console 使用既有公开健康元数据展示运行中的后端版本。有界、
  不带凭据的请求提供本地化读取/失败状态，不阻断登录，也不以前端构建版本替代。
- 明确 MCP 资源 URL 是客户端连接地址，不是 OAuth 回调。只在编辑空值或上次
  自动填写值时建议 Issuer + `/mcp`，保留手动修改和加载的配置。
- 展示四步配置，并在未重新读取确认活动签名密钥时禁止新启用。关闭状态保存地址
  无需密钥；密钥快捷入口仅定位原有需确认操作。密钥操作后重读服务器状态，重试
  保留未保存地址；已启用服务读取失败时仍可通过确认明确关闭。
- 成功反馈改为现有的可关闭、四秒消退、礼貌播报的轻量消息。错误持续可见，
  一次性密钥保留原确认，消息不包含秘密。
- 本人授权默认有效，支持过期/撤销/全部；在完整已读取本人数据上搜索筛选后分页。
  分列展示范围、UTC 到期、配额、状态和操作。历史记录保留可搜索分页的只读详情，
  有效授权缩小与撤销仍须确认并通过后端本人权限/版本校验。

验证详见成对的
[0.4.1 验证记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.1/docs/zh-CN/release-validation-0.4.1.md)。
合成授权/浏览器覆盖不代表真实 ChatGPT、外部客户端、公开 TLS 或生产升级完整
验收。未运行完整可选布局/视觉套件；首次未筛选调用在两项可选重置布局案例失败
后停止（位移 2 px，要求小于 2 px），失败如实保留。未更新基线，此前记录的
0.4.0 可选失败不宣称通过。

**Git/网络执行仍为部分实现：**生产 `SafeNetworkExecutor` 尚未实现，真实 Git
拉取、代理测试、包管理器准备和指定网络安装保持关闭式失败。未创建真实代理、
SSH 密钥、token、隧道或远控配置；仍不支持 DCR/CIMD。

正常发行工作流生成五种原生目标（Linux x86_64/ARM64、Windows x86_64、
macOS x86_64/ARM64）、Compose、两个离线 Core 镜像、应用 SPDX、镜像摘要与
`SHA256SUMS`，共 11 个资产。下载后须核验校验和及仓库构建来源证明。既有 0.4.0
发行资产和历史截图证据保持原样。
