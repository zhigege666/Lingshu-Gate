# Lingshu Gate 文档

[English](../README.md) · [项目 README](../../README.zh-CN.md)

本组文档描述当前 Gate 产品边界。英文是导航和发行打包的默认语言，简体中文文档与其同步维护。

| 指南 | 用途 |
|---|---|
| [架构](architecture.md) | 组件、请求路径、持久化与信任边界 |
| [配置](configuration.md) | 环境变量、目录、Manifest、凭据和反向代理设置 |
| [MCP 网关](mcp-gateway.md) | 网关入口、协议协商、下游 HTTP/stdio、发现、分类和调用 |
| [项目交付](project-delivery.md) | 上传、构建、部署、启动流程，`gate_*` 工具和自带 Delivery Skill |
| [部署](deployment.md) | Docker Compose、原生服务、生产加固、备份、升级和回滚 |
| [运维](operations.md) | 健康探针、日志、事件、诊断、运行时缓存、审计和故障检查 |
| [本地开发](local-development.md) | 源码环境、Console 构建、测试套件和仓库约定 |
| [发行产物](releases.md) | 平台归档、checksum、SBOM、构建元数据、离线镜像和发布规则 |

运行中的 Gate 会在 `/docs` 提供 API Schema。安全策略和报告方式见 [SECURITY.zh-CN.md](../../SECURITY.zh-CN.md)。

## 稳定入口

| 入口 | 用途 | 认证 |
|---|---|---|
| `/console` | Web Console | 认证 Cookie |
| `/docs` | OpenAPI UI | 由部署策略决定 |
| `/mcp` | 无状态 Streamable HTTP MCP 网关 | Console Cookie 或 Bearer Token |
| `/v1/*` | 控制与操作 API | 按权限检查 |
| `/healthz` | 进程存活 | Probe |
| `/startupz` | 初始化完成 | Probe |
| `/readyz` | 请求路径就绪 | Probe |

编排器应使用上面三个用途明确的端点。
