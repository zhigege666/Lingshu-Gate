# 更新记录

## 0.4.3

- 本人在 Gate 明确确认即可为现有 OAuth 授权新增、重新确认或移除 MCP/工具。同一 bearer 与刷新令牌族在不变的 OAuth scope 上限内跟随 live 工具范围，同 scope 工具不需要客户端再次 OAuth。
- 更新保留会话/Origin/CSRF、绑定确认、当前权限、版本 CAS 与原子审计。不补造缺失 scope，较窄令牌族保留自身限制，其他授权不变。
- 配置 Form/JSON 编辑保留未知字段和精确草稿，提供明确 Gate 启动/重启策略及准确重载反馈。新 MCP 默认启用但不自动启动，应用不会悄悄启动服务。
- 工具目录、资源授权和分类审核正确解析内置工具来源。
- 范围弹窗在工具滚动时保留控件与操作，MCP 选择展示 ID 并支持名称搜索，授权支持完整本人数据搜索和分页。
- HTTP 自动协商识别精确的初始旧版初始化拒绝，展示实际协商版本，不重放业务调用。

[候选验证](docs/zh-CN/development-validation.md)。正式发布、平台资产及独立视觉验收分别记录。

## 0.4.2

0.4.2 增加绑定精确服务/IP/端口的内网 HTTP MCP 授权，提供实时管理员检查、CAS、明确内联确认、默认拒绝与撤销重检，保留 HTTPS 验证及禁止重定向边界。

[Validation / 验证记录](docs/zh-CN/release-validation-0.4.2.md) · [Release notes / 发行摘要](packaging/release-notes.md)
