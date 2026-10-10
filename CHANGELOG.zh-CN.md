# 更新记录

## 0.4.7

- 配置 writer 使分组目录快照失效后，重试复用本次请求已持有的不可变工具合同；复用绑定发布 revision 与冻结对象身份，已知过期输入在权限投影和比较前拒绝。
- 继续复核当前 token scope、grant、分类及分组/配置/Registry 版本；保留输入边界、共享缓存上限、最多三轮尝试，以及真实 5,000 实例/50,000 工具并发回归中的原 20 秒 reader 预算。
- 以新 patch 身份继续交付已整合的根路径 Console、分组/实例会话、按需目录、OAuth 编辑、账户菜单和干净打包；已占用的 v0.4.5/v0.4.6 标签保持不可变。
- 本地证据证明重试存在额外工作，不证明先前托管超时的唯一原因，也不承诺生产时延或 RSS 上限；正式发布继续执行完整 quality、native、Compose/Core、校验和、SBOM 与来源证明门槛。
- 准确源码检查、新候选和发布边界见配对的 [0.4.7 验证记录](docs/zh-CN/release-validation-0.4.7.md)。

## 0.4.6

- 修复缓存中的已关闭账户菜单在排队动画帧中重新夺取键盘焦点的问题；保留当前菜单的受控关闭与焦点恢复。
- 以新 patch 版本交付已整合的根路径 Console、显式分组/实例会话、有界按需目录、OAuth 编辑改进及干净 wheel staging；既有权限与可选宿主/客户端边界保持。
- 候选检查绑定精确源码和包摘要；实际本地 HTTP/stdio 验收与所属进程回收分别记录，不作为浏览器、远端宿主或 OAuth 验收。
- 已占用的 v0.4.5 标签保持不可变；v0.4.6 正式发布须通过既有 quality、五平台 native、Compose、双架构 Core/离线包、校验和、SBOM 与来源证明门槛。
- 已跑检查和剩余边界见配对的 [0.4.6 验证记录](docs/zh-CN/release-validation-0.4.6.md)。

## 0.4.5

- 浏览器 Console 迁移至根路径，保留内容协商 JSON 发现、稳定 /v1/meta、旧链接兼容、资源路径边界和经核对的 native 入口 smoke。
- 整合显式 MCP 分组/连接绑定实例会话、有界按需目录及可终止 schema 验证；派发保留实际工具/实例权限与凭据复核。
- 整合私有 OAuth 目录分页、完整选择解析、紧凑双语编辑器、无损草稿及写结果未知后的明确核对；scope/令牌族与选择上限保持。
- 补齐账户菜单受控关闭、键盘焦点恢复与内置角色双语名称，清理重复和空角色；展示已有工具分类合同变化原因，明确旧记录未保存字段摘要的限制。
- 连续 wheel 构建采用私有 staging，并准确校验静态清单/RECORD，覆盖 sdist-to-wheel，保留安全路径边界和冻结 worker 入口。
- 保留 Vite 8/Rolldown、关闭标识符 mangle 及 Console base /；包含经审查的 Windows 启动、TLS、协议/OAuth 与冻结导出修复。
- 可选 Native/Linux rootless Podman 在另行批准宿主准备/readiness 前保持关闭；真实 Podman、ChatGPT OAuth 及多机器验收仍未完成。
- [候选验证](docs/zh-CN/release-validation-0.4.5.md) 区分当前源码/包/CI 检查、历史浏览器失败及正式发布。

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
