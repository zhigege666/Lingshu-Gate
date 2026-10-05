# Native 隔离交付执行器

[English](../native-executor.md) · [Git/网络合同](git-import-network.md) · [落地决策](git-executor-decision.md)

本开发分支实现了可选的 Native/Linux 适配器，使用本机 rootless Podman、管理员已审查并预加载的完整 digest 镜像、持久单所有者 job journal 和可信 HTTPS 获取。它复用 Gate 的 GitImport、ProjectUpload、BuildPlan、BuildDeploy 链，不增加 Core 引擎访问、远程 worker、stdio 桥接、部署服务或自动镜像拉取。源码版本保持 0.4.4，本功能尚未发布。

## 宿主准备合同

宿主准备由管理员负责，与代码开发分开。本轮测试未准备宿主 daemon、挂载、网络策略、凭据或生产项目。

Native Gate 应以专用非 root Linux 账户运行。该可信账户拥有本机引擎、日志和缓存；项目容器不挂载该账户 home、Gate 数据/配置、凭据、socket 或引擎存储。执行器 root 必须与 Gate 数据、配置、项目工作区分离。root 和其 `workspaces` 子目录须预先创建为账户拥有、无链接的 0700 目录；`workspaces` 必须是实际独立的 `tmpfs` 挂载，带 `nodev,nosuid`，总容量不超过 2 GiB。普通目录或剩余空间估计不满足 readiness。journal 与工具缓存位于 tmpfs 外的持久存储，最多保留四份受审分发，每次解包限 200 MiB/4,000 条；缓存满时由管理员清理，不自动替换。

本机 Podman 二进制必须为管理员审查的绝对可执行路径，不能由 group/world 写入。必须具备 rootless 用户映射、cgroup v2 及已委派的 CPU、memory、pids 控制器。Gate 强制本机 CLI 模式，不使用引擎 API socket；子进程只执行代码生成的固定 Podman 操作，不执行宿主项目命令或 shell。

固定 create 参数忽略镜像 volume、清除镜像/引擎默认环境，禁用隐式可写 tmpfs、restart policy 和镜像 health 命令。启动前将实际 container ID/job label 及每个内容 bind 的 source/destination/读写权限对照固定挂载。引擎配置带入的额外挂载在启动任何进程前拒绝；身份不匹配保留 unknown job，不 kill/删除不匹配资源。

镜像必须已存在于精确的 `registry/name@sha256:<64 位小写十六进制>` RepoDigest 下，不接受 tag、浮动 latest 或自动拉取。受审镜像必须提供 `/usr/bin/python3`、具有 SHA-1 碰撞检测的 `/usr/bin/git`、`/usr/local/bin/node`，且不含秘密或未审查启动代码。容器入口由 Gate 固定只读 runner 替换。Node 须满足所选分发包的精确官方 engines（pnpm 11 还要求 >=22.13），Gate 不升级 Node。[镜像合同配方](../../packaging/native-executor/Containerfile) 只接受已审查 base，不安装或下载任何内容。

设置 `LINGSHU_GATE_RUNTIME_ROLE=local`，以 JSON 对象配置 `LINGSHU_GATE_NATIVE_EXECUTOR`：

| 字段 | 含义 |
|---|---|
| `enabled` | 布尔值，默认 false。明确启用后允许启动对账及合成 sandbox 自检。 |
| `root` | 已准备的执行器绝对目录，与 Gate 数据/配置/工作区分离。 |
| `image` | 已预加载的精确受审 manifest digest；不是项目输入。 |
| `podman_bin` | 管理员二进制路径，默认 `/usr/bin/podman`。 |
| `proxy_hosts` | 最多 32 条精确受审代理 host/port 规则及可选明确 private CIDR，默认空。 |

以下仅展示配置结构，须把占位符换成受审 digest；示例不是可运行镜像引用。

```json
{
  "enabled": true,
  "root": "/var/lib/lingshu-gate-executor",
  "image": "registry.example.invalid/gate-executor@sha256:<reviewed-64-hex-digest>",
  "podman_bin": "/usr/bin/podman",
  "proxy_hosts": [
    {"host": "proxy.example.invalid", "port": 8080, "private_cidrs": []}
  ]
}
```

