# 第一阶段开发复核

[English](../stage1-development-review.md) · [外部配置](external-mcp-configuration.md)

这是已发布 0.4.3 之后的候选复核记录，不是发布或生产验收。源码版本及不可变发行说明保持原值。此验证未包含推送、合并、tag、发布、真实外部 MCP/SSH 调用、包下载、凭据供应或执行器部署。

## 候选与证据

- 基线：已发布 main `5fc3aaba94955e243598783166479136797733e4`；独立分支 `recovery/stage1-after-v043`。
- Header 提交：`4c61cb4fa9301805386122e27a2e88098c0770fc`；账户名称一次、翻译角色标签、版本/API/退出唯一入口，可访问受控菜单与焦点恢复。
- Header 浏览器证据：五项通过，包含 1600×900、1920×1080、2560×1080、2560×1440，中英与明暗共 16 种桌面组合。截图存在和浏览器检查不能替代独立像素复核。
- 外部配置：一个应用服务、薄 REST/MCP 适配器、迁移 `0010_gate_external_mcp_config` 与 `0011_gate_console_csrf`，复用现有配置保存、幂等、runtime 与分类服务。不绕过 UI 保存语义或 Git 执行 guard。
- 最终受审代码后端全量 1338 项通过、3 项跳过，耗时 310.06 秒。三个跳过均来自 `tests/test_mcp_playwright_interop.py`，原因是未提供指定 peer 安装；未安装依赖消除跳过。前端检查/构建及 69 个文件的 422 项测试通过。浏览器 6 项通过，耗时 20.9 秒：五项 Header、16 张桌面截图及真实 Chromium 同源 CSRF POST/修改请求体/重放用例。lint、mypy（115 个源文件）、身份、Compose 与 diff 检查通过。测试日志不是发行包核验。

本轮修复要求会话 REST 写入使用共享的严格 Console Origin/会话绑定及五分钟一次性 CSRF 票据，API bearer 验证保持独立。取票使用 POST，让浏览器自动提供 Origin。无 client 清理路径先查操作归属；运行时应用中断保留未知/对账状态；连接/刷新共享一次严格快照和首次分类计数；取消在排队锁与 SQLite 写事务内重查终态。合成回归覆盖缺失/跨源/重放/其他会话/到期票据、无 client 后继、未知取消及完成/取消竞态。

[管理员 OAuth 设计](oauth-external-management-design.md)保留明确 `operations.manage`、当前 admin/角色与 JWT/client/grant/family 上限、精确四个 builtin、预先授权的准确新建/更新目标，尚未实现授权。客户端元数据/challenge 机制已按官方文档核验；真实 ChatGPT 管理 scope 请求尚未观察，需要独立获准的非生产测试。

## 复核顺序

1. 当前 admin/session/token/角色权限及 scope/委托上限；其他管理连接不能消费计划。
2. 规范化 manifest/凭据/目标/动作摘要、期限与单次使用、新建/更新 CAS 及准确幂等重试。
3. 协作锁/HTTP 预算、取消、初次/刷新分类门禁、清理所有权与保守失去线程恢复。
4. 共用适配器、增量迁移、终态/幂等日志原子写、脱敏 manifest 与有界结构化失败。
5. 合成测试、中英文档和唯一自带 Skill 的 ZIP/Git/外部路由。

## 剩余边界

文件保存、runtime 与 SQLite 不属于同一事务。连接/刷新失败保留已保存配置。终态事务失败或重启需要对账，不能重放写入。完成后发出的 audit event 可能独立于终态事务失败。协作期限不能强制中断系统 DNS；SQLite 竞争仍可能使用现有 30 秒 busy 上限。配置/runtime manager 锁串行化此控制路径，未声明多 Core 或多实例并行能力。

已消费的过期计划在幂等日志关联操作存在时保留；现有保留策略移除操作后，下次创建计划通过索引查找清理过期孤立记录，不会让已消费计划再次可用。

当前 `instance_id=server_id`；文件 digest CAS 不能识别同字节删除重建的 generation。新服务复用 `ProjectDeliveryMcpService` 私有幂等辅助函数；未来可选择提取共用协调器，不是再建一条写入流程。真实 peer、部署、真实 socket/DNS 竞争中的取消及 root 独立视觉复核尚未验证。

## 保留的后续阶段与验收矩阵

| 阶段/工作 | 必须行为 | 仍需证据 |
|---|---|---|
| Git 执行器决策 | 选择原生隔离 Linux adapter、Core + 远程 worker 或独立 VM worker；保留 Core guard 与五方法端口 | 生命周期、源码/产物摘要、出口/工具完整性、整个沙箱取消/重启；禁止 host shell 替代 |
| 分组/多实例 | 明确逻辑组、稳定 instance/generation；不继承凭据或暗增授权 | 独立状态/配置版本、故障切换与获准选择；删除重建与晚响应竞争 |
| 有状态实例路由 | 整个 MCP 会话粘在同一目标；更新不能悄悄切换 | 并发用户/会话、过期映射、重启/取消及拒绝不安全写重试 |
| 固定 `current_connection` | 只返回当前有效连接获准概览及完整分页 | 用户/grant/token scope 隔离、实时撤销、cursor 失效；不暴露隐藏/全局计数 |
| 固定 `authorized_tool_search` | 获准 MCP/tool/client 小摘要；全结果搜索/分页 | 大列表、不能仅过滤当前页、隐藏名称/schema/计数不泄露 |
| 固定 `tool_describe` | 按需 schema，绑定当前获准工具及实例/schema 版本 | 搜索/描述/调用间撤销与 schema 漂移；描述不是鉴权输入 |
| 读/写/破坏调用入口 | 分开分类/权限校验；generic invoke 绝不能声明 read-only | 每次重查当前 ACL/scope/分类/实例，写不能作为读重放，破坏确认 |
| 直接工具兼容 | 固定入口旁保留常用 direct tools；客户端首次刷新一次 | 支持客户端真实证据；之后新增 MCP/工具不需反复刷新，权限变化仍即时生效 |
| 新鲜度提示 | 授权/配置版本仅供展示，不是 capability | 篡改或旧 metadata 不能授权，后端始终裁决 |

固定入口阶段在此登记为已授权后续范围；本切片未实现这些入口或新的搜索系统。
