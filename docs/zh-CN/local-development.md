# 本地开发

[English](../local-development.md) · [文档索引](README.md)

Lingshu Gate 使用 Python 实现服务，使用 React/TypeScript 实现 Console。构建后的 Console 嵌入 Python 包，并在 `/console` 提供。

## 环境要求

- Python 3.11、3.12 或 3.13
- Node.js 22 和 npm
- `uv` 0.11.33，或 CI 固定的版本
- 用于容器验证的 Docker 与 Compose
- 仅在测试自带 Delivery 打包脚本时需要 PowerShell 7

## 仓库布局

| 路径 | 用途 |
|---|---|
| `src/lingshu_gate/` | Python 包、API、策略、运行时、持久化和嵌入 Console |
| `web/` | Console 源码、单元测试和 UX Contract 检查 |
| `tests/` | 后端、协议、安全、打包和启动测试 |
| `scripts/` | 本地启动、质量、容器策略、冒烟和发行工具 |
| `packaging/` | 原生启动器、PyInstaller Spec 和发行包资产 |
| `.agents/skills/lingshu-gate-upload-build-start/` | 本仓库维护的项目交付 Skill |
| `docs/` | 英文指南和 `zh-CN` 镜像 |

## 安装

```bash
uv sync --frozen
npm --prefix web ci
```

把 Console 构建到 `src/lingshu_gate/static/console`：

```bash
npm --prefix web run build
```

运行 Gate：

```bash
uv run lingshu-gate
```

测试写操作时使用临时且已被仓库忽略的目录：

```bash
export LINGSHU_GATE_DATA_DIR="$PWD/local/data"
export LINGSHU_GATE_CONFIG_DIR="$PWD/local/config/mcp.d"
export LINGSHU_GATE_ALLOWED_ROOT="$PWD/local/workspace"
uv run lingshu-gate
```

不要在开发环境复用生产 Data 或凭据密钥。

## 后端检查

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
```

迭代时可以运行聚焦测试，请求评审前再运行完整套件：

```bash
uv run pytest -q tests/test_mcp_protocol_current.py
uv run pytest -q tests/test_project_delivery_mcp.py
uv run pytest -q tests/test_access_control.py
```

执行子进程的测试必须使用临时目录、受限超时和无副作用 Fixture。禁止下载或执行无关项目作为测试 Fixture。

## Console 检查

实时开发 Console 时，保持 Gate 运行，并在另一个终端启动 Vite：

```bash
npm --prefix web run dev
```

打开 `http://127.0.0.1:4173/console/`。开发服务器默认把 Gate API 请求代理到 `http://127.0.0.1:8000`；只有本地 Gate 使用其他 Origin 时，才需要在启动 Vite 前设置 `LINGSHU_GATE_DEV_PROXY_TARGET`。

```bash
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
```

`check` 会运行 TypeScript 和仓库 UX Contract。Console 变更还应在窄屏和宽屏下检查认证、加载、空状态、错误和权限拒绝状态。

不要手工编辑 `src/lingshu_gate/static/console` 下的生成文件。修改 `web/` 后重新构建。

## Pull Request 检查

**Continuous integration** 集中运行仓库身份、版本与依赖检查、Ruff、Mypy、Console
UX 测试、TypeScript 和生产构建。Python 3.12 运行完整测试后，将本次工作流的
Console 产物共享给 Python 3.11、3.13 兼容性任务。**CI result** 始终报告结果，
源码或兼容性任务失败、取消、被跳过都会使汇总失败。CodeQL 和容器检查独立报告。

普通 UI 和 README 修改不再启动五平台原生打包矩阵；版本、依赖、打包、启动入口、
运行环境、身份策略和发行工作流变更仍会触发。打包 PR 在固定工具链中运行针对性的
发行测试；正式发行独立重跑完整源码与产物检查，并重新构建资产，不复用 PR 产物发布。
容器 CI 校验镜像与 Compose，不重复前后端测试套件。

## 容器检查

```bash
docker compose config --quiet
docker build --target core -t lingshu-gate:dev .
```

