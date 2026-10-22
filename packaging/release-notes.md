# Lingshu Gate 0.5.5

## English

0.5.5 defaults new Console, REST and external-MCP configurations to automatic startup. It separates creation defaults from historical file parsing so existing configurations and explicit administrator choices retain their startup behavior.

### Changes

- Default new configurations to `enabled=true`, `auto_start=true` and `startup_policy=gate_start_v1` across Console, REST and external-MCP creation entries.
- Preserve explicit `auto_start=false`, explicitly selected `legacy_restore`, disabled configurations and historical files without startup fields. Ordinary edits do not migrate an existing configuration.
- Keep save, apply and immediate start/connect independent. External HTTP startup establishes a connection; it does not start a remote service. Build/upload candidate drafts retain their explicit startup settings.
- Add creation, explicit-off, disabled, legacy-file, runtime-policy and form-mode regression coverage. Retain the certifi security baseline, configurable 32 MiB message budget and business-credential features.

### Upgrade and support boundaries

There are no new dependencies or database migrations over 0.5.4. Existing configurations are not bulk migrated; an administrator must explicitly change an existing startup switch. Upgrades from older versions apply pending migrations, including `0022_tool_preferences`, `0023_tool_argument_policy` and `0024_business_credentials`. Back up the database, configuration and all credential keys together. Once used, include `<data-dir>/business-credentials/credential.key`; remote browser-vault keys retain their separate lifecycle. SQLite remains single-writer and single-Core.

Automatic startup is evaluated when Gate starts; this change does not implement on-demand startup or idle shutdown. Existing authorization and managed business-credential boundaries remain in place. It does not activate credential bindings or establish real website login acceptance.

### Validation and publication

Focused configuration and startup-policy tests cover creation defaults, explicit opt-outs, historical loading and saving without starting; Console model tests cover mode changes. The native bundle is built and smoke-tested separately before deployment. These checks do not establish real website login acceptance. Formal multi-platform publication is separate from a local operator build and deployment, and requires all required jobs, eleven assets, checksums, SBOM and provenance to be verified. Existing tags and releases remain immutable.

See [configuration](../docs/configuration.md), [business credentials](../docs/business-credentials.md) and [operations](../docs/operations.md).

## 简体中文

0.5.5 将 Console、REST 和外部 MCP 新建配置默认设为自动启动。新建默认值与历史文件解析分开处理，保留已有配置及管理员明确选择的启动行为。

### 变更

- Console、REST 和外部 MCP 新建入口默认 `enabled=true`、`auto_start=true` 和 `startup_policy=gate_start_v1`。
- 保留明确的 `auto_start=false`、明确选择的 `legacy_restore`、停用配置及缺少启动字段的历史文件；普通编辑不迁移已有配置。
- 保存、应用及立即启动/连接保持独立。外部 HTTP 自动启动只建立连接，不启动远端服务；构建/上传候选草稿保留明确的启动设置。
- 增加新建、明确关闭、停用、历史文件、运行策略及表单模式回归；保留 certifi 安全基线、可配置 32 MiB 消息上限和业务凭据功能。

### 升级和支持边界

相对 0.5.4 不增加依赖或数据库迁移。不批量迁移已有配置，已有启动开关需管理员明确修改。从更旧版本升级时执行尚未应用的迁移，包括 `0022_tool_preferences`、`0023_tool_argument_policy`、`0024_business_credentials`。应一致备份数据库、配置和全部凭据密钥；开始使用业务凭据后，包含 `<data-dir>/business-credentials/credential.key`，远端浏览器密码库密钥仍有独立生命周期。SQLite 保持单写入者、单 Core。

自动启动在 Gate 启动时执行，本次不实现按需启动或空闲停机。既有授权及业务凭据受管边界保持有效，不自动启用凭据绑定，也不证明真实网站登录成功。

### 验证和发布

定向配置及启动策略测试覆盖新建默认值、明确关闭、历史加载及保存不启动，Console 模型测试覆盖模式切换；原生包在部署前单独构建并做启动冒烟。这些检查不代表真实网站登录验收。本地操作员构建部署与正式多平台发布分别核验；正式发布需全部必需任务、十一项资产、校验和、SBOM 及构建来源验证通过。已有标签和发行保持不可变。

参见[配置](../docs/zh-CN/configuration.md)、[业务凭据](../docs/zh-CN/business-credentials.md)与[运维](../docs/zh-CN/operations.md)。
