# Lingshu Gate 0.5.6

## English

0.5.6 makes external HTTP MCP setup usable without hand-written authentication headers and adds end-to-end administrator MCP management for external configurations and encrypted shared credentials. Connection testing, saving, runtime connection, tool discovery and tool publication remain separate operations.

### Changes

- Add guided **None / Bearer Token / API Key / Basic / Custom** authentication. Select an existing target-scoped credential or create one inline; a successful selection generates the reference-based header directly, without an extra Add step. New credential IDs are generated and remain editable. Bearer accepts one pasted prefix; Basic takes username/password and handles encoding. Unknown or multiple authentication headers remain Custom, and unrelated headers survive edits.
- Add a draft-only **Home** shortcut with PAT guidance. It appends `/mcp` only to an explicit root URL, preserves existing paths and never guesses a port, signs in, grants permission or sends a token automatically.
- Add **Test connection** and `gate_http_mcp_test`. An isolated, bounded client checks configuration, HTTP, request authentication, MCP handshake and tool discovery. Results distinguish failures and unverified stages; changed drafts invalidate earlier results. Testing does not save configuration, change persistent trust, replace a running connection, publish tools or invoke business tools.
- Add `gate_http_mcp_plan`, `gate_http_mcp_apply`, `gate_http_mcp_status` and `gate_http_mcp_cancel`, reusing the reviewed operation engine and journal. Plans cover create/update/delete and exact private-HTTP permission revoke/restore, with revision checks, idempotency and explicit connection/discovery choices. Deletion removes the local configuration and its catalog/group membership, not the remote process or shared credentials.
- Add `gate_credential_list`, `gate_credential_get`, `gate_credential_create`, `gate_credential_update` and `gate_credential_delete`. Credentials remain encrypted with masked reads, write-only values, revision-aware updates, keyed idempotency and dependency-protected deletion. HTTP usage binds service, origin and lifecycle; subsequent dispatches resolve rotated values rather than indefinitely caching old headers.
- Combine the exact private-HTTP permission with an authorized configuration save instead of requiring a separate **Authorize this address** step. Revocation persists across ordinary saves/reconnects; restoring it remains explicit. Recreated service IDs cannot inherit previous permission.
- Widen configuration dialogs to a 1200 px desktop maximum, move connection results into the editor and retain **Cancel / Test connection / Save** in the external-HTTP footer. Save runs static validation automatically; network testing is optional. Advanced headers and technical diagnostics are expandable. Preserve unfinished secrets and failed-write inputs, provide list-loading recovery and restore keyboard focus after credential use/cancellation.

- Split the complete formal backend/release collection across four deterministic required quality jobs, avoiding the previous sequential 40-minute timeout without dropping tests or shrinking scale fixtures. Every shard must pass before packaging.

### Upgrade and compatibility

No new dependency or numbered SQL migration is introduced over 0.5.5. Existing operation journals are reused. Matching legacy shared-credential consumers and private-HTTP records receive bounded compatibility conversion; orphaned records gain no wildcard permission. This changes persisted credential/trust metadata, so back up the database, configuration, encrypted credential stores and all associated keys together. Restore the matching complete backup when rolling back; an older executable does not enforce newly added boundaries. SQLite remains single-writer and single-Core.

Existing four `gate_mcp_config_*` tool schemas and authorization fingerprints remain unchanged. The new management tools require current administrator permissions and applicable token/delegation scopes. Management OAuth must explicitly consent to new tools, exact target actions and `credentials.manage.system` for credential administration. Upgrading, reconnecting or refreshing an old token does not expand its grant. Existing explicitly wildcard-scoped administrator API tokens retain their current scope ceiling.

Credential REST updates/deletes now require the current `expected_revision`; clients should read the masked record first. Unchanged write retries should reuse the idempotency key. Saving a rotated value does not revoke a remote token or prove that a downstream service accepts the new value. A matching service/origin/lifecycle scope remains required for HTTP use.

### Support boundaries and validation

The connection test defaults to a 15-second budget, accepts 1–30 seconds and admits at most two tests concurrently per Core. DNS and cleanup remain subject to the underlying transport limits. A browser wait timeout is not proof of remote cancellation. HTTPS verification and redirect blocking remain enabled; plain HTTP and Basic encoding are not transport encryption. Personal downstream credential slots keep their caller-owned flow, and advertised OAuth metadata does not trigger automatic login/token acquisition.

Candidate evidence includes 655 frontend tests, 101 distinct relevant browser cases verified across batches, and focused backend/OAuth regressions. Browser coverage includes Chinese/English, light/dark themes, 2560×1440, 1920×1080, 1600×900 and 2560×1080, custom headers, failure recovery and keyboard handling. Actual HTTP fixtures validate Bearer, Basic and API-key behavior using synthetic credentials; this is not production Home account acceptance. Existing Vite large-chunk warnings remain.

Formal publication separately requires the complete source quality gate, five native targets, Compose bundle, two offline Core images, application SPDX SBOM, exact container reference, aggregate checksums and provenance verification. A source commit, version tag or partial job completion is not a completed release. Existing tags and releases remain immutable.

See [HTTP setup and testing](../docs/http-mcp-connection-testing.md), [external MCP management](../docs/external-mcp-configuration.md), [shared credentials](../docs/shared-system-credentials.md) and [release verification](../docs/releases.md).

## 简体中文

