# Lingshu Gate

自托管 MCP 网关：连接工具，限定谁可以调用，并记录调用结果。

[English](README.md) · [下载 0.5.7](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v0.5.7) · [开始使用](docs/zh-CN/getting-started.md) · [文档](docs/zh-CN/README.md) · [安全](SECURITY.zh-CN.md)

<img src="docs/images/console-refactor/dashboard.png" alt="Lingshu Gate Console：紧凑导航与运行总览" width="1200">

*当前源码 Console，以合成测试数据在 2560×1440 下实际截图；已发布的 0.5.7 是独立发行基线。*

## 适合哪些场景

- **统一受控工具入口：** 接入多个 MCP 服务并自动同步工具，通过一个 `/mcp` 入口按账号和客户端授权范围调用。
- **接入已有服务：** 通过明确配置的连接器访问私网 HTTP MCP，或将本地 OpenAPI 快照中的选定操作转换为工具。可信本地 stdio 和项目交付使用原生 Gate。
- **核对运行结果：** 查看调用决策，限制实际工具参数，并按需接入 Prometheus 指标或 OTLP 链路。

## 快速开始

| 目标 | 选择 | 入口 |
|---|---|---|
| 试用已发布版本 | 原生归档，或使用发行镜像的 Docker 本机试用 | [下载并启动](docs/zh-CN/getting-started.md) |
| 生产部署 | HTTPS 后固定 digest 的 Core，或托管原生服务 | [部署、备份和升级](docs/zh-CN/deployment.md) |
| 开发 Gate | 源码仓库和锁定依赖 | [本地开发](docs/zh-CN/local-development.md) |

### 预编译原生包

下载匹配系统、CPU 的归档及 `SHA256SUMS`，[校验](docs/zh-CN/releases.md)后解压并进入目录。Linux/macOS 运行 `./start.sh`，Windows 运行 `.\start.cmd`。Gate 本身不需要宿主安装 Python、Node.js 或 Git。

打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，在本机读取 `data/initial-admin-credentials.json`，登录、修改密码并重新登录。生成的初始文件会删除，旧会话会撤销。包内中英文 README 提供对应平台的完整步骤。

### 已发布 Docker 本机试用

校验并解压 `lingshu-gate-v0.5.7-docker-compose.tar.gz`，进入该目录后执行：

```bash
cp .env.quickstart.example .env.quickstart
docker compose --env-file .env.quickstart -f compose.quickstart.yaml up -d --no-build --wait --wait-timeout 120 core
docker compose --env-file .env.quickstart -f compose.quickstart.yaml exec core cat /data/initial-admin-credentials.json
```

打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，用本机一次性凭据登录并改密。该方式使用发行镜像、仅限 loopback 的 HTTP、认证、独立试用卷、UID/GID `10001`、只读根文件系统且无引擎 socket。PowerShell 第一行可使用 `Copy-Item`。端口和离线镜像说明见[开始使用](docs/zh-CN/getting-started.md)。

### 生产部署

使用包内默认 `compose.yaml` 和配对 `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md`：选择正式 digest，准备正确可读且受保护的 bootstrap 凭据、持久存储及启用 Secure cookie 的 HTTPS。按[部署指南](docs/zh-CN/deployment.md)配置精确代理、Origin、备份与升级。每个数据库只运行一个 Core。

### 从源码运行

需要 Git、Python 3.11–3.13、uv、Node.js 22.x 的 22.12+、24.x 或 26+，以及 npm。

```bash
git clone https://github.com/zhigege666/Lingshu-Gate.git
cd Lingshu-Gate
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run lingshu-gate
```

源码 Docker 构建在该仓库根目录执行 `mkdir -p runtime/workspace` 和 `docker compose up -d --build --wait --wait-timeout 120 core`。[本地开发](docs/zh-CN/local-development.md)说明独立路径、凭据和测试命令。

## 首次授权调用