Network 设置响应现在返回观测到的 `executor.available`、稳定 code、精确缺失条件和有界支持矩阵。启动先检查账户、目录、引擎、镜像，再实际观测独立 user/mount/PID/network namespace、只读 root 和 runner/cgroup 挂载、无 capabilities、no-new-privileges、仅 loopback 网络、已生效 CPU/memory/pids 上限。自检保留一个独立后代，只有观测到整个 sandbox cgroup 为空才成功。发现 PATH 中的 Podman 或声明 capability 不会启用执行；失败不转宿主。Core 连引擎适配器都不创建或探测。

缺失 controller 分别列明：`delegated_cgroup_controller_cpu_required`、`delegated_cgroup_controller_memory_required`、`delegated_cgroup_controller_pids_required`。本地镜像缺失返回 `preloaded_exact_image_digest_required`；各项 sandbox 观测失败返回 `sandbox_selftest_<check>_required`。这些检查不会拉取镜像或转宿主执行。

## 获取与包支持

| 阶段 | 已实现支持 | 明确拒绝 |
|---|---|---|
| Git | HTTPS smart v0/v1、SHA-1 完整 commit、精确 branch/tag 广告、浅层固定 commit 获取、隔离 strict pack 解析、原始 object 校验导出 | SSH、helper、redirect、hook/filter、submodule/LFS、SHA-256 仓库、不支持协议 |
| 代理 | HTTP CONNECT、SOCKS5/SOCKS5H，使用已验证数字上游 IP 和原 host 的 TLS SNI/证书校验 | HTTPS 代理传输、未审 host/port、代理远程 DNS 选择、direct 回退 |
| 工具准备 | 固定官方 npm 9–11、pnpm 8–11、Yarn Classic 1.22 分发包；官方 SHA-512、可选声明 integrity、有界无链接解包、实际 CLI/Node 探测 | 缺失/未知 metadata、engines 不匹配、缓存变化、工具 lifecycle、Corepack/global install/Node bootstrap |
| 依赖安装 | registry-only npm lock v2/v3；pnpm 8/9 匹配锁和官方 v3 store；Yarn Classic 1.22 v1 锁和官方 offline mirror/cache；强固定 SRI、有界获取及离线冻结安装 | pnpm 10/11 package-ID store、Berry、workspace/link/patch/override/bundled、Git/file/alias/custom origin、弱/缺失 integrity 和项目 rc/hook |
| Python | 本适配器之外既有 upload/direct `requirements.txt` legacy 路径 | Git/profile Python sandbox 安装、Poetry/uv/bootstrap；本批没有 Python cache adapter |
| 构建 | 所选受审 npm/pnpm/Yarn 的 `run build`，在无秘密离线 sandbox 执行，含已有足够源码的 build-only 项目 | 任意命令、路径、镜像；联网回退；非计划 manager/Node 下载 |

既有 manager 矩阵描述源码与计划格式，不代表本适配器支持全部缓存安装。未支持安装命令在计划/排队时可见地阻断；其他未支持 npm 缓存形态在依赖获取前拒绝。不会把所选 manager 改为 npm。多锁文件继续遵循精确 `packageManager`、已保存 override 和 shrinkwrap 原生优先级。

工具缓存身份绑定官方分发包字节、版本和 SRI。各项目可选声明 hash 独立对照已验证 archive hash；无 pin、大小写等价 hash 和不同受支持算法不会把其他项目的 pin 绑定到共享缓存。错误请求 pin 在 CLI 探测前拒绝。

Gate 生成经 fingerprint 绑定的只读 `/tool/shims`，将所选 manager（含脚本内嵌套调用）固定到 `/usr/local/bin/node` 和已验证 CLI。镜像中的其他 manager/Corepack 明确拒绝。`npx`/`pnpx` 只执行 contained 的已有项目 binary，不下载、不自动安装包。管理员专用 `test_native_executor_host_acceptance.py` 在 `LINGSHU_GATE_TEST_EXECUTOR_ROOT`、`LINGSHU_GATE_TEST_EXECUTOR_IMAGE` 指向已准备且受审 sandbox 时，实际验证嵌套 npm 及已有/缺失 npx；测试不准备宿主，云端默认跳过。