0.5.6 改善外部 HTTP MCP 接入体验，不再要求用户手写常见鉴权头，同时补齐外部配置与加密共享凭据的管理员 MCP 管理能力。连接测试、配置保存、运行时连接、工具发现和工具发布仍是独立操作。

### 变更

- 增加 **无鉴权 / Bearer Token / API Key / Basic / 自定义** 引导式鉴权。选择目标范围匹配的已有凭据或内联新增凭据后，直接生成引用形式的请求头，不再额外点击添加。凭据 ID 自动生成并允许修改；Bearer 可处理粘贴时带入的一次前缀，Basic 直接填写用户名和密码，由表单编码。未知或多项鉴权头保持自定义，无关请求头不丢失。
- 增加只修改草稿的 **Home** 快捷模板和 PAT 获取说明。仅对明确填写的根 URL 补充 `/mcp`，保留已有路径，不猜测端口，不自动登录、授权或发送令牌。
- 增加 **测试连接** 和 `gate_http_mcp_test`。独立、有界的客户端分别检查配置、HTTP、请求鉴权、MCP 握手和工具发现，明确区分失败与未验证阶段；草稿变化后旧结果过期。测试不保存配置、不修改持久信任、不替换运行连接、不发布工具、不调用业务工具。
- 增加 `gate_http_mcp_plan`、`gate_http_mcp_apply`、`gate_http_mcp_status`、`gate_http_mcp_cancel`，复用审核后的操作引擎与日志。计划支持创建、更新、删除，以及精确内网 HTTP 许可撤销/恢复，保留版本检查、幂等和明确连接/发现选择。删除只清理本地配置及工具目录/分组成员，不停止远端进程，也不删除共享凭据。
- 增加 `gate_credential_list`、`gate_credential_get`、`gate_credential_create`、`gate_credential_update`、`gate_credential_delete`。凭据加密存储、脱敏查询、原文只写入，支持版本更新校验、带密钥幂等及依赖保护删除。HTTP 使用绑定服务、origin 和生命周期；轮换后后续派发解析新值，不长期沿用旧 Header 缓存。
- 将精确内网 HTTP 许可合并到有权的配置保存操作，取消单独的 **授权此地址** 步骤。普通保存或重连不能恢复撤销，恢复须明确执行；同名服务重建不能继承旧许可。
- 配置弹窗桌面最大宽度调整为 1200px，测试结果移入编辑主体，外部 HTTP 底部保留 **取消 / 测试连接 / 保存**。保存前自动静态校验，网络测试可选；高级请求头及技术诊断按需展开。未完成秘密值与失败输入保留，凭据列表失败可重试，使用或取消凭据后恢复键盘焦点。

- 将完整正式后端与发布测试确定性分配到四个必须通过的质量任务，避免此前串行测试触及 40 分钟上限；不删除测试、不缩减规模场景，所有分片通过后才允许打包。

### 升级与兼容

相对 0.5.5 不新增依赖或编号 SQL 迁移，复用已有操作日志。对匹配的旧共享凭据使用者和内网 HTTP 记录执行有界兼容转换，孤立记录不会获得通配许可。凭据和信任元数据会发生持久化变化，因此升级前须一致备份数据库、配置、加密凭据存储及全部相关密钥。回退时恢复相互匹配的完整备份，旧可执行文件不会执行新增的保护边界。SQLite 保持单写入者、单 Core。

四个既有 `gate_mcp_config_*` 工具的 schema 与授权指纹不变。新管理工具要求当前管理员权限及相应 token/委托范围；管理 OAuth 须明确同意新工具、精确目标动作，以及凭据管理所需的 `credentials.manage.system`。升级、重新连接或刷新旧令牌不会扩大旧授权。已有明确通配 scope 的管理员 API Token 保持当前权限上限。

凭据 REST 更新/删除现在要求当前 `expected_revision`，调用方应先读取脱敏记录。相同写入的重试应复用幂等标识。保存轮换值不等于撤销远端旧令牌，也不证明下游接受新值；HTTP 使用仍须匹配服务、origin 和生命周期范围。

### 支持边界与验证

连接测试默认预算 15 秒，可设置 1–30 秒，每个 Core 最多同时执行两个测试；DNS 和清理仍受底层传输限制。浏览器等待超时不能当作远端请求已经取消。HTTPS 验证和禁止重定向仍有效；明文 HTTP 和 Basic 编码都不是传输加密。个人下游凭据槽保持调用者自有流程，服务声明 OAuth 元数据也不会触发自动登录或获取令牌。

候选实现已有 655 项前端测试、分批核验的 101 个不同浏览器用例，以及后端/OAuth 重点回归证据。浏览器覆盖中英文、亮暗主题、2560×1440、1920×1080、1600×900、2560×1080、自定义头、失败恢复和键盘操作；真实 HTTP 测试服务使用合成凭据验证 Bearer、Basic 和 API Key，不代表生产 Home 账号已验收。既有 Vite 大分块警告仍存在。

正式发布另需完整源码质量门禁、五个平台原生包、Compose、两个离线 Core 镜像、应用 SPDX SBOM、精确容器引用、总校验和及来源证明通过验证。源码提交、版本标签或部分任务完成均不等于正式发布完成。已有标签和发行保持不可变。

参见 [HTTP 接入与测试](../docs/zh-CN/http-mcp-connection-testing.md)、[外部 MCP 管理](../docs/zh-CN/external-mcp-configuration.md)、[共享凭据](../docs/zh-CN/shared-system-credentials.md)和[发行验证](../docs/zh-CN/releases.md)。
