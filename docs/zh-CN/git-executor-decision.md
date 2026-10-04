# Git 执行缺口与落地决策

[English](../git-executor-decision.md) · [Git/网络契约](git-import-network.md)

本文不表示已有安装的执行器或隔离证据。未发布的源码获取/校验模块已基于可信后端契约实现，但生产 Git transport/隔离 adapter 和隔离运行环境仍缺失。在现有 Gate 旁安装 Git、pnpm 或 Docker 不能补齐。

第一阶段仅涉及 Git 获取和离线依赖/构建契约，首个隔离后端选择 Linux rootless OCI。远程 MCP 运行时、stdio bridge 或新部署体系不在此范围，需另行明确决策。下文较广的运行讨论仅指出潜在后续缺口，不授权实现；现有 local 运行工具 pin 修复不新增 worker。

## 首个获取/校验切片（未发布）

`ports/git_acquisition.py:TrustedGitBackend` 只提供有界安全 ref 解析和准确 commit 对象访问，是契约，不是 Git transport、pack 解码器或 CLI 实现。`git_acquisition.py:VerifiedGitAcquisition` 消费该契约，校验原始 SHA-1 commit/tree/blob 的类型、声明长度和对象摘要，生成 `VerifiedSourceSnapshot`。当前仓库仍只支持小写 40 位完整 SHA-1 ID；明确拒绝 SHA-256 仓库，不转换算法。兼容性摘要比较不是 SHA-1 碰撞检测，未来受审后端必须提供可识别碰撞的 Git 解码。获取时不再次解析移动 branch/tag。

检查根 tree 的全部后代，包括用户选定项目之外。导出直接读取对象，不 checkout，不运行 hooks/filters，不获取 submodule/LFS，不应用 attributes 替换或忽略规则。symlink、gitlink/submodule 配置、LFS pointer、不明确/不安全路径、敏感路径和扫描发现的凭据都明确拒绝。有效源码保留既有 ZIP 接口和 Core 文件清单/上传复验。内容扫描是有界启发式，不能证明不存在未知或混淆秘密。

限制在对象读取前和解析/复制中执行：对象读取/tree entry 各 10,000，commit metadata 64 KiB、单 tree 4 MiB、对象展开总量 216 MiB、源码 3,000 文件、展开源码 200 MiB、ZIP 输出 50 MiB、读取块 64 KiB。解析/fetch/export 上限 15/120/30 秒，零重试，检查单调 deadline。未来 transport 还必须在接收/解码中独立约束 50 MiB 压缩传输量；本片没有真实 transport，不能据此证明该保证。请求只能收紧，不能放宽这些上限。ZIP 内容也逐块扫描，覆盖跨块秘密。

`ExecutorReadiness` 要求实际 Linux/rootless、namespace、委派的 CPU/memory/pids 控制器和整组终止证据，以及各阶段网络证据；CLI 或能力集合不够。仅来源 adapter 不能满足 `SafeNetworkExecutor`，生产组合仍不注入执行器，设置仍显示不可用。scanner 取消在可信后端清理确认整组终止之前属于未知结果；不确定完成不发布快照。

`offline_build_contract.py` 定义不可变规范化依赖节点、完整 root/edge 闭包检查、精确 HTTPS origin 绑定、明确 SHA-256/384/512 SRI 和有界流式内容校验。它不解析 npm/pnpm/Yarn lockfile，也不能证明生产者没有漏掉 lockfile 依赖；完整图 adapter 仍缺失。缺失/弱/多选 integrity 及未审 Git/file/link 来源明确拒绝，不重写。不实现依赖下载器、缓存安装或 lifecycle 执行器。

`OfflineBuildRequest` 只带来源/文件清单/工具/图/缓存摘要、有界命令/资源限制和小型非网络环境 allowlist，不包含 credential material、代理、实时 registry、镜像选择或宿主路径。命令即使有 `--offline`，也必须有实际网络 namespace 断开证据。既有安全构建协调器未改，也尚未接入未来契约；后续离线派发移除 material 仍待实现。

合成对象/图/worker fixture 不运行 Git、网络、容器，不下载镜像/工具，不用 SSH 或真实凭据。这只验证模块，不代表 Git 联网或离线安装/构建验收。开发环境只读探测发现 Docker/runc CLI，但 cgroup v2 只读，没有可写的委派/终止控制，因此 rootless OCI 不可验收。不注入后端。

## 现有执行路径

| 代码 | 当前行为 / 缺口 |
|---|---|
| `config.py:Settings.runtime_role` | 原生默认 `local`，只接受 `local`/`core`，没有 worker 连接配置。 |
| `compose.yaml`、`compose.prod.yaml`、Dockerfile `core` | 默认 `core`，UID 10001、根/Workspace 只读、无引擎 socket、无 Git/Node 构建工具；定位控制面/外部 HTTP MCP 网关。 |
| `build_deploy.py:BuildDeployStore._require_local_execution` | 构建/部署/回滚要求 `local`，仅注入新端口不能启用 Core 交付。 |
| `build_deploy.py:build_upload`、`_run_build_job`、`_execute_plan_dag`、`_run_single_step` | 既有队列/IR/协调/持久化；安全计划转交可选端口，旧直连走 `_run_command`。必须复用此链路。 |
| `build_deploy.py:_build_subprocess_environment`、`_run_command` | 专用目录、净化环境、宿主 `subprocess.Popen`、输出/时间限制、进程组终止；没有文件系统/网络/cgroup 隔离，子孙进程可逃离进程组。 |
| `ports/safe_network_executor.py:SafeNetworkExecutor` | `resolve_commit`、`export_snapshot`、`probe`、`prepare_package_manager`、`run_command` 五方法仅协议定义，缺具体实现。 |
| `git_acquisition.py`、`ports/git_acquisition.py`、`offline_build_contract.py` | 已有有界原始对象导出、规范化依赖图与离线请求校验；可信 transport、完整 lock 图 adapter、缓存安装与真实离线 worker 尚缺。 |
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

首个隔离后端是 Linux rootless OCI。若默认 Docker 产品必须有全流程，远程 worker 仍需另行决定；当前进程内 `cwd`/结果端口及本地 guard 不能表示远程产物和运行目标。尚未新增 daemon、引擎暴露、Core 权限、服务部署或真实凭据。

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
4. 提供操作者复核的镜像/服务供应文档；首片仅本地代码/fixture，不启动 daemon/引擎/网络服务/Git/install/部署。
5. 后续验收真实 namespace/controller、DNS/代理凭据、快照、工具 integrity、所有锁流程、恶意 lifecycle、超时/取消/重启、旧部署/回滚及双语桌面布局。

提案运行条件参考 [Podman run](https://docs.podman.io/en/latest/markdown/podman-run.1.html)和 [Docker rootless 资源限制](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources)。namespace/网络选项与主机 controller 委派需实际验证，不代表本分支已有运行沙箱。
