# Lingshu Gate 0.5.2

## English

0.5.2 adds business accounts and explicit MCP adapter bindings to Gate's credential management. The first adapter synchronizes selected agent-browser vaults and lets agents request login with a credential reference and a logical session. This release also fixes tool-review filter layout and removes deleted MCP tools from the current governance catalog while retaining audit history.

### Changes

- Add personal and shared business-account sections to the existing credentials pages. Store usernames and passwords encrypted, return masked metadata, and support environment/business-role labels and explicit user/role grants. Secret entry continues to require HTTPS or loopback; editing preserves unchanged secrets without echoing them into the form.
- Bind an account to selected MCP instances through reviewed adapters. The first adapter, `agent_browser`, performs controlled vault save/delete and native login operations. Each binding records the account version and synchronization result; edits mark copies pending, stale revisions are rejected, and uncertain outcomes remain visible.
- Let agents use `gate:<credential-id>` and an explicit logical session with the native login tool. Recheck the current account, binding, MCP permission, argument policy and tool contract before dispatch. Open the configured login page and verify its origin before filling credentials; separate sessions by caller and Gate connection.
- Apply managed-browser restrictions to the bound instance. Block raw vault management, arbitrary JavaScript, state/cookie export, host-file access, unreviewed fields and global browser controls. Protect secrets in transport diagnostics and returned content; managed browser results are excluded from Gate's short-lived result cache.
- Keep account disablement, remote vault cleanup and browser-session closure as distinct operations. Preserve unresolved cleanup records, show unknown outcomes, and avoid automatic replay of uncertain writes. Closing a browser is not reported as website-wide session revocation.
- Add bilingual account, grant, binding, synchronization and browser-session controls. Clear secret drafts when they are no longer needed, and fix dropdown interaction within dialogs.
- Fix long MCP names and status badges in tool review by keeping the name and badge independently constrained, preserving usable search width and allowing the toolbar to wrap on narrower desktop layouts.
- Build current REST/MCP governance lists from the live tool registry. Retire classifications only after the MCP deletion is durably saved, reject stale edits/confirmation/publication for removed tools, and retain audit history. Temporary stops and restarts preserve prior review decisions.

### Upgrade and support boundaries

Upgrade applies migration `0024_business_credentials`; upgrades from older versions also apply any earlier pending migrations. Back up the database, configuration and all credential keys together before upgrading. Business-account ciphertext is stored in the Gate database and its key is `<data-dir>/business-credentials/credential.key`. Include that key in backups once business credentials are used. The remote agent-browser vault has its own key and lifecycle; a Gate database backup alone does not preserve its encrypted values. SQLite remains single-writer and single-Core.

Use a dedicated, trusted agent-browser instance with a compatible reviewed save/login/delete/navigation contract and explicit `session`/`noNavigate` support. The first binding enables managed restrictions for all calls through that instance, including other users' calls; removing the final binding does not reopen raw vault tools. Targets with per-user downstream HTTP-header slots are unsupported by this adapter. The remote host administrator and the browser's trusted execution boundary can access passwords; the OS-user vault and logical sessions are not isolation from a hostile host or mutually hostile users.

Before upgrading a bound browser target or changing its manifest/tool contract, disable the affected bindings, clean up their remote copies, close their managed sessions and remove the bindings. Review and bind the changed target again. A receipt from a replacement target cannot establish that the old target was cleaned up.

Business-account grants and bindings do not publish tools or expand existing MCP/OAuth authorization scopes. Other MCP products require their own reviewed adapter; arbitrary tools cannot resolve these references. Existing service environment/header credentials remain separate, and static business passwords do not replace OAuth consent or token refresh. A successful native login action proves form interaction, not successful website authentication or MFA completion. Account disablement, vault deletion, browser closure and website-side revocation remain separate outcomes.

This release adds no mobile product support. Existing transport, container-engine and host-execution boundaries remain in place. Actual installed browser-node contracts, real business-account logins and production upgrades were not exercised by the candidate checks below.

### Validation and publication

Pre-release candidate checks passed 329 relevant backend tests with 12 subtests, a separate 13-test schema-budget suite, Ruff, Mypy over 192 source files, frontend type/UI-contract checks, 619 frontend tests and both Console/OAuth production builds. Thirteen Chromium UI cases passed with synthetic API responses across 2560×1440, 1920×1080, 1600×900 and 2560×1080 desktop sizes, covering English/Chinese and light/dark presentation. These checks do not establish a live browser-node login. The formal release pipeline independently checks the final release commit.

Publication is complete only after the formal quality, five native targets, Compose and two offline Core-image jobs pass and all eleven release assets, checksums, application SPDX SBOM, container references and build provenance are verified. The published title and body are read back against the source notes. Existing tags and releases remain immutable.

See [business credentials](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/business-credentials.md), [configuration](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/configuration.md), [operations](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/operations.md) and the [release process](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/releases.md).

## 简体中文

0.5.2 在 Gate 凭据管理中增加业务账号和明确的 MCP 适配绑定。首个适配器可同步选定的 agent-browser 密码库，让 Agent 通过凭据引用与逻辑会话请求登录。本版同时修复工具审核筛选布局，以及已删除 MCP 的工具仍出现在当前治理目录的问题，审计历史继续保留。

