# 0.4.9 候选与正式发布验证

## 源码与 Patch 范围

0.4.9 在同一 MCP 服务重启、网络/健康检查临时中断恢复或平滑升级时，只要工具定义保持未变，即可保留其分类、原审核时间戳以及已确认的 OAuth 授权快照。服务离线后工具立即退出可调用目录，在保障离线安全性的同时，免除服务恢复后重复授权与重新审核的负担。

唯一运行时版本源为 `src/lingshu_gate/_version.py`，本版本更新至 `0.4.9`，并同步更新双语 README、更新记录、发行说明和使用指南。已有分组/实例会话、根路径 Console、按需目录、OAuth 编辑及干净打包链路继续保留。已占用的 v0.4.5、v0.4.6、v0.4.7 和 v0.4.8 标签保留原修订；本源码使用全新的 `v0.4.9` 标签身份。

## 已执行验证与测试证据

候选版本验证覆盖静态分析、单元测试与集成回归：

- **静态分析与代码规范**：
  - Python 代码规范：`ruff check .` 检查通过，零告警。
  - 类型检查：`mypy --platform linux` 检查全部 165 个源码文件，零类型错误通过。
  - 仓库 Git 规范：`git diff --check` 通过，无行尾空白或格式边界违规。
- **后端测试**：
  - MCP 审核生命周期与持续 OAuth 授权范围测试套件全部通过（30 项测试通过）：
    - `tests/test_mcp_review_lifecycle.py`
    - `tests/test_oauth_continuous_scope.py`
  - 未变工具在服务重启及平滑升级后保留审核快照与授权快照，无需重复授权。
  - 离线工具在故障或服务停止时立即从网关可调用目录退出，恢复后安全重连。
  - 新增工具默认进入 `pending` 状态且权限为 `unknown`，须显式审核与发布。
  - 工具定义变化、显式注销及服务删除重建严格遵守原有失效边界。
- **前端检查**：
  - TypeScript 类型检查：`npm run typecheck` 通过（含 `tsconfig.app.json` 与 `tsconfig.node.json`）。
  - 静态 UI 契约：`npm run check:ux` 校验全部 19 个页面、11 个可搜索页面和 2 个阶段式工作流。
- **部署与配置**：
  - `docker compose config --quiet` 验证部署配置格式正确。

## 数据库迁移与升级路径

升级至 0.4.9 不引入新的数据库迁移。0.4.8 的数据库结构保持前后兼容。SQLite 单写入者语义、无特权 Core 执行以及原子事务审计边界保持不变。

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
