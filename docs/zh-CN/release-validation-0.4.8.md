# 0.4.8 候选与正式发布验证

## 源码与 Patch 范围

0.4.8 提供统一个人凭据管理的“我的授权”入口、MCP 持续授权范围、持久化到每条授权且默认按需的工具发现模式、可编辑调用配额以及显式分组用途区分。本版本将个人 API 令牌、Gate OAuth 授权和外部身份提供方授权整合至统一管理界面，移除分散的独立令牌页与常驻长说明条。

唯一运行时版本源为 `src/lingshu_gate/_version.py`，本版本更新至 `0.4.8`，并同步更新双语 README、更新记录、发行说明和使用指南。已有分组/实例会话、根路径 Console、按需目录、OAuth 编辑及干净打包链路继续保留。已占用的 v0.4.5、v0.4.6 和 v0.4.7 标签保留原修订；本源码使用全新的 `v0.4.8` 标签身份。

## 已执行验证与测试证据

候选版本验证覆盖静态分析、单元测试与集成回归：

- **静态分析与代码规范**：
  - Python 代码规范：`ruff check .` 检查通过，零告警。
  - 类型检查：`mypy --platform linux` 检查全部 165 个源码文件，零类型错误通过。
  - 仓库 Git 规范：`git diff --check` 通过，无行尾空白或格式边界违规。
- **后端测试**：
  - MCP 持续授权、Token 授权策略和授权级发现测试套件全部通过：
    - `tests/test_authorization_discovery.py`
    - `tests/test_continuous_authorization_runtime.py`
    - `tests/test_oauth_continuous_scope.py`
    - `tests/test_token_authorizations.py`
    - `tests/test_builtin_oauth.py`
    - `tests/test_external_oauth_http.py`
    - `tests/test_mcp_gateway.py`
    - `tests/test_oauth_live_scope.py`
    - `tests/test_oauth_paged_catalog.py`（全部 29 项测试通过）
- **前端检查**：
  - TypeScript 类型检查：`npm run typecheck` 通过（含 `tsconfig.app.json` 与 `tsconfig.node.json`）。
  - 静态 UI 契约：`npm run check:ux` 校验全部 19 个页面、11 个可搜索页面和 2 个阶段式工作流。
  - 单元与集成测试：`vitest run` 通过，78 个测试文件、477 项测试全部通过（0 失败）。
  - 生产构建：`npm run build` 使用 Vite 8 / Rolldown 成功构建 Console 与 OAuth 静态资源包。
- **部署与配置**：
  - `docker compose config --quiet` 验证部署配置格式正确。

## 数据库迁移与升级路径

升级至 0.4.8 会执行三项新增数据库迁移：
1. `token_authorizations`：持久化独立 MCP 范围策略、服务策略和 Token 调用配额。
2. `mcp_authorization_identity`：将服务生命周期身份绑定至授权，删除重建或替换信任目标后须重新确认。
3. `authorization_discovery`：持久化每条业务授权的工具发现模式（`on_demand` 或 `direct`）。

SQLite 单写入者语义、无特权 Core 执行以及原子事务审计边界保持不变。

## 支持边界

可选 Native/Linux rootless Podman 执行器默认关闭；真实 Podman 宿主、ChatGPT OAuth 客户端及多机器验收仍未完成。安装本版本不会自动准备这些资源、启用 OAuth 或扩大权限。

## 正式发布门禁

版本变更推入 `main` 后会自动启动创建 tag 与正式发行工作流。正式发布要求 11 项经来源证明验证的资产：
- 5 个平台的原生可执行包（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）
- 1 个 Docker Compose 部署包
- 2 个离线 Core 镜像（Linux amd64/arm64）
- 1 个应用 SPDX SBOM
- 1 个容器镜像引用清单
- 覆盖全部资产的 `SHA256SUMS`
