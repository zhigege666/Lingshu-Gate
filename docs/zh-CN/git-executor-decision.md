# Git 执行缺口与落地决策

[English](../git-executor-decision.md) · [Git/网络契约](git-import-network.md)

本文是提案，不是已安装的执行器或隔离证据。功能尚未完成：同时缺具体 adapter 代码和隔离运行环境。在现有 Gate 旁安装 Git、pnpm 或 Docker 不能补齐。

当前待批准范围仅涉及 Git 拉取、依赖安装和构建。远程 MCP 运行时、stdio bridge 或新部署体系不在此范围，需另行明确决策。下文较广的运行讨论仅指出潜在后续缺口，不授权实现；现有 local 运行工具 pin 修复不新增 worker。

## 现有执行路径

| 代码 | 当前行为 / 缺口 |
|---|---|
| `config.py:Settings.runtime_role` | 原生默认 `local`，只接受 `local`/`core`，没有 worker 连接配置。 |
| `compose.yaml`、`compose.prod.yaml`、Dockerfile `core` | 默认 `core`，UID 10001、根/Workspace 只读、无引擎 socket、无 Git/Node 构建工具；定位控制面/外部 HTTP MCP 网关。 |
| `build_deploy.py:BuildDeployStore._require_local_execution` | 构建/部署/回滚要求 `local`，仅注入新端口不能启用 Core 交付。 |
| `build_deploy.py:build_upload`、`_run_build_job`、`_execute_plan_dag`、`_run_single_step` | 既有队列/IR/协调/持久化；安全计划转交可选端口，旧直连走 `_run_command`。必须复用此链路。 |
| `build_deploy.py:_build_subprocess_environment`、`_run_command` | 专用目录、净化环境、宿主 `subprocess.Popen`、输出/时间限制、进程组终止；没有文件系统/网络/cgroup 隔离，子孙进程可逃离进程组。 |
| `ports/safe_network_executor.py:SafeNetworkExecutor` | `resolve_commit`、`export_snapshot`、`probe`、`prepare_package_manager`、`run_command` 五方法仅协议定义，缺具体实现。 |
| `main.py:create_app` | 两个服务都不注入执行器，缺 factory/配置/readiness/生命周期。 |
| `git_import_mcp.py:GitImportService._executor` | Core 先被角色阻断，原生再被缺少 adapter 阻断。 |
| `network_settings.py:NetworkSettingsStore.settings` | 状态硬编码 false，需真实可信 adapter readiness。 |
| `build_plan.py:finalize_manifest` | 只生成本地 `managed_process` 和产物路径，没有远程制品/运行目标。 |
| `mcp_runtime.py:McpRuntimeManager.start_server` | Core 拒绝受管进程/容器，支持外部 HTTP MCP；远程构建不自动带来部署/启动。 |
| `mcp_container.py:build_docker_command` | 既有容器无网络、根/挂载只读；不是 install/build 沙箱，不能移除其基线。 |

原生/local 仍可构建可信上传项目，要求 Node/Python 与受支持的匹配工具已安装，且计划无需新安全端口；这不是不可信 Git 的隔离。两种部署的 Git 拉取、受控测试、指定出口及工具 bootstrap 都没有生产实现。默认 Core 原本也不能构建/部署/启动上传本地代码。功能目标尚未完成。

## 必须先决定范围

| 范围 | 代码 | 基础设施 / 代价 | 结果 |
|---|---|---|---|
| 先原生/local | 具体隔离 adapter、可信下载/出口、工具缓存、factory/readiness/生命周期 | 独立 Linux 执行账户/主机、受审查固定镜像、实际 namespace/资源控制器可用的 rootless 引擎、独立 Workspace/cache | 保留本地部署/启动；Docker Core 仍仅网关；Windows/macOS 需显式 Linux 执行主机。 |
| 默认 Core + 远程 worker | 上述代码，加认证阶段 RPC、源码/产物传输、持久化操作对账、远程部署/启动目标 | Core 外独立 worker 服务、mTLS/信任/秘密供应、镜像与缓存维护、配额及监控 | Core 协调全流程，不执行项目代码，不控制引擎。 |
| 独立 VM worker | 相同远程阶段/日志/摘要契约，构建作业使用运维供应的可丢弃 VM 边界 | VM 镜像、生命周期/配额、验证 guest 隔离、受控出口及清理；供应成本更高 | 可选更强主机分离方式；不是另一条 host-shell 回退，也未实现 adapter。 |

