# Lingshu Gate 0.5.1

## English

0.5.1 improves the signed-in Console and built-in OAuth workflows. Shared spacing, compact actions and click-to-open field help reduce visual clutter. MCP and invocation editors retain incomplete drafts and advanced JSON values, and failed reads can be retried without discarding unrelated work.

### Changes

- Refine all 23 signed-in routes with shared page/card spacing, consistent control sizes, centered dialogs and internally scrolling lists. Desktop layouts use 2560×1440 as the baseline and support 1920×1080, 1600×900 and 2560×1080 in English and Simplified Chinese.
- Put static field explanations behind help buttons beside labels. Click, keyboard, Escape, outside-close and focus recovery are supported; errors, current state and confirmation facts remain directly visible.
- Preserve advanced MCP fields and incomplete numeric/key-value drafts across Form/JSON editing. Reject duplicate object keys, unsafe integers and non-finite numbers before they can be silently converted. Keep original text and identify the affected path; server validation and normalization still apply.
- Add managed-container stdio fields for digest-pinned images, arguments, environment, enablement, automatic startup, timeouts, restart and health settings. Separate process and container environments, retain explicit credential references and keep unsupported container HTTP transport blocked.
- Reorganize built-in OAuth into connection settings, independent management access and client operations. Keep registration with the client list, expose direct editing, hide empty-list search chrome and show only the next relevant setup recommendation. Distinguish configured and active management states and explain when each switch takes effect.
- Recover configuration, client and signing-key reads independently. Preserve revision checks, body-bound CSRF, dirty/pending navigation protection, one-time-secret handling and focus on retry, cancellation and dialog close.
- Improve authorization paging and current-tool selection, retain failed classification selections and recover project-delivery, network and observability drafts. Tool discovery and bulk selection do not grant future tools or expand existing OAuth scopes by themselves.

### Upgrade and support boundaries

This patch introduces no additional database migrations or runtime dependencies over 0.5.0. Back up the database, configuration and credential keys together before upgrading. Upgrades from versions before 0.5.0 still apply migrations `0022_tool_preferences` and `0023_tool_argument_policy`; older binaries do not enforce the added argument policies. SQLite remains single-writer and single-Core.

Advanced mounts, resource limits, toolchains, package/protocol settings, permissions, credential slots, roots and analysis remain in JSON where applicable. The form changes only the edited paths; it does not promise byte-for-byte JSON round trips or arbitrary decimal precision. Credential masks are not reusable secrets, and a configured permission or root is not a grant of runtime access.

This release does not add mobile product support. The UI acceptance does not establish third-party client reauthorization, every private network topology, real container startup for the newly exposed form controls or production upgrade behavior. Existing transport, container-engine and host-execution support boundaries remain in place.

### Validation and publication

Pre-release candidate validation passed frontend type and UI-contract checks, 607 unit tests, both Console/OAuth builds, a 23-route desktop/language rendering matrix, and targeted form, recovery and authorization regressions. The OAuth layout suite passed 108 cases; 52 targeted cases were rerun after final refinements and are not an additional distinct-case total. Eight real test-instance desktop/language combinations passed login, reads, help, focus and refresh checks without business writes. The formal release pipeline independently checks the final release commit.

Publication is complete only after the formal quality, five native targets, Compose and two offline Core-image jobs pass and all eleven release assets, checksums, application SPDX SBOM, container references and build provenance are verified. The published title and body are read back against the source notes. Existing tags and releases remain immutable.

See [configuration](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/configuration.md), [built-in OAuth](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/builtin-oauth.md), [operations](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/operations.md) and the [release process](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/releases.md).

## 简体中文

0.5.1 优化登录后的 Console 与内置 OAuth 流程，通过统一间距、紧凑操作区和点击展开的字段说明减少页面杂乱。MCP 配置与调用编辑器保留未完成草稿及高级 JSON 值，读取失败后可重试，无需丢弃其他区域的修改。

### 变更

- 优化全部 23 个登录后路由，统一页面/卡片间距、控件尺寸、居中弹窗和列表内部滚动。桌面布局以 2560×1440 为基准，支持 1920×1080、1600×900、2560×1080 与中英文。
- 静态字段说明放到标签旁的帮助按钮，支持点击、键盘、Escape、外部点击关闭和焦点恢复；错误、当前状态与确认事实保持直显。
- Form/JSON 编辑保留 MCP 高级字段及未完成的数字、键值草稿。在静默转换前拒绝重复对象键、不安全整数与非有限数字；保留原文并定位相关路径，服务端校验和规范化继续生效。
- 补充托管容器 stdio 的 digest 固定镜像、参数、环境变量、启用、自启、超时、重启与健康设置表单。区分进程/容器环境，保留明确的凭据引用，并阻止尚不支持的容器 HTTP 传输。
- 重整内置 OAuth 的连接配置、独立管理连接和客户端操作。注册入口归属客户端列表，编辑直接可见，空列表隐藏无用搜索区，接入建议只显示当前下一项；区分管理资源已配置/已生效状态，并说明各开关的生效时机。
- 配置、客户端和签名密钥读取可独立恢复；版本校验、精确请求体 CSRF、未保存/请求中导航保护、一次性秘密，以及重试、取消和弹窗关闭后的焦点语义保持有效。
- 改善授权分页和当前工具批选，分类发布失败后保留失败选择，项目交付、网络配置与日志观测支持草稿恢复。工具发现和批量选择本身不会授权未来工具，也不会扩大已有 OAuth 作用域。

### 升级和支持边界

相对 0.5.0，本补丁不新增数据库迁移或运行依赖。升级前一起备份数据库、配置和凭据密钥。从 0.5.0 之前的版本升级，仍需执行 `0022_tool_preferences`、`0023_tool_argument_policy` 迁移；更早的二进制不执行新增的参数策略。SQLite 继续限定单写入者、单 Core。

高级挂载、资源限制、工具链、包/协议设置、权限、凭据槽位、roots 和 analysis 等适用字段继续通过 JSON 编辑。表单只修改目标路径，不承诺逐字节 JSON 往返或任意小数精度。凭据掩码不是可重复使用的秘密，配置权限或根目录也不等于授予运行时访问权限。

本版不新增移动端产品支持。本轮 UI 验收不代表已经验证第三方客户端重新授权、所有私网拓扑、新增表单控件的真实容器启动或生产升级。原有传输、容器引擎和宿主执行支持边界继续保留。

### 验证和发布

发布前候选已通过前端类型和 UI 契约检查、607 项单元测试、Console/OAuth 双构建、23 路由桌面/语言渲染矩阵及表单、恢复和授权定向回归。OAuth 布局首轮 108 项通过；最终调整后定向复测 52 项，这些复测不计为额外独立用例。真实测试实例的 8 组桌面/语言组合通过登录、读取、帮助、焦点和刷新检查，未执行业务写入。正式发行流水线另行检查最终发行提交。

正式质量检查、五平台原生包、Compose 和两个离线 Core 镜像任务全部通过，且十一项发行资产、校验和、应用 SPDX SBOM、容器引用与构建来源证明验证完成后，才算发布完成。发布标题和正文必须回读并与源码说明一致。已有标签和发行保持不可变。

参见[配置](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/zh-CN/configuration.md)、[内置 OAuth](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/zh-CN/builtin-oauth.md)、[运维](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/zh-CN/operations.md)和[发行流程](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.1/docs/zh-CN/releases.md)。