[内置 demo 流程](docs/zh-CN/first-call.md)不需要外部服务账号或桌面 MCP 客户端。启动独立内存 demo，在 Gate 中接入并自动同步三个工具，为两个读工具保存只读策略，再创建独立只读调用者，再使用实际返回的引用和修订完成 `tools/list → gate_catalog_search → gate_tool_describe → gate_tool_invoke`。

核对成功审计、写入拒绝且计数不变、错误修订拒绝、demo 停止/恢复和调用者撤销。保存并连接时自动校验和同步工具，无需单独审核发布；访问仍须同时满足资源权限和 token scope。

## 0.5.7 — MCP 超时信息与迟到响应回读

MCP 等待期限到期时返回结构化的 `mcp_request_timeout`。调用方可以区分尚未派发的请求与执行结果未知的操作；超时不会被报告成远端进程已停止，也不会触发自动重试。

符合条件的共享 stdio 调用可使用返回的恢复句柄，通过 `gate_request_status` 或 `POST /v1/catalog/requests/status` 读取迟到响应。句柄绑定原身份、工具修订与运行时连接，每次读取都复核当前权限。按需模式默认入口由六个增加为七个，完整工具列表模式保持不变。

回读有容量与时间上限，仅在当前 Gate 进程内有效，不能跨 Gate 重启恢复，也不能替代远端作业接口。本版 HTTP 调用仅增加结构化超时信息，不支持迟到回读；收到完整响应仍不代表已经确认远端命令退出码。相对 0.5.6 不新增运行依赖或数据库迁移。参见[请求回读](docs/zh-CN/on-demand-tools.md)、[MCP 连接行为](docs/zh-CN/mcp-gateway.md)、[变更记录](CHANGELOG.zh-CN.md)和[双语发行说明](packaging/release-notes.md)。

## 架构总览

```mermaid
flowchart TB
    subgraph Clients["客户端与控制端"]
        AI["AI Agent / 编程助手"]
        Console["管理员 Web Console (/)"]
    end

    subgraph Gate["Lingshu Gate (网关与控制面)"]
        Gateway["MCP 网关 (/mcp) · 完整目录 | 按需发现模式"]
        Auth["认证与 RBAC 权限"]
        Governance["工具同步与权限策略"]
        Delivery["项目交付与构建引擎"]
        Audit["审计、保留策略与内容记录"]
    end

    subgraph Downstream["下游 MCP 服务"]
        Stdio["本机 stdio 进程"]
        HTTP["Streamable HTTP 服务"]
        Container["受管容器服务"]
    end

    AI --> Gateway
    Console --> Auth
    Console --> Delivery
    Gateway --> Auth
    Gateway --> Governance
    Gateway --> Audit
    Gateway --> Stdio
    Gateway --> HTTP
    Gateway --> Container
```

## 控制台重构（当前源码）

