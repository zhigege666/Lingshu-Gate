# Git 导入与网络设置

[English](../git-import-network.md) · [项目交付](project-delivery.md)

## 设计与执行边界

系统设置作为 Console 一级入口，页内采用横向标签；先实现“网络与依赖”。命名代理配置支持不可变修订、停用、引用检查、乐观锁、脱敏状态和受控测试。配置使用 `system_settings.manage`，调用使用 `network.use`，并同时保留原有操作、工具和令牌权限。两项权限互不授予。

Git 拉取和依赖安装分别配置默认值。项目明确选择 `inherit`（计划时解析当前默认）、`direct`（不使用代理）或 `profile`（命名修订）。npm registry 和 Python index 是独立 HTTPS 地址，不能作为代理别名。凭据仅引用现有加密凭据存储；普通返回、审计、计划、Manifest 和产物不含代理地址或秘密值。运行时 MCP 不继承交付网络配置。

Gate 当前**没有生产安全网络执行器**。本地构建器以操作者账号执行子进程，净化环境变量不等于操作系统隔离；Core 禁止本地执行。Git 解析/拉取、代理测试和指定网络的依赖安装均以 `safe_executor_unavailable` 关闭失败。本变更新增供独立审查执行器实现的端口，不新增启用宿主执行的开关，不挂 Docker socket，不修改全局 git/npm 配置，不扩宽 Core 权限。

## 来源到交付

缺少执行器同时是仓库实现缺口，不只是操作者部署条件。原生/local 也没有生产 adapter；Core 完整交付还缺明确远程阶段/产物/运行目标契约。详见[执行路径与落地决策](git-executor-decision.md)。以下控制与计划描述的功能实现尚不完整。

来源表单接受 HTTPS 仓库 URL、分支/tag/完整 commit、相对项目子目录、私有仓库凭据引用、独立 Git/安装网络选择，以及 Node/Python 运行模板。任何网络请求前先验证输入。安全执行器必须从实际环境解析完整 commit SHA；歧义或不存在的 ref 均失败。导入计划绑定 SHA、来源选择、凭据修订、网络修订、策略修订、限制和摘要。拉取单独要求明确确认及幂等键，固定取该 SHA，不重新解析移动分支。执行器输出有界 ZIP，不输出 Git 工作目录。Gate 经 `ProjectUploadStore` 验证并导入，附上源码/文件清单摘要、仓库 commit、所选修订和来源记录，继续原有构建部署链路。

预检与 BuildPlan 保持可审查；依赖安装和构建要求自己的确认及摘要绑定。部署、覆盖、启动、取消和回滚保留原有 Project Delivery 边界及归属检查。新制品使用新目录；导入或构建失败不能替换已部署版本。部署复用现有目标补偿及明确回滚，不提供无缝 MCP 会话迁移。

## 网络与来源限制

本期仅支持 HTTPS Git。SSH/scp 语法以可操作的错误明确拒绝，`HTTP_PROXY` 不能实现 SSH；未来 SSH 执行器需单独审查 host-key、密钥引用及隧道策略。拒绝 `file`、`git`、`ext`、remote helper、URL userinfo/query/fragment、控制字符、类似选项的 ref 和修订表达式。Git 命令策略禁止 hooks、全局/系统配置、credential helper、重定向、submodule 递归与 LFS smudge。凭据在执行器内部短暂且限定来源注入，不进入命令参数；不继承 SSH agent。

默认 Git 主机策略只允许公网 `github.com:443`。管理员可显式增加精确 HTTPS 主机/端口，并为内网 Git 指定私网 CIDR。每个 DNS 解析地址都须符合主机策略；私网需要明确管理员 CIDR，仍拒绝环回、链路本地、多播、未指定地址及元数据端点。执行器必须固定已验证 DNS 地址、在连接及通过代理时执行目标策略，并拒绝重定向。远程 DNS 的 HTTP 代理也须约束上游目标，仅在 Core 检查 DNS 不足以保证安全。

代理测试仅接受服务端内置目标 ID 和 HEAD 方法，不接受任意 URL、body、重定向或端口；使用与拉取相同的安全执行环境，限时 5 秒、响应 4 KiB、有并发/频率限制、无自动重试。配置协议为 HTTP/HTTPS/SOCKS5/SOCKS5H，执行器按阶段协商支持。Git HTTP 传输可通过 libcurl 支持这些协议，但 npm/pnpm/Yarn 与 pip 不共享 SOCKS 支持保证；不支持的组合明确失败，不能静默直连。

