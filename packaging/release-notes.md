# Lingshu Gate 0.5.3

## English

0.5.3 fixes valid downstream MCP responses being rejected by the former fixed 8 MiB limit. A configurable byte budget defaults to 32 MiB for stdio messages, HTTP JSON responses and SSE responses/events. The 0.5.2 business-credential features are retained.

### Changes

- Add `LINGSHU_GATE_MCP_MAX_MESSAGE_BYTES`, default 33,554,432 bytes, with an accepted range of 1–268,435,456 bytes. Configuration changes require a Gate restart; zero does not disable protection.
- Apply the administrator-selected budget to stdio input/output and bounded stderr lines, HTTP JSON/error bodies, and SSE response/event/line accumulation. Retain absolute deadlines, discovery paging and event-count limits.
- Add transport regressions for image-shaped responses larger than the old limit and a subsequent response, custom small budgets and invalid settings. Synchronize native and Compose examples and paired configuration documentation.

### Upgrade and support boundaries

There are no additional database migrations or runtime dependencies over 0.5.2. Upgrades from older versions apply pending migrations, including `0022_tool_preferences`, `0023_tool_argument_policy` and `0024_business_credentials`. Back up the database, configuration and all credential keys together. Once used, include `<data-dir>/business-credentials/credential.key`; remote browser-vault keys retain their separate lifecycle. SQLite remains single-writer and single-Core.

A larger message budget does not remove memory, network-bandwidth, tool-timeout or client response limits and does not promise faster large transfers. Managed business-credential restrictions and existing authorization boundaries remain in place; this patch does not activate bindings or prove successful real website logins.

### Validation and publication

Local Linux validation passed 361 targeted transport, runtime-resource, business-credential privacy and release tests, 619 frontend tests, frontend type checks, Ruff and Mypy over 192 source files. These checks do not establish real website login or production upgrade acceptance. The formal release pipeline independently validates the final commit, native packages, Compose and offline images. Publication is complete only after all required jobs and eleven assets, checksums, SBOM and provenance are verified; tags alone are not completion. Existing tags and releases remain immutable.

See [configuration](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/configuration.md), [business credentials](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/business-credentials.md) and [operations](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/operations.md).

## 简体中文

0.5.3 修复合法下游 MCP 响应被固定 8 MiB 上限拒绝的问题，将字节上限改为可配置，stdio 消息、HTTP JSON 响应及 SSE 整段响应/事件默认统一为 32 MiB，并保留 0.5.2 的业务凭据功能。

### 变更

- 增加 `LINGSHU_GATE_MCP_MAX_MESSAGE_BYTES`，默认 33,554,432 字节，仅接受 1–268,435,456 字节；修改后重启 Gate 生效，零值不能关闭保护。
- 将管理员设置的上限用于 stdio 收发及 stderr 行、HTTP JSON/错误响应体、SSE 整段响应、事件与行的累积；保留绝对截止时间、发现分页及事件数量限制。
- 增加超过旧上限的图片形状响应及后续响应、自定义小上限和无效配置回归，同步原生包、Compose 示例和配对配置文档。

### 升级和支持边界

相对 0.5.2 不增加数据库迁移或运行依赖。从更旧版本升级时执行尚未应用的迁移，包括 `0022_tool_preferences`、`0023_tool_argument_policy`、`0024_business_credentials`。应一致备份数据库、配置和全部凭据密钥；开始使用业务凭据后，包含 `<data-dir>/business-credentials/credential.key`，远端浏览器密码库密钥仍有独立生命周期。SQLite 保持单写入者、单 Core。

增加消息上限不消除内存、网络带宽、工具超时或客户端响应限制，也不承诺大响应传输加速。业务凭据受管限制及既有授权边界保持有效，本补丁不自动启用绑定，也不证明真实网站登录成功。

### 验证和发布

本地 Linux 已通过 361 项定向传输、运行资源、业务凭据隐私及发行测试，619 项前端测试、前端类型检查、Ruff 及 192 个源码文件的 Mypy 检查。这些检查不代表真实网站登录或生产升级验收。正式流水线独立验证最终提交、原生包、Compose 和离线镜像；全部必需任务及十一项资产、校验和、SBOM、构建来源验证通过后，才算发布完成，标签本身不是完成证据。已有标签和发行保持不可变。

参见[配置](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/zh-CN/configuration.md)、[业务凭据](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/zh-CN/business-credentials.md)与[运维](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.3/docs/zh-CN/operations.md)。