布局参考 [shadcn-admin](https://github.com/satnaing/shadcn-admin)，使用既有 React、Tailwind 和 shadcn/Radix 组件。导航、页面标题、搜索、表单与明暗主题采用同一套规范；保留的复杂 Ant Design 表格接入相同颜色和尺寸 token。

| 批次 | 覆盖范围 | 交互变化 |
|---|---|---|
| 1 | 登录、总览、MCP 服务与配置、工具目录/调试/权限 | 默认保存并启动，连接后自动同步；移除日常接入的分析、审核和发布步骤。 |
| 2 | 项目交付、构建/部署、日志、审计、诊断、缓存与网络设置 | 导入/构建自动校验和计划，筛选即生效；首次部署直接执行，覆盖或中断时确认具体影响。 |
| 3 | 成员、角色、资源授权、共享/个人凭据、Token 与 OAuth | API Token 一步进入创建；新建、缩权和配额修改一次保存；实际扩权展示差异；凭据保存后同步已授权且启用的绑定。 |

新增外部工具默认需要**读写授权**，远端 `readOnlyHint` 不会赋予只读权限。已有服务持续授权保留原级别，精确工具选择不会自动扩展。Schema 变化时重新 describe，无需发布；普通同步不改变权限策略修订，移除、替换、禁用和策略变化会使相应旧快照失效。内置管理工具继续受专用控制面权限约束。

以下为实际构建在隔离测试环境中的截图，使用合成数据，不代表生产实例或业务统计。

![工具权限：自动发现与可选策略](docs/images/console-refactor/toolClassifications.png)

![中文工具权限：一次保存生效](docs/images/console-refactor/tool-access-zh.jpg)

*中文权限编辑器为 1363×936 浏览器实拍；其余列表截图为 2560×1440。*

![项目交付](docs/images/console-refactor/builds.png)

![我的授权](docs/images/console-refactor/myConnections.png)

## 现有功能


| 功能 | 能力与边界 | 指南 |
|---|---|---|
| MCP 聚合网关与传输 | 统一认证的 Model Context Protocol 入口；无状态 JSON `/mcp`、Streamable HTTP 远程 MCP、原生 stdio、明确版本与有界旧协议协商。聚合工具，不提供通用 resource/prompt 托管。 | [指南](docs/zh-CN/mcp-gateway.md) |
| MCP 分组与实例会话 | 逻辑分组引用已有实例，不复制凭据且不自动授权；合同分区与连接绑定的实例会话。 | [指南](docs/zh-CN/mcp-groups.md) |
| 按需工具发现 | 默认七个入口，包含只读的超时结果查询；最多 20 个有权固定工具/分组及可选文本结果分页；每条授权保持独立范围。 | [指南](docs/zh-CN/on-demand-tools.md) |
| 超时结果查询 — 开发中 | 结构化 MCP 超时信息；符合条件的共享 stdio 调用可凭身份绑定的短期句柄查询晚到响应。不重放或取消调用，不确认远端退出状态，不跨 Gate 重启恢复。 | [指南](docs/zh-CN/on-demand-tools.md#超时请求结果查询) |
| 参数限制 | 对实际参数执行等值、候选集合、数值范围和字符串前缀限制，纯预览、版本化保存与原子审计。 | [指南](docs/zh-CN/argument-policies.md) |
| 私网 HTTP MCP 连接器 | 固定目标 relay/agent、独立凭据、有界会话，不自动重放业务。 | [指南](docs/zh-CN/private-connector.md) |
| OpenAPI 适配器 | 本地 OpenAPI 3.0/3.1 快照的选定操作、固定来源与绑定执行合同的工具名称。 | [指南](docs/zh-CN/openapi-adapter.md) |
| 标准观测 | 默认关闭的 Prometheus 聚合与 OTLP/HTTP 追踪，受控入口、有界导出。 | [指南](docs/zh-CN/telemetry.md) |
| 用户与 RBAC | 本地登录、注册审核、自定义角色和权限类型、服务/工具授权与到期、限定范围的个人 API 令牌及用户状态管理。 | [指南](docs/zh-CN/configuration.md) |
| 工具权限治理 | 连接后自动同步；外部新工具默认要求读写授权，可按需设置只读、读写、禁用或恢复默认，保存即生效。账号、Token/OAuth、精确范围和服务绑定仍独立校验。 | [指南](docs/zh-CN/mcp-gateway.md) |
| 内置 OAuth 与远程访问 | 明确启用的授权码流程，面向 OAuth 2.1 / PKCE 客户端：机密静态客户端、S256、每用户工具同意、加密 RS256 签名密钥、刷新轮换与撤销。独立公网同意页；不支持 DCR/CIMD，不宣称全面规范合规。 | [指南](docs/zh-CN/builtin-oauth.md) |
| 外部身份提供方 | 可选外部 RS256 JWT 校验，精确 issuer/JWKS/audience/resource/client 绑定、身份映射和仅本人可管理的委托。支持直连 HTTPS 或管理员维护的隧道配置；Gate 不创建隧道。 | [指南](docs/zh-CN/external-connections.md) |
| 服务配置与生命周期 | Manifest 表单/JSON 编辑、静态校验、应用/重载、启动/停止/连接、分区详情、健康、日志与重启历史。原生托管容器要求明确复核的 digest 固定镜像。 | [指南](docs/zh-CN/configuration.md) |
| 工具目录与调试 | 按服务筛选的工具目录与有效权限标识；Schema 驱动的表单/JSON 参数、默认值/示例、结果复核与本地结果内容搜索。执行时仍重新校验权限。 | [指南](docs/zh-CN/operations.md) |
| HTTP MCP 管理 — 开发中 | 离线计划/应用/状态/取消，合并精确内网许可，明确撤销/恢复及物理删除外部配置；旧授权不扩张。 | [指南](docs/zh-CN/external-mcp-configuration.md) |
| 加密凭据 | 共享凭据 MCP/REST 增删改查，版本校验、幂等、只写入原文及精确 HTTP 使用范围；个人下游绑定保持独立。 | [指南](docs/zh-CN/shared-system-credentials.md) |
| 业务账号与浏览器绑定 | 加密的个人/共享网站账号、明确的用户/角色及 MCP 目标、版本化密码库同步和隔离的逻辑会话。首个适配器要求专用可信的 agent-browser 实例；绑定不授予 MCP 访问权限。 | [指南](docs/zh-CN/business-credentials.md) |
| 可信项目交付 | ZIP 分析与可续传 MCP 上传、预检、摘要绑定 BuildPlan、有界构建日志/取消、部署预览与覆盖保护、启动及工具对账。原生执行要求信任项目源码，并非不可信代码沙箱。 | [指南](docs/zh-CN/project-delivery.md) |
| 私有草稿与恢复 | 加密且带版本的交付草稿、合并的校验/计划/执行流程、实际覆盖或中断确认、幂等 MCP 写操作及受保护的手动回滚。替换可中断服务，不做无缝会话迁移。 | [指南](docs/zh-CN/console-delivery.md) |
| Git、代理与依赖源 — 部分支持 | HTTPS 固定 commit、来源限额、加密代理不可变修订、独立 Git/install 与 inherit/direct/profile。本开发分支实现可选 Native/Linux 获取/代理测试/固定工具准备和 registry-only npm、pnpm 8/9、Yarn Classic 离线安装/构建；其他 manager cache 安装明确阻断，真实宿主验收未测。 | [指南](docs/zh-CN/git-import-network.md) |
| 个人工作区与文件引用 | 我的 MCP、连接、授权、调用、API 令牌和下游凭据；仅对明确支持的工具提供短期、用户/目标绑定的 `fileRef` 上传。 | [指南](docs/zh-CN/mcp-gateway.md) |
| 审计与可观测性 | 工具授权决策审计、调用统计、按权限限定的服务/工具日志范围、事件、诊断、内存/环境摘要、运行缓存及存活/启动/就绪探针。 | [指南](docs/zh-CN/operations.md) |
| 内容记录与保留策略 | 可选开启的脱敏、有界调用入出参记录；独立日志/事件/调用保留策略、清理预览和作业记录。7 天只是默认策略，定时 retention worker 默认关闭。 | [指南](docs/zh-CN/retention.md) |
| Console、API、自动化与发行包 | 中英文、明暗主题、桌面布局、筛选/分页、私有 REST/OpenAPI 和 CLI；带确认边界的 `gate_*` 工具与 Delivery Skill。原生包、Docker Core、离线镜像、校验和、SBOM 及备份/升级流程。 | [指南](docs/zh-CN/releases.md) |

完整操作入口见下方文档索引。[调用内容记录](docs/zh-CN/invocation-recording.md) · [Git 执行决策](docs/zh-CN/git-executor-decision.md)

## 项目交付与远程访问

上传、预检、构建、部署、覆盖、启动、取消和放弃保留各自后端权限；MCP 写操作绑定幂等键和摘要。Console 在目标任务内自动完成校验和计划，覆盖已有目标或中断运行服务时仅确认一次实际影响。私有草稿保持加密，部署差异可以查看，受保护快照可用时支持明确请求的手动回滚。参见[交付指南](docs/zh-CN/project-delivery.md)、[Console 交付](docs/zh-CN/console-delivery.md)和仓库自带 [Delivery Skill](.agents/skills/lingshu-gate-upload-build-start/SKILL.md)。

远程访问可使用 Gate API 令牌、内置 OAuth 或外部 RS256 IdP；OAuth 默认关闭。内置模式复用 Gate 用户，在单独的公网页面登录与同意工具范围；外部模式只验证 provider 签发的令牌。`direct` HTTPS 和 `secure_mcp_tunnel` 是管理员维护的网络选择，反向代理不能单独穿透 NAT，机器隧道密钥不能替代用户身份。参见[内置 OAuth](docs/zh-CN/builtin-oauth.md)与[外部身份/网络接入](docs/zh-CN/external-connections.md)。Console 和 `/v1` 保持私有，仅公开所选模式所需的 MCP、发现与 `/oauth` 路径。

## 安全默认值

- 认证默认开启；初始凭据随机生成且只保存在数据目录。
- 网络默认绑定回环地址；远程访问应放在 HTTPS 反向代理之后。
- 会话 Cookie 使用 `HttpOnly` 和 `SameSite=Lax`；HTTPS 部署应设置 `LINGSHU_GATE_AUTH_COOKIE_SECURE=true`。
- MCP payload 日志默认关闭。
- Secret 加密保存，响应中仅返回掩码元数据；Manifest 应使用 `${credential:<id>}` 引用。
- Tool annotation 只是提示。外部工具默认要求读写授权；只有本地策略能改变权限级别。每次调用仍检查账号、资源授权、Token/OAuth 范围和当前服务身份。
- Docker Core 服务会丢弃 Linux capabilities、禁止权限提升，并以只读方式挂载 workspace。

在单台受信任主机之外暴露 Gate 前，请先阅读 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## 发行下载

发行自动化构建以下归档：

| 目标 | 归档 |
|---|---|
| Linux x86-64 | `lingshu-gate-v<version>-linux-x86_64.tar.gz` |
| Linux ARM64 | `lingshu-gate-v<version>-linux-aarch64.tar.gz` |
| Windows x86-64 | `lingshu-gate-v<version>-windows-x86_64.zip` |
| macOS x86-64 | `lingshu-gate-v<version>-macos-x86_64.tar.gz` |
| macOS ARM64 | `lingshu-gate-v<version>-macos-arm64.tar.gz` |
| Docker Compose | `lingshu-gate-v<version>-docker-compose.tar.gz` |

Tag 发行还提供 `amd64` 和 `arm64` 的 Linux Core 离线镜像，以及应用 SPDX SBOM。每个原生包都包含 `SBOM.spdx.json`、`BUILD-INFO.json`、`LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和包型专用的中英文 README。解压前应按 `SHA256SUMS` 校验所选归档，详见 [发行产物](docs/zh-CN/releases.md)。

原生与 Compose 包还包含配对指南、中性示例、更新记录、安全说明、发行摘要和 Project Delivery Skill。可从[首次授权调用](docs/zh-CN/first-call.md)开始。

Core 管理的凭据加密保存；辅助进程使用独立受保护本地凭据文件。

## 支持矩阵

| 能力 | Linux 原生 | Windows 原生 | macOS 原生 | Docker Core |
|---|:---:|:---:|:---:|:---:|
| Console、REST API、`/mcp` 网关 | 是 | 是 | 是 | 是 |
| 外部 Streamable HTTP 下游 | 是 | 是 | 是 | 是 |
| 受管本机 stdio 下游 | 是 | 是 | 是 | 否 |
| 显式受管容器下游 | 本机容器引擎可用时 | 本机容器引擎可用时 | 本机容器引擎可用时 | 否 |
| 本机项目构建执行 | 需要对应宿主工具链 | 需要对应宿主工具链 | 需要对应宿主工具链 | 否 |
| SQLite 持久化 | 是 | 是 | 是 | 是，仅单个 Core 副本 |
| 发行架构 | x86-64、ARM64 | x86-64 | x86-64、ARM64 | Linux amd64、arm64 |

原生归档只捆绑 Gate，不会捆绑所有项目运行时。下游启动和构建能否跨平台运行，仍取决于项目自身的工具链、命令、路径和依赖；预检会在执行前报告缺失项。

## 支持边界

- 入站 `/mcp` 是无状态 JSON；不提供 GET/SSE、旧式独立 HTTP+SSE、通用 resources/prompts 或未经请求的服务端消息。下游 POST SSE 响应能力不扩大入站范围。
- SQLite 与配额为单 Core/单进程边界，不提供多租户或分布式配额保证。Core 不执行本地 build/deploy/start，不挂容器引擎 socket。原生可信项目执行不等于代码隔离。
- Git SSH、自动 hooks/submodule/LFS 和重定向凭据转发不支持。交付代理不会自动传入运行时 MCP，也不修改宿主全局 Git/npm 设置；准确版本 manager 运行要求管理员受审查的 Node/CLI 注册表，不自动安装工具。
- 已实现的自动化测试使用合成隔离环境；真实 ChatGPT/OAuth、用户 Git/代理与生产升级验收需要另行完成。不同平台的原生产物和镜像以该 Tag 的发布工作流实际结果为准。

## 文档

- [开始使用：原生、Docker、生产与源码](docs/zh-CN/getting-started.md)
- [第一次成功与拒绝调用](docs/zh-CN/first-call.md)
- [工具参数限制](docs/zh-CN/argument-policies.md)
- [私网 HTTP MCP 连接器](docs/zh-CN/private-connector.md)
- [选定 OpenAPI 操作](docs/zh-CN/openapi-adapter.md)
- [Prometheus 指标与 OTLP 追踪](docs/zh-CN/telemetry.md)

- [MCP 网关、协议、工具权限与文件引用](docs/zh-CN/mcp-gateway.md)
- [MCP 分组与路由适配](docs/zh-CN/mcp-groups.md)
- [按需工具发现模式](docs/zh-CN/on-demand-tools.md)
- [用户、配置、凭据与运行策略](docs/zh-CN/configuration.md)
- [业务账号与 agent-browser 绑定](docs/zh-CN/business-credentials.md)
- [内置 OAuth 管理与同意](docs/zh-CN/builtin-oauth.md)
- [外部身份与远程网络接入](docs/zh-CN/external-connections.md)
- [项目交付 API/工具与 Delivery Skill](docs/zh-CN/project-delivery.md)
- [Console 交付、私有草稿与回滚](docs/zh-CN/console-delivery.md)
- [Git 计划、网络配置与依赖源](docs/zh-CN/git-import-network.md)
- [Git 执行器实现与上线决策](docs/zh-CN/git-executor-decision.md)
- [Native 隔离执行器](docs/zh-CN/native-executor.md)
- [服务运维、调试、审计与诊断](docs/zh-CN/operations.md)
- [调用入出参记录](docs/zh-CN/invocation-recording.md)
- [保留策略与确认清理](docs/zh-CN/retention.md)
- [部署、备份、升级与恢复](docs/zh-CN/deployment.md)
- [发行包、校验和与 SBOM](docs/zh-CN/releases.md)
- [架构与安全边界](docs/zh-CN/architecture.md)
- [开发、API 与自动化检查](docs/zh-CN/local-development.md)
- [合成浏览器回归场景](docs/zh-CN/browser-regression.md)
- [有界性能测量](docs/zh-CN/performance-review.md)
- [UI 与可访问性验收约定](docs/zh-CN/ui-interaction-contract.md)
- [0.4.0 验证与截图来源](docs/zh-CN/release-validation.md)
- [0.4.7 验证与发行门禁](docs/zh-CN/release-validation-0.4.7.md)

## 参与改进

如果 Gate 解决了你的问题，可以 Star 便于再次找到项目，并使用 GitHub Watch → Custom → Releases 订阅发行通知。反馈问题时附最小脱敏复现，也欢迎提交带权限与失败案例的小型接入示例。[第一次调用指南](docs/zh-CN/first-call.md)适合试用或向同事演示。

## 开源协议

Lingshu Gate 使用 Apache License 2.0 发布，见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。第三方组件继续受各自协议约束；打包所需声明记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