确认镜像以预期非 Root 账户运行、能够进入 Ready、不包含本机项目工具链，并且没有获得容器引擎 Socket。容器测试不得把服务发布到回环地址之外。

## 身份检查

仓库身份门禁会扫描源码、文档、脚本、配置和生成的 Console 资产中的第一方身份与内容，同时只报告 Rule ID 和位置。依赖锁文件，以及打包的第三方许可证或 SBOM 元数据不属于这项身份内容策略；它们继续由独立的安全与许可证检查负责。

```bash
uv run python scripts/quality/check_repository_identity.py
```

仓库树扫描会排除生成的 Build 和 Release 目录。打包后，产物模式会递归检查每个最终资产及归档成员中的第一方身份与内容：

```bash
uv run python scripts/quality/check_repository_identity.py --artifacts dist/release
```

发行维护者还会检查整理后的 Commit Graph 中的第一方身份与内容，包括曾被跟踪在生成目录名下的文件：

```bash
uv run python scripts/quality/check_repository_identity.py --history
```

不要为了消除失败而削弱、打印或复制基于摘要的策略规则。修复报告的文件或产物，再重新运行检查。

历史模式包含一条精确限定的旧快照例外，针对
`web/test-fixtures/mcp-config-editor.tsx`；当前源码已在
`4556352c4671efa7a810d129adf0d561b820363f` 中修正。
`scripts/quality/check_repository_identity.py` 中的记录绑定七个完整旧提交 ID、
文件路径、Git Blob ID、内容 SHA-256，以及第 12、14、20 行的三条 `TXT-001`
发现，所有字段都必须匹配。启用历史模式时，CLI 会明确提示这项策略；历史内容并未被删除。

例外只适用于这些旧快照。即使字节完全相同，只要在其他提交或路径中重新引入，仍会失败，
后续再次删除也不能绕过。提交消息、其他发现、当前文件和最终产物仍严格检查。
不得自动扩充记录，也不得改成按分支、日期、整个路径或整条规则跳过检查。
普通修正提交无法清除既有 Git 对象，这条限定记录用于避免重写共享历史。

## 发行检查

发行工作流会在匹配的操作系统和架构上构建每个原生归档。在匹配的本机上，维护者可以构建一个 Target：

```bash
uv run python -m scripts.release.build_native --target linux-x86_64
```

独立构建 Compose 包：

```bash
uv run python -m scripts.release.build_docker_bundle
```

发行测试会校验归档名称、必需法律与文档文件、启动器行为、Checksum、SBOM 结构、构建元数据、安全路径和版本/Tag 一致性。

## 变更指南

### 协议和运行时

- 只实现发行版固定的协议版本。
- 传输解析与 Registry、授权策略保持分离。
- 保持无状态的按请求隔离和受限超时。
- 每项协议变更都增加 Conformance 和失败测试。

### 访问和凭据

- 路由检查和工具调用检查必须一致。
- 发现和分类绝不能自动授予权限。
- API Token Scope 不能超出主体权限。
- Secret 值必须加密保存、在响应中掩码，并且不进入结构化日志。

### 项目交付

- 保持不同确认阶段和严格请求 Schema。
- 写效果绑定当前摘要和幂等键。
- 网络超时后先检查资源状态，再判断完成情况。
- 构建计划保持准确，并拒绝调用方替换命令。

### 持久化

- Schema 更新保持确定性，并覆盖全新数据库和升级测试。
- 相关 SQLite 状态使用事务，Manifest 文件使用原子替换。
- 测试不能依赖顺序、墙钟时间或开发者机器路径。

### 文档

英文与简体中文文件同步更新。命令、路径、环境变量、工具 ID、归档名称和安全声明必须匹配同一代码树。

## 评审前

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
docker compose config --quiet
uv run python scripts/quality/check_repository_identity.py
git diff --check
```

在 Pull Request 中记录命令和结果。禁止提交本机 Data、凭据、依赖目录、上传/构建状态、日志或发行归档。