Git/install 网络选择仍在原 digest 计划中独立固定为 `inherit`/`direct`/`profile`。目标 DNS 的每个地址必须符合 host/port/private CIDR，公有/禁止地址混合回答整体拒绝。连接使用数字地址、原 host TLS SNI；HTTP CONNECT/SOCKS 也只接收该数字上游，不让代理重选 DNS。代理端点须另行匹配管理员受审 host 规则。Git 凭据值为 `username:token` 时用 origin-bound HTTP Basic（适合要求 Basic 的 smart Git host），仅 token 时用 Bearer；registry 凭据用 origin-bound Bearer；HTTP/SOCKS 代理认证引用使用 `username:password`。代理认证不进入上游 TLS 请求，镜像 registry 凭据不发给官方 metadata。

snapshot/artifact 扫描包含各 Basic token/代理 password 分量、其 URL/base64 编码及完整认证材料；公开 username 本身不列为秘密。短秘密分量仍扫描，过滤过宽时返回同样的有界拒绝，不静默省略。这也拒绝已授权端点把裸 token 反射进 Git 内容的情况。

HTTPS 禁 redirects、编码响应、环境代理和自动重试，限制 headers/body/deadline。DNS 只允许一个有界在途 resolver 槽。超时但未实际退出的 resolver 为未知结果，阻断网络 readiness，不能冒充已取消。可信 socket 关闭后才确认其取消；项目执行只接收已校验、无秘密内容。

同一 socket supervisor 贯穿 TCP connect、代理协商、显式 TLS handshake、发送和响应，始终使用原 deadline 并重算剩余预算。握手后取消会在构造/发送 origin 认证前重查。连接中和握手中 socket 在阻塞操作前注册，确保全程取消均能关闭它们。

可信获取不执行项目或依赖代码。Git 在无网络 sandbox 只解析 pack，原始 object 导出绕过 checkout、attributes、filters。官方工具解包不执行 lifecycle；npm 缓存准备只使用 SRI 已验证的官方 cache library 和 blobs。Yarn 接收只读、已校验的 registry mirror（存在旧 SHA-1 fragment 时额外核验），固定 CLI 使用仅携带依赖请求的 seed manifest 执行 `--offline --frozen-lockfile --ignore-scripts`。pnpm 8/9 由官方 CLI 将已验证本地 tarball 写入 SHA-512 寻址的 v3 store，再禁用 hook/script 验证 seed 的离线冻结安装。导出缓存前删除 seed 项目和 node_modules。原锁字节保持不变，项目安装后再次核对。项目容器把只读 source/tool/cache 复制到有界工作目录，没有 proxy/auth 环境、外部网络、SSH agent 或 Gate socket/home。项目及依赖 lifecycle 都在用户确认的 install/build 范围中运行。