快照限制为压缩 50 MiB、展开 200 MiB、3,000 文件。拒绝链接、路径逃逸、设备、歧义名称、敏感凭据路径/内容、submodule 和 LFS pointer。子目录为相对路径，不能逃逸或跟随链接。解析/拉取/导出各自限时并支持取消；不确定完成后不自动重放导入、构建、部署或启动，复用原有幂等操作协调。发送终止请求不代表完成，需执行器返回终态。

## 依赖计划契约

重启对账在受支持的单协调器接收新工作前，将丢失句柄的 `queued`/`running`/`cancel_requested` 持久化为 `interrupted`，释放四槽协调器队列，不代表释放执行器真实资源。`terminal=true` 结束协调器轮询；`execution_state=unknown`、`execution_terminated=false`、`requires_reconciliation=true` 明确保留未知执行结果，取消不能报成功。原导入与幂等键仍可查询，不恢复或盲重放写操作。未来 worker 须自行对账持久化任务/资源后再 dispatch，本修复不实现 worker。

执行器普通 `InterruptedError` 同样记录未知结果并保留代理引用保护。`SafeExecutionCancelled` 只供可信执行器在确认阶段及其所有子进程已终止后使用。协调器在执行前、或执行器已返回后处理取消可结束为已取消；仅发出取消请求不能。

代理删除保护跟随真实资源生命周期：未过期可复用计划、活跃/未知导入、保留的上传/构建和当前默认值保护固定修订。计划过期保护在规划/查看引用/删除时清理；已知终态导入释放自身引用。实际删除上传/构建时在同一数据库事务释放对应保护。历史计划、审计及不可变版本快照保留，不永久阻止删除；中断/未知执行仍保护到结果对账。

支持命令族：npm 9–11 + package-lock/shrinkwrap v2/v3（`npm ci`）；pnpm 8–11 + 对应格式锁文件（`pnpm install --frozen-lockfile`）；Yarn Classic 1.22.x + v1 锁文件（`yarn install --frozen-lockfile`）。Yarn Berry 的 immutable/PnP 行为不同，本期明确不支持。Node 必须安装但无锁文件时阻断；纯封装项目继续支持。

精确 `packageManager` 声明或明确项目覆盖固定工具版本。工具缺失或已安装版本不符时，在同一个待确认 BuildPlan 中增加**工具准备步骤**：安全执行器通过所选安装代理/registry 获取固定版本的官方 npm/pnpm/Yarn 分发包，校验官方 registry integrity，记录版本/来源/integrity，按 manager/version/integrity 在项目产物外隔离缓存。解包经过审查的官方分发包，不执行工具安装生命周期。Corepack 不是前置依赖：缺失或损坏时也走受控官方分发路径。禁止宿主全局安装/配置、浮动 latest、未经确认的 Corepack 下载或静默版本替换。Node engine 不兼容、下载或校验失败会停止构建；项目生命周期与工具准备均出现在安装/构建确认中。

只在实际所选项目根检查锁文件。声明/覆盖能唯一选中对应锁时，保留其他包管理器锁并警告；npm shrinkwrap 遵循其原生优先级。真正歧义返回结构化候选，可存入操作者私有、带修订的项目交付草稿，并原样返回计划/创建。未知工具版本及锁格式不兼容仍明确报错。计划只接受生成的准备/安装/构建命令及对应依赖。可选择安全相对文件形式的 Node `bin` 入口，如 `bin/ssh-mcp.mjs`；这不配置 SSH 密钥或执行远控。Python `requirements.txt` 保持原行为，不隐式支持 uv/Poetry 等。


没有精确声明或覆盖时，隔离计划明确展示固定策略版本：npm `11.6.0`、pnpm `9.15.4`、Yarn Classic `1.22.22`；宿主 PATH 不能证明执行器工具可用。隔离 Node 命令计划始终显式验证或准备版本缓存，即使宿主已有同版本工具。准备工具仅留在执行器缓存，不会悄然成为运行时工具。通过依赖工具执行 `scripts.start` 需另有同工具/版本的受审查运行环境；直接 Node `bin` 入口不需要该额外工具。

## 依赖支持矩阵