若默认 Docker 产品必须有全流程，建议远程 worker；接受仅原生交付则原生优先改动较小。当前进程内 `cwd`/结果端口及本地 guard 不能表示远程产物和运行目标，需先选择范围。尚未新增 daemon、引擎暴露、Core 权限、服务部署或真实凭据。

## 安全边界提案

Core 保留唯一权威 SQLite 写入者及现有 Project Delivery 协调器，负责 actor/权限、确认、源码/计划/配置摘要、幂等、代理固定修订及部署记录。worker 执行校验过的阶段，不另建交付流程。请求不可指定任意宿主路径、镜像、命令、凭据或探测 URL。网络秘密只经获准认证通道到可信下载/出口组件，不到项目代码、普通返回、日志或产物。

worker 在 Core 外使用独立账户，只有该账户接触受审查引擎；Core 和项目容器均无此能力。任务使用预加载 digest 固定镜像，禁止自动拉镜像，独立 PID/mount/user namespace、删除 capabilities、禁止提权、只读工具根、受限 Workspace/tmp、实际资源控制器。不得挂 Gate data/config/密钥、宿主 socket/home 或引擎控制。readiness 验证真实条件，缺项准确报错；只有容器命令不够。

依赖出口是最难缺口。bridge 加 HTTP_PROXY 不能约束 DNS/重定向/来源，也不能防 lifecycle 读取认证。提案的可信下载/缓存组件持有上游代理和凭据；Git、准确官方分发不运行源码 hook/filter。依赖获取不能执行项目 hook；pnpm hook、其他工具/bootstrap 及解析期代码必须禁用或拒绝。校验过的缓存不带秘密用于冻结安装/构建，未计划 lifecycle 网络获取失败。依赖网络的脚本/custom registry 流程需要单独审查出口/来源策略，不能因选代理就承诺支持。每项 npm/pnpm/Yarn 冻结缓存流程都需验证。

每阶段绑定 actor/operation、源码/计划/网络摘要、固定修订、限制、deadline、独立幂等键。worker journal 把键对应到唯一沙箱和输出摘要。不确定完成时只查询，不盲重放。取消/超时终止整个沙箱/cgroup 和所有 writer 再冻结输出；重启先对账 journal/容器 ID，未知结果阻断。

源码/制品采用有界流及文件清单/内容摘要，不信任 worker 路径。Core 再校验并写新制品；失败不替换当前部署。远程部署/启动需要独立目标句柄及 generation 乐观锁。stdio 项目需 worker 认证 HTTP bridge；Core 连接外部 Streamable HTTP，不能启动 worker 本地 Manifest。保留 grants/分类/按用户凭据语义；运行时不继承交付代理，更新可打断 session。

## 决策后实现

1. 严格配置/readiness/阶段/源码/产物契约及真实 factory，保留旧 local 行为和 Core 宿主 guard。
2. 具体有界 TLS/DNS/重定向 Git/测试/官方工具获取、不可变缓存及隔离冻结安装/构建，补离线 transport/container/journal 测试；区分代码/配置缺失与运行条件缺失。
3. Core 范围在现协调器扩展远程制品/目标，只允许验证过的远程 dispatch，禁止宿主回退，保留单独确认的部署/启动/回滚。
4. 提供操作者复核的镜像/服务供应文档；当前只做静态检查，不启动 daemon/引擎/网络服务/Git/install/部署。
5. 后续验收真实 namespace/controller、DNS/代理凭据、快照、工具 integrity、所有锁流程、恶意 lifecycle、超时/取消/重启、旧部署/回滚及双语桌面布局。

提案运行条件参考 [Podman run](https://docs.podman.io/en/latest/markdown/podman-run.1.html)和 [Docker rootless 资源限制](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources)。namespace/网络选项与主机 controller 委派需实际验证，不代表本分支已有运行沙箱。
