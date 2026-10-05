# 更新记录

## Unreleased — Native executor

- 实现可选 Native/Linux rootless Podman 执行器、可信固定 HTTPS/Git 获取、官方精确工具缓存、registry-only npm/pnpm 8–9/Yarn Classic 离线冻结安装/构建、真实 readiness 及持久阶段/container/cgroup 对账。Core 仍为 gateway；pnpm 10/11、Yarn Berry、Python sandbox 缓存安装及未支持 origin 明确拒绝，真实宿主验收未测。
- DNS 超时后的未知获取 job 阻断准入；仅在精确 resolver 与调用者退出、资源对账及残留工作区清理完成后恢复 readiness。保留未知消费者输入，不重跑中断 key；清理失败释放操作锁但继续阻断 readiness。
- HTTPS deadline/取消错误分类保留存活 DNS worker 证据；真实 request wrapper 测试覆盖上游/代理 DNS、unknown journal、暂存目录/owner lease 保留及安全 readiness 恢复。

## 0.4.4

- 四个管理工具在通用调用入口拒绝 Console cookie；专用 Console REST 保留 Origin/会话/请求体绑定的 CSRF。连接/探测在锁等待后和解密前拒绝凭据版本变化。内存诊断不读取命令参数与环境，Core 安装 Debian 准确 Perl 安全版本，不增加扫描例外。
- 管理员外部 HTTP 配置提供共用 REST/MCP 离线计划、摘要绑定确认应用、本人状态与取消。连接失败保留配置；初次和再次发现都隔离变化分类，不扩大访问。
- 流程校验当前管理会话/token/权限、凭据版本与 CAS，限制协作期限，保护连接所有权并原子提交完成日志。自带 Skill 分别路由 ZIP、Git 与外部来源。
- 独立内置 `/mcp/manage` 默认关闭，要求明确客户端资源 allowlist 和管理同意，只开放四个外部配置工具；拒绝业务/外部令牌及跨资源授权码/刷新使用。
- 精确创建/更新目标绑定派发、排队、计划及幂等完成记录。私有本人目标修改要求当前管理员、Origin/会话 CSRF、复核后单次确认、版本 CAS 与原子审计；JWT/令牌族 scope 及业务授权不扩展。
- Console 与公共同意明确展示资源/scope/精确目标，使用有编辑保护的居中弹窗、完整目标分页及短暂保存反馈。[管理契约](docs/zh-CN/oauth-external-management-design.md)与[外部配置契约](docs/zh-CN/external-mcp-configuration.md)说明实际行为。真实客户端/peer 联调仍未验证。多实例路由、海量目录检索和 Git 执行器不纳入本版。

## 0.4.3

- 本人在 Gate 明确确认即可为现有 OAuth 授权新增、重新确认或移除 MCP/工具。同一 bearer 与刷新令牌族在不变的 OAuth scope 上限内跟随 live 工具范围，同 scope 工具不需要客户端再次 OAuth。
- 更新保留会话/Origin/CSRF、绑定确认、当前权限、版本 CAS 与原子审计。不补造缺失 scope，较窄令牌族保留自身限制，其他授权不变。
- 配置 Form/JSON 编辑保留未知字段和精确草稿，提供明确 Gate 启动/重启策略及准确重载反馈。新 MCP 默认启用但不自动启动，应用不会悄悄启动服务。
- Console 配置文件读取及修改规范化路径并检查配置目录边界，阻止符号链接越界。
- 工具目录、资源授权和分类审核正确解析内置工具来源。
- 范围弹窗在工具滚动时保留控件与操作，MCP 选择展示 ID 并支持名称搜索，授权支持完整本人数据搜索和分页。
- HTTP 自动协商识别精确的初始旧版初始化拒绝，展示实际协商版本，不重放业务调用。

[候选验证](docs/zh-CN/development-validation.md)。正式发布、平台资产及独立视觉验收分别记录。

## 0.4.2

0.4.2 增加绑定精确服务/IP/端口的内网 HTTP MCP 授权，提供实时管理员检查、CAS、明确内联确认、默认拒绝与撤销重检，保留 HTTPS 验证及禁止重定向边界。

[Validation / 验证记录](docs/zh-CN/release-validation-0.4.2.md) · [Release notes / 发行摘要](packaging/release-notes.md)