下列是有版本边界的源码/计划规则，不代表真实安装已验收。请求版本必须存在于官方元数据并满足对应 Node engines；未知版本失败，默认策略不能替换显式声明。

| 工具 | 锁格式 | 冻结命令 | Node 要求 / 边界 |
|---|---|---|---|
| npm 9–11，精确稳定版本 | package-lock / shrinkwrap 2 或 3 | `npm ci` | 核验精确官方分发的 engines |
| pnpm 8，精确稳定版本 | 6 / 6.0 | `pnpm install --frozen-lockfile` | 核验精确官方分发的 engines |
| pnpm 9–10，精确稳定版本 | 9 / 9.0 | `pnpm install --frozen-lockfile` | 核验精确官方分发的 engines |
| pnpm 11，含 11.5.0 | 9 / 9.0 | `pnpm install --frozen-lockfile` | 实际 Node >=22.13 **且**满足精确官方 engines；不自动升级 Node |
| Yarn Classic 1.22.x | v1 | `yarn install --frozen-lockfile` | 核验精确官方分发的 engines |
| Yarn Berry / pnpm 12 / 其他 Node 工具 | — | — | 明确不支持，不回退 Classic/npm/其他版本 |
| Python requirements | requirements.txt | 既有 `python -m pip install -r requirements.txt` | 沿用 Python/pip 流程，不新增 Poetry/uv/bootstrap 支持 |

pnpm 11.5.0 版本证据：[官方 package engines](https://github.com/pnpm/pnpm/blob/v11.5.0/pnpm/package.json)、[安装命令语义](https://github.com/pnpm/pnpm/blob/v11.5.0/installing/commands/src/install.ts)、[提交的 9.0 锁文件](https://github.com/pnpm/pnpm/blob/v11.5.0/pnpm-lock.yaml)。仅阅读官方元数据/源码，未安装或运行 pnpm 分发包。运行时/工具自动下载及依赖出口变更必须由受审查执行器禁止，不能依赖工具自身的默认行为。

执行器需先冻结输出再交给 Gate 导出。网络产物导出增加 30 秒、500 MiB 与 30,000 条目限制；拒绝外部/绝对/循环/指向忽略目录的链接及已知网络秘密，保留范围内的相对包链接。这是额外防线，不能隔离仍在运行的恶意进程。Git 文件摘要在计划、排队和 worker 复制前复核；快照变化要求重新导入和确认。

## 验收证据

新生成的 manager 启动 Manifest 带严格 `launch.toolchain` 工具/版本约束及工具名 command。只读 Manifest 校验不执行程序，仅检查服务管理员登记路径及文件元数据，准确版本仍为未验证。仅现有 local stdio/受管 HTTP 启动客户端在已授权启动后探测登记 Node 和复核 JS CLI，再执行同一组合。项目绝对 command、项目/宿主 PATH 均不能改选探测程序或解释器。缺失/不安全注册、版本漂移或不可验证明确阻断。参见[管理员注册与旧配置兼容](configuration.md#交付网络配置)。版本探测仍为空目录、无项目凭据、五秒/128 字节上限，但这些限制不证明信任。Core 不探测或执行固定工具；不安装运行工具、不借用构建缓存、不继承交付代理、不新增远程 bridge。pnpm 11 验证实际登记 Node >=22.13；复核的直接 Node 入口及未带 pin 的旧 Manifest 保留既有授权行为，不受该 manager pin 约束。本地执行仍不是沙箱，管理员工具完整性是前提。

0.4.0 验证在隔离的合成环境中执行 Python、Console 和浏览器回归。Git/网络测试使用受控 fake adapter，不连接用户仓库、代理或 SSH。双语布局覆盖 1600×900、1920×1080、2560×1080、2560×1440；实际计数、跳过项及 CI 状态见[验证记录](release-validation.md)。这些结果不证明真实拉取/install 可用：生产安全执行器仍缺失。

成功计划创建仅审计 actor、计划 ID 和 digest，不持久记录来源 URL/代理值。每轮最多清理 100 个过期未使用计划；每 actor 最多 32 个、全局最多 256 个未使用计划。任何 import 引用的计划均保留其来源，包括失败或取消状态。

命令行为依据：[Git 配置](https://git-scm.com/docs/git-config)、[npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/)、[pnpm install](https://pnpm.io/cli/install)、[Yarn Classic install](https://classic.yarnpkg.com/lang/en/docs/cli/install/)。
