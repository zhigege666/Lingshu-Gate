# Lingshu Gate 文档

[English](../README.md) · [项目 README](../../README.zh-CN.md)

本组文档描述当前 Gate 产品边界。英文是导航和发行打包的默认语言，简体中文文档与其同步维护。

| 指南 | 用途 |
|---|---|
| [性能评估](performance-review.md) | 可复现的合成数据基准测试与验证边界 |
| [保留策略](retention.md) | 日志、事件、调用独立保留期限，清理预览及确认 |
| [调用内容记录](invocation-recording.md) | 按需启用限长脱敏内容、本人隔离、审计能力及保留边界 |
| [架构](architecture.md) | 组件、请求路径、持久化与信任边界 |
| [配置](configuration.md) | 环境变量、目录、Manifest、凭据和反向代理设置 |
| [MCP 网关](mcp-gateway.md) | 网关入口、协议协商、下游 HTTP/stdio、发现、分类和调用 |
| [按需工具发现](on-demand-tools.md) | 六个有界发现/会话入口、每客户端模式、保留原授权与合成规模基准 |
| [按需目录集成溯源](on-demand-integration.md) | 精确分组提交映射、冲突处理与定向安全证据 |
| [按需目录集成验收记录](on-demand-integration-validation.md) | 精确测试检查点、物理/分组实测及原生 worker 证据 |
| [Gate 功能集成候选](gate-feature-integration.md) | OAuth/catalog/group/Native 溯源、a3b57f7 前端验证、最新 ed34c5a wheel／Linux 包验收及继承的后端证据 |
| [MCP 分组](mcp-groups.md) | 逻辑组、显式实例、管理员管理和合同分区 |
| [MCP 分组路由适配](mcp-group-routing-contract.md) | 按需目录内部接口与绑定认证连接的实例会话 |
| [项目交付](project-delivery.md) | 上传、构建、部署、启动流程，`gate_*` 工具和自带 Delivery Skill |
| [外部 MCP 配置](external-mcp-configuration.md) | 管理员现有 HTTP MCP 离线计划/应用/状态/取消；开发候选 |
| [管理员 OAuth 配置](oauth-external-management-design.md) | 默认关闭的管理资源，精确目标与 scope/令牌族隔离；真实客户端尚未联调 |
| [Git 导入与网络设置](git-import-network.md) | 交付网络版本、受控 Git 来源、确定性依赖工具与执行器边界 |
| [Native 隔离执行器](native-executor.md) | 已实现 Linux/rootless adapter、准备/readiness、npm/pnpm 8–9/Yarn Classic 有界缓存及剩余宿主验收 |
| [Console 交付工作区](console-delivery.md) | 私有交付草稿、确认、冲突恢复与交付记录 |
| [Git 执行器实现与落地决策](git-executor-decision.md) | Native 实现、默认 Core 限制及剩余宿主验收 |
| [部署](deployment.md) | Docker Compose、原生服务、生产加固、备份、升级和回滚 |
| [运维](operations.md) | 健康探针、日志、事件、诊断、运行时缓存、审计和故障检查 |
| [本地开发](local-development.md) | 源码环境、Console 构建、测试套件和仓库约定 |
| [根路径 Console 入口候选](root-console-entry.md) | 根入口 HTML/JSON 协商、旧书签、资源边界及候选验证 |
| [UI 交互约束](ui-interaction-contract.md) | 新增或迁移 Console UI 的验收规则、编辑安全、证据与独立评审 |
| [浏览器回归](browser-regression.md) | 隔离真实后端 Playwright、合成大列表、场景编号及证据边界 |
| [外部 OAuth 资源访问](external-connections.md) | 默认关闭的 JWT 验证、信任配置、个人委托与实际接入边界 |
| [内置 OAuth 授权](builtin-oauth.md) | 复用已有用户、静态客户端、同意、刷新/撤销与公网代理放行清单 |
| [OAuth Console 密度](oauth-console-density.md) | 开发中的范围编辑器与已配置管理布局、不变授权边界及合成证据 |
| [发行产物](releases.md) | 平台归档、checksum、SBOM、构建元数据、离线镜像和发布规则 |
| [0.4.0 验证记录](release-validation.md) | 已执行检查、合成截图与剩余验收缺口 |
| [0.4.1 验证记录](release-validation-0.4.1.md) | OAuth 兼容/配置、本人授权与运行版本证据 |
| [0.4.4 验证记录](release-validation-0.4.4.md) | 外部 HTTP 管理、Skills、资源隔离及验收缺口 |

运行中的 Gate 会在 `/docs` 提供 API Schema。安全策略和报告方式见 [SECURITY.zh-CN.md](../../SECURITY.zh-CN.md)。

## 稳定入口

| 入口 | 用途 | 认证 |
|---|---|---|
| `/` | 浏览器 Console；程序请求得到 JSON 服务信息 | 登录页公开，Console 操作需要认证 Cookie |
| `/v1/meta` | 不受 Accept 影响的 JSON 服务信息 | 公开元信息 |
| `/console`、`/console/` | 保留 query 与 hash 的 `/` 兼容跳转 | 保留 Console 认证边界 |
| `/docs` | OpenAPI UI | 由部署策略决定 |
| `/mcp` | 无状态 Streamable HTTP MCP 网关 | Console Cookie 或 Bearer Token |
| `/v1/*` | 控制与操作 API | 按权限检查 |
| `/healthz` | 进程存活 | Probe |
| `/startupz` | 初始化完成 | Probe |
| `/readyz` | 请求路径就绪 | Probe |

编排器应使用上面三个用途明确的端点。
