# Git 执行器实现与落地决策

[English](../git-executor-decision.md) · [Git/网络合同](git-import-network.md) · [Native 宿主准备](native-executor.md)

已决定采用 **Native/Linux 先行**。本开发分支实现可信 HTTPS 获取和真实本机 rootless Podman 适配器，复用计划、确认/digest/idempotency、GitImport/ProjectUpload、BuildDeploy 链。适配器可选且默认关闭，须管理员准备及审查前提；真实宿主验收未测。源码版本保持 0.4.4，本轮不发布、打 tag 或 merge。

Core 继续是非特权 gateway 和权威单 SQLite coordinator：不创建适配器、不接引擎/socket、不执行本地项目、不准备宿主工具、不远程部署 runtime、不桥接 stdio。Core readiness 明确返回 `core_gateway_only_native_delivery_disabled`。Native 构建成功不增加 Core deploy/start 支持。

## 已实现代码

| 范围 | 实现 |
|---|---|
| `native_executor_config.py`、`adapters/safe_network_factory.py` | 管理员固定 digest/root/binary/proxy 策略，Linux/local 工厂在导入引擎前守卫。 |
| `main.py`、`network_settings.py` | 同一个适配器接入 GitImport/BuildDeploy，真实 readiness、启动对账/自检、关闭接单。 |
| `adapters/native_executor/controller.py`、`journal.py` | 固定 Podman argv、已预载 digest 镜像、实际 namespace/controller、有界 tmpfs、持久阶段/资源账、整 cgroup 终止与未知阻断。 |
| `adapters/native_executor/https.py`、`git.py`、`git_acquisition.py` | 有界 TLS、数字 DNS/代理目标连接、固定 smart HTTPS fetch、离线 strict pack 解析、hash-bound 原始 object 导出，不 checkout。 |
| `adapters/native_executor/packages.py`、`runner.py` | 官方固定 npm/pnpm/Yarn 完整性/engines；npm/pnpm 8–9/Yarn Classic registry cache、无秘密离线冻结 install/build。 |
| `build_deploy.py`、`git_import_mcp.py` | 保持既有 coordinator/artifact，绑定持久 actor/source/plan/network，interrupted 不盲重跑、不删除未知资源。 |

保留原五方法协议及 capability 名称，生产组合额外要求真实 readiness；Native 仅声明 capability 不够。factory/settings/lifecycle 已非 stub。只复用历史原始 object/scanner/offline integrity 校验器，未带入无关 Stage 1 修改。

## 有界支持范围

Git 支持 HTTPS smart v0/v1 和 SHA-1 固定 commit，禁 hooks/helpers/checkout/submodule/LFS/redirect。HTTP CONNECT/SOCKS 代理接收已验证数字上游 IP，保持原 host TLS。HTTPS 代理传输明确拒绝；代理 host 策略与 Git 策略分开，Git/install revision 独立固定。

固定官方 npm/pnpm/Yarn 可在不使用 Corepack/global install 的情况下准备。受审依赖闭环覆盖 registry-only npm lock v2/v3、pnpm 8/9 v3 store、Yarn Classic 1.22 mirror，强固定 integrity、有界内容及官方离线冻结闭包验证。pnpm 10/11 package-ID store、Berry、Python sandbox cache、workspace/link/bundled/custom/Git/file、项目 rc/hook 明确拒绝；Python 仅保留本适配器之外的 legacy upload/direct 路径，没有 manager/version/network fallback。所选受审 Node manager 可离线执行确认 build script。

项目代码只有只读校验 source/tool/cache 和有界可写工作目录，无 network/secret/engine mount。整组终止后才冻结输出，再通过既有有界制品边界。持久 journal 将阶段绑定唯一 sandbox；重启/取消/超时保留未知结果、不自动重放。deploy/start/overwrite/rollback 的独立确认仍保留。

## 仍须管理员验收

代码已实现，宿主准备与真实验收分开。受审预载镜像、专用非 root Native 账户、实际 cgroup v2 CPU/memory/pids 委派、owned bounded tmpfs 为前提。缺 namespace/controller/image/quota/journal 所有权时返回可行动 readiness 原因，不执行宿主 fallback。

云端证据为合成。准备后宿主仍须验证真实 HTTPS Git/credential/proxy 来源保真、官方 manager 及 npm/pnpm/Yarn cache、恶意 lifecycle、全部后代终止、重启对账、制品和既有 deploy/rollback。未使用生产凭据、SSH，未变更 nx 服务、信任或宿主网络。见[可部署 Native 合同](native-executor.md)。

未来 Core remote worker 须另立鉴权 phase/artifact/runtime、远程 deploy/stdio 合同；不在本实现内，也不因 Native 支持而自动授权。