pnpm 10/11 的工具准备和 build-only 仍可用，但依赖安装在获取前返回 `pnpm_cache_format_unsupported`。其索引还绑定 package ID，本地 file seeding 不能直接证明同一 registry index；下一步需要按版本、完整性和 registry ID 绑定的受审缓存写入器，再验证真实离线冻结闭包，不能伪造 store JSON 或替换 npm。v3 路径要求 SHA-512、匹配的单项目锁且无 patch/override。Yarn 要求有界 Classic v1 registry 记录及单一强 SRI；两条路径都拒绝 alias、自定义 registry 路径前缀和不完整/未支持闭包。缓存语义对照了 [Yarn Classic 精确版本 tarball 实现](https://github.com/yarnpkg/yarn/blob/v1.22.22/src/fetchers/tarball-fetcher.js)和 [pnpm 9.15.4 精确 v3 index 路径](https://github.com/pnpm/pnpm/blob/v9.15.4/store/cafs/src/getFilePathInCafs.ts)。

## 日志、输出与恢复

`jobs.sqlite3` 使用 FULL-synchronous 事务和排他单所有者 lease。阶段绑定持久 actor、import/build ID、operation/source/plan/network/lock digest、deadline、固定镜像；获取或创建容器前先落账。controller job 记录确定名称、实际 container ID、观测 cgroup 和冻结输出 inventory digest。请求不能选引擎参数、镜像、宿主路径或任意命令。重复阶段 key 不重新执行，绑定不同则幂等冲突。

取消/超时须终止整个 sandbox 并验证 cgroup 为空后冻结输出。状态丢失、无法观测 cgroup 或终止不明写为 `unknown`、阻断 readiness 并保留对账。重启先对账 journal/container ID 才派新任务。旧 coordinator import/build 成为 `interrupted`：`terminal=true` 停止轮询，`execution_state=unknown`、`execution_terminated=false`、`requires_reconciliation=true` 保留不确定性。中断 build 不能取消成功或删除；import/build/deploy/start 都不自动恢复。

只有冻结、有界输出进入既有 source/artifact 路径。inventory 绑定路径、类型、mode、字节数、文件 hash、链接目标；冻结的项目/object 根目录本身也不能是链接。导出只保留 contained relative package links，拒绝 external/cyclic/special 和已知秘密值，复用 500 MiB、30,000 条、30 秒制品上限。失败不发布部分新制品、不替换已有部署。管理员对账须检查原 coordinator operation 和私有 job 记录，不能删除 journal 或换新 key 当重试捷径。

固定 PID 1 runner 在放行项目代码前关闭 Linux dumpability，阻止同 UID 子进程通过 ptrace 或 `/proc` 文件描述符修改它。所有内容阶段（包括依赖归档及缓存准备）等待 cgroup 观测持久落账并再次检查取消后才执行，再以引擎观测到的容器退出码结束。项目自行创建 `result.json` 不能证明成功或提前结束仍在运行的阶段；共享结果字段也不提供脚本阶段的可信 manager/Node 版本。

冻结后的结果、inventory、Git object、artifact 使用 nonblocking/no-follow 文件描述符打开，并经 `fstat` 确认普通文件。结果 JSON 读取上限为 8 KiB/一秒；FIFO、设备、目录、inode 交换及超限输出在解析前拒绝。拒绝结果记录为已确认失败的阶段，释放 controller admission。

journal 独立持久记录 `cleanup_state=pending/cleaned`。已确认取消、超时及其他失败阶段在释放 admission 前删除工作区，成功输出在消费后删除。启动同时对账未终止执行和终态残留目录，避免终止后崩溃积累 tmpfs 占用。未知执行保留输出并阻断 readiness；清理失败仍为 pending，并阻断 readiness，直到成功对账。

既有明确确认的本地 deploy/start/rollback 保持。准备工具不会安装到宿主 runtime；manager 启动仍要求独立管理员 runtime registry，直接 Node 入口保留原规则。构建隔离不改变既有 Native managed-process 的非隔离运行时，也不增加 Core 交付/启动。

## 证据与剩余验收

合成测试使用假 socket/engine，验证真实 HTTPS framing/策略、原始 object、官方解包/cache、npm/pnpm 8–9/Yarn Classic 的 GitImport/BuildDeploy 链、幂等、秘密/链接/锁改写拒绝、整组取消/超时/未知/重启及 Core guard。未连接用户仓库、代理、凭据，未运行项目脚本。实际 Podman namespaces/controllers、Git HTTP 协商、npm/pnpm/Yarn 离线 cache/install、官方工具探测和恶意 lifecycle 隔离仍是未测宿主验收项。Native-only、Core-gateway 阶段不代表 Docker 用户完整交付/构建/部署/启动链完成。实际数量见分支提交/检查报告；合成通过不是宿主验收。

Podman 参数与 rootless 语义对照了[官方 run 文档](https://docs.podman.io/en/latest/markdown/podman-run.1.html)。控制器委派与整组终止仍须实际自检及管理员验收。
