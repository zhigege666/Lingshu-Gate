# 为 Lingshu Gate 贡献

[English](CONTRIBUTING.md)

感谢你改进 Lingshu Gate。贡献应保持网关核心精简且与具体厂商无关，并让安全敏感行为容易审查。

## 开始之前

对于缺陷或范围明确的改进，请创建 Issue 或 Draft Pull Request，并说明：

- 问题与预期行为；
- 受影响的部署方式和操作系统；
- 已移除 Secret 的最小复现；
- 可能的安全和升级影响。

对于认证、授权、凭据、协议协商、项目执行、持久化 Schema 或发行打包变更，请在实现前先说明边界设计。

安全漏洞应按 [SECURITY.zh-CN.md](SECURITY.zh-CN.md) 报告，不应使用公开 Issue。

## 项目范围

Lingshu Gate 负责以下产品领域：

- 认证 MCP 网关与下游 HTTP/stdio 运行时；
- 配置、生命周期、工具注册、分类、授权和审计；
- 加密凭据、健康、诊断、日志、事件和运行时缓存；
- 受控的项目上传、构建、部署、启动和对账；
- `.agents/skills/lingshu-gate-upload-build-start/` 中由本仓库维护的 Delivery Skill。

示例和接口应与具体厂商无关。下游行为通过通用 Manifest 和协议传输边界扩展。

所有位置统一使用以下身份：

- 产品：`Lingshu Gate`；
- Python 包：`lingshu_gate`；
- 命令与产物前缀：`lingshu-gate`；
- 环境变量前缀：`LINGSHU_GATE_`；
- 第一方 MCP 工具前缀：`gate_`。

`MCP` 只用于开放协议及其消息、传输、服务、工具、资源和提示词等通用概念。

## 开发环境

要求：

- Python 3.11、3.12 或 3.13；
- Node.js 22 和 npm；
- `uv` 0.11.33，或项目固定的兼容版本；
- 用于容器检查的 Docker 与 Compose。

安装并构建：

```bash
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
```

本地运行：

```bash
uv run lingshu-gate
```

默认地址为 <http://127.0.0.1:8000>。开发时请使用可丢弃的 `data`、`config` 和 `workspace` 目录。

## 质量门禁

请执行覆盖本次改动的检查。请求评审前的完整基线为：

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
docker compose config --quiet
git diff --check
```

依赖变化时，应使用项目工具更新锁文件，并确认 `requirements.lock` 与冻结的 `uv export` 输出一致。

测试应覆盖成功路径与失败关闭路径。安全敏感写操作需要覆盖授权、确认、幂等、摘要冲突、脱敏和中断操作。

## 文档

英文是默认文档语言。对 `README.md` 或 `docs/*.md` 的任何用户可见变更，都必须在同一 Pull Request 中更新 `README.zh-CN.md` 或 `docs/zh-CN/` 下对应的简体中文文件。

文档必须：

- 只使用同一变更中已经实现的命令和字段；
- 使用中性的示例 ID、主机和项目；
- 不包含真实 Token、私有路径、个人数据或复制来的产品文案；
- 先说明确认与失败边界，再介绍便捷流程；
- 链接到仓库内的权威页面，避免重复长篇契约。

## Pull Request

保持提交聚焦，并使用描述工程结果的中性提交信息。Pull Request 应包括：

- 简洁的变更摘要；
- 用户可见影响和安全影响；
- 已运行命令及结果；
- Console 变更的截图；
- 产物内容、配置或公共 API 变化时的发行说明影响。

不要提交生成的凭据、本地数据库、项目上传包、构建输出、依赖目录、运行日志或发行归档。

提交贡献即表示你同意按本仓库协议授权该贡献。