### 变更

- 在现有凭据页面增加个人和共享业务账号分区。加密保存用户名与密码，仅返回掩码元数据，支持环境/业务角色标签及明确的用户/角色授权。秘密录入仍要求 HTTPS 或回环地址；编辑时可保留已有秘密，无需将其回显到表单。
- 通过经复核的适配器将账号绑定到选定 MCP 实例。首个适配器 `agent_browser` 执行受控的密码库保存/删除与原生登录操作。每条绑定记录账号版本及同步结果；修改后将副本标为待同步，拒绝过期修订，并保留结果不明的状态。
- Agent 可使用 `gate:<credential-id>` 和明确的逻辑会话调用原生登录工具。派发前重新检查当前账号、绑定、MCP 权限、参数策略与工具契约；先打开已配置的登录页并核对来源，再填写凭据，并按调用者及 Gate 连接区分会话。
- 对绑定实例启用受管浏览器限制，阻止原始密码库管理、任意 JavaScript、状态/Cookie 导出、宿主文件访问、未经复核的字段和全局浏览器控制。在传输诊断和返回内容中保护秘密；受管浏览器结果不进入 Gate 的短期结果缓存。
- 将账号停用、远端密码库清理和浏览器会话关闭保持为独立操作。保留清理未确认的记录，显示未知结果，不自动重放结果不明的写操作，也不将浏览器关闭报告为网站全局会话撤销。
- 增加中英文账号、授权、绑定、同步和浏览器会话控件，在不再需要时清理秘密草稿，并修复弹窗内下拉选项无法点击的问题。
- 修复工具审核中长 MCP 名称与状态标识的布局，独立约束名称和标识，保留搜索框可用宽度，并在较窄桌面下允许工具栏换行。
- 当前 REST/MCP 治理列表以实时工具注册表为准，仅在 MCP 删除配置成功持久化后退役分类。拒绝对已移除工具的过期编辑、确认与发布，保留审计历史；临时停止和重启继续保留原有审核结果。

### 升级和支持边界

升级会执行 `0024_business_credentials` 迁移；从更早版本升级时，还会执行此前尚未应用的迁移。升级前应一致备份数据库、配置和全部凭据密钥。业务账号密文保存在 Gate 数据库中，对应密钥为 `<data-dir>/business-credentials/credential.key`；开始使用业务凭据后，应将其纳入备份。远端 agent-browser 密码库有独立密钥和生命周期，仅备份 Gate 数据库不能保存其加密数据。SQLite 继续限定单写入者、单 Core。

应使用专用、可信的 agent-browser 实例，其保存/登录/删除/导航工具契约须兼容且经过复核，并明确支持 `session`/`noNavigate`。首次绑定会对经由该实例的所有调用启用受管限制，包括其他用户的调用；移除最后一条绑定也不会恢复原始密码库工具。本适配器不支持带每用户下游 HTTP Header 槽位的目标。远端主机管理员及浏览器可信执行边界内的代码能够接触密码；按操作系统用户保存的密码库和逻辑会话，不提供对恶意宿主或互不信任用户的安全隔离。

升级绑定的浏览器目标或修改其 Manifest/工具契约前，应停用受影响的绑定、清理远端副本、关闭受管会话并移除绑定；目标变更后重新复核和绑定。替换后目标返回的回执不能证明旧目标已完成清理。

业务账号授权和绑定不会发布工具，也不会扩大现有 MCP/OAuth 授权范围。其他 MCP 产品需要各自经过复核的适配器，任意工具不能解析此类凭据引用。现有服务环境变量/Header 凭据保持独立，静态业务密码也不能替代 OAuth 同意或令牌刷新。原生登录操作成功只证明已操作表单，不代表网站认证或 MFA 已完成。账号停用、密码库删除、浏览器关闭与网站侧撤销仍是不同结果。

本版不新增移动端产品支持，原有传输、容器引擎和宿主执行边界继续保留。下述候选检查未验证实际已安装的浏览器节点契约、真实业务账号登录或生产升级。

### 验证和发布

发布前候选已通过 329 项相关后端测试及 12 项子测试、单独的 13 项 Schema 预算测试、Ruff、覆盖 192 个源码文件的 Mypy、前端类型/UI 契约检查、619 项前端测试及 Console/OAuth 双生产构建。13 项 Chromium UI 用例使用合成 API 响应，在 2560×1440、1920×1080、1600×900、2560×1080 四种桌面尺寸下通过，覆盖中英文与明暗主题。这些检查不等于实际浏览器节点登录验收；正式发行流水线另行检查最终发行提交。

正式质量检查、五平台原生包、Compose 和两个离线 Core 镜像任务全部通过，且十一项发行资产、校验和、应用 SPDX SBOM、容器引用与构建来源证明验证完成后，才算发布完成。发布标题和正文必须回读并与源码说明一致。已有标签和发行保持不可变。

参见[业务凭据](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/zh-CN/business-credentials.md)、[配置](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/zh-CN/configuration.md)、[运维](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/zh-CN/operations.md)和[发行流程](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.2/docs/zh-CN/releases.md)。
