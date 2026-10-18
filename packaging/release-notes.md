# Lingshu Gate 0.5.0

## English

0.5.0 adds controlled tool discovery, argument policies, fixed HTTP integrations and optional standard telemetry. Released native and Docker trial packages have dedicated bilingual start pages. The paired first-call guide uses an included demonstration service to make dynamic discovery, a read-only authorization, audit, a denied write and revocation reproducible.

### Changes

- Persist up to 20 pinned tools per business authorization. Optional result budgets return bounded previews for eligible plain-text results and support authorized, expiring result reads without invoking the downstream tool again.
- Add four argument-policy rule types and an English/Chinese Console editor with pure example evaluation, exact-body confirmation and revision checks. Enforce the current policy against effective arguments at final dispatch, including file-reference conversion and session retries.
- Add independent private connector relay and agent commands with fixed target allowlists, separate agent/consumer credentials, TLS controls and bounded requests. Transport reconnect does not replay business calls.
- Add an independent adapter for a strict local OpenAPI 3.0/3.1 subset. Selected operations become MCP tools bound to an immutable HTTP contract; changed contracts require fresh review/publication. Selected-tool snapshots require explicit reconfirmation; an existing continuous policy can cover a new published contract only within its previously confirmed scope and unchanged service identity.
- Add default-off Prometheus metrics and OpenTelemetry OTLP/HTTP tracing. Scraping requires current authentication plus both `operations.manage` and `observability.read.all`; the credential is not a globally read-only role. Export uses bounded memory and fixed destinations without recording tool arguments, results or credentials.
- Include a local demo service, paired English/Chinese getting-started and feature guides, neutral configuration examples and the documentation trees in native and Compose bundles. Add an explicit released-image Docker quickstart with independent trial volumes and demo readiness checks; update the project READMEs with current Console captures and clear download, production and source entry paths.

### Upgrade and support boundaries

Back up the SQLite database, configuration and credential keys together before upgrading. Migrations `0022_tool_preferences` and `0023_tool_argument_policy` add persistent discovery preferences and policy rules. A previous binary does not enforce the new policies; rollback requires a matching backup and reconciliation of changes made after it. SQLite remains single-writer and single-Core.

Runtime dependencies now include the OpenTelemetry API/SDK and OTLP HTTP exporter, Requests, JSON Schema validation, HTTPX2 and WebSockets. The frozen locks and third-party notices describe the shipped versions and licenses. Connector and adapter credentials are separate protected local files; they do not use Core's encrypted credential store. The connector and adapter run as separate processes and require explicit configuration. Optional host execution remains disabled until separately provisioned.

The adapter intentionally supports a bounded subset, not arbitrary OpenAPI documents. The connector forwards its documented MCP method subset and does not propagate tracing headers through the tunnel. Third-party desktop clients, every private network topology and Windows ACL handling for connector and adapter credential files are not covered by Linux acceptance.

### Validation and publication

Regression coverage includes current-policy checks at dispatch, authorization revocation, retries, result-cache isolation, fixed HTTP contracts, connector sessions, default-off metrics, OTLP protobuf export, TLS failure, redirects, queue saturation and exporter shutdown. The release pipeline requires quality checks, five native targets, Compose, two offline Core images, application SPDX SBOM, container image references, checksums and build provenance.

Publication is complete only after all formal jobs and eleven release assets are verified and the published title/body are read back against this version. Existing tags and releases remain immutable. See the [first-call guide](../docs/first-call.md), [argument policies](../docs/argument-policies.md), [private connector](../docs/private-connector.md), [OpenAPI adapter](../docs/openapi-adapter.md), [telemetry](../docs/telemetry.md) and [release process](../docs/releases.md).

## 简体中文

0.5.0 增加受控工具发现、参数策略、固定 HTTP 集成和可选的标准观测能力。原生发行包和 Docker 试用包提供专用中英文开始页；配对的首次调用指南使用内置演示服务，帮助复现动态发现、只读授权、审计、写入拒绝和授权撤销。

### 变更

- 每条业务授权持久化最多 20 个固定工具。可选结果预算为符合条件的纯文本结果返回有界预览，后续读取受当前授权和过期时间约束，不重新执行下游工具。
- 增加四类参数规则，以及支持纯示例评估、精确请求体确认和版本检查的中英文 Console 编辑器。最终派发前，基于转换后的实际参数复核当前策略，覆盖文件引用转换和会话重试。
- 增加独立的私网连接器 relay 和 agent 命令，使用固定目标白名单、分离的 agent/consumer 凭据、TLS 控制和有界请求；传输重连不会重放业务调用。
- 增加支持本地 OpenAPI 3.0/3.1 严格子集的独立适配器。选定操作生成绑定不可变 HTTP 合同的 MCP 工具；合同变化后需要重新审核/发布；指定工具快照须明确再确认，既有持续策略仅在原先已同意范围和未变化的服务身份内纳入新发布合同。
- 增加默认关闭的 Prometheus 指标和 OpenTelemetry OTLP/HTTP 链路。抓取必须通过当前认证，并同时具备 `operations.manage` 和 `observability.read.all`；该凭据不是全局只读角色。导出采用有界内存和固定地址，不记录工具参数、结果或凭据。
- 增加本地演示服务、配对的中英文开始指南及功能文档和中性示例；原生及 Compose 包包含文档与示例目录。增加使用发行镜像、独立试用卷和 demo 就绪检查的明确 Docker quickstart；项目 README 更新为当前 Console 截图及清晰的下载、生产和源码入口。

### 升级和支持边界

升级前一起备份 SQLite 数据库、配置和凭据密钥。迁移 `0022_tool_preferences`、`0023_tool_argument_policy` 增加发现偏好和参数规则持久化。旧二进制不会执行新策略；回退必须使用匹配备份，并核对备份后的数据变更。SQLite 继续限定单写入者、单 Core。

运行依赖增加 OpenTelemetry API/SDK、OTLP HTTP exporter、Requests、JSON Schema 校验、HTTPX2 和 WebSockets；冻结锁文件与第三方声明列明发行版本和许可证。辅助进程凭据使用独立的受保护本地文件，不接入 Core 的加密凭据库。连接器和适配器均为单独进程，必须显式配置；可选宿主执行仍需单独准备后才能启用。

适配器支持有界子集，不承诺处理任意 OpenAPI 文档。连接器只转发文档列明的 MCP 方法，不经隧道传递链路头。第三方桌面客户端、所有私网拓扑及 Windows 辅助进程凭据 ACL 行为不属于 Linux 验收范围。

### 验证和发布

回归覆盖最终派发前的当前策略、撤销、重试、结果缓存隔离、固定 HTTP 合同、连接器会话、默认关闭的指标、OTLP protobuf 导出、TLS 失败、重定向、队列饱和及导出器关闭。正式发行流水线要求质量检查、五个平台原生包、Compose、两个离线 Core 镜像、应用 SPDX SBOM、容器镜像引用、校验和与构建来源证明。

全部正式任务和十一项发行资产通过验证，并回读发布标题及正文与本版本一致后，才算发布完成。已有标签和发行保持不可变。参见[首次调用](../docs/zh-CN/first-call.md)、[参数策略](../docs/zh-CN/argument-policies.md)、[私网连接器](../docs/zh-CN/private-connector.md)、[OpenAPI 适配器](../docs/zh-CN/openapi-adapter.md)、[标准观测](../docs/zh-CN/telemetry.md)和[发行流程](../docs/zh-CN/releases.md)。
