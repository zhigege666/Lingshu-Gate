# Gate 功能集成候选

[English](../gate-feature-integration.md) · [OAuth 分页](oauth-catalog-scaling.md) · [Native 执行器](native-executor.md)

`test/gate-feature-integration-20261005` 将已复审开发输入合入精确 main `d4786fd368e932bc758ea29da1a597c9d9551794`，版本保持 0.4.4。这是未发布 test 候选；main、tag、部署及宿主准备不在本次集成中。

| 输入 | 精确来源 | 集成处理 |
|---|---|---|
| OAuth UI、已存 grant 验证、候选分页、公共 catalog/group | `d8d4833bfdefbf7e679190565294f38f7a109145` | 普通三方合并的第一父提交，已包含复制的公共 `f51d1b18d7475034b61567be00ef999128918e83`／产品 `d99be556ff48e018792268abeb7c5a22c5517476` 改动 |
| Native 隔离获取／离线执行及安全修复 | `76bfe2c4eeae7f1a693e1d86b03c78e6098866d1` | 第二父提交，十九个 Native 提交全部保留真实祖先关系 |
| 公共 catalog 最终完整回归／包验证证据 | `6f3e87145a8ff581d8738ffbc3ee6f374ab56010` | 仅复制文档／数据，不重复产品 patch |
| OAuth 范围保存响应丢失恢复 | `9af3ddb5f5d7699f3c2bfe408c4f09cf04861020` | 无冲突复制为 `a3b57f708ae3d848382e46ee9c9b85ccae8e5722`；十二个变更 blob 与来源完全一致 |

合并为 `31f5195`，纯文档证据复制为 `a089dc2`。未用伪祖先合并或单方源码覆盖。两输入分别修改 151、54 个路径，九个路径重叠。仅中英文 CHANGELOG 未发布标题存在文本冲突，双方条目保留到同一未发布区；README、安全指南、文档索引和 `main.py` 自动合并。

## 组合与安全复核

同一应用组合共享 catalog、显式 group router、OAuth 候选索引与 Native factory。GitImport 和 BuildDeploy 共用已配置隔离执行器及固定网络选择；group 定义保留独立存储和既有配置服务边界。即使提供启用的 Native 配置，Core 角色也不构造、启动 Native engine 边界。

Catalog/group 迁移保留 OAuth 输入的 0012–0016 顺序。Native 不增加冲突的 Gate migration，私有 job journal 使用独立 single-owner SQLite 文件。配置／runtime 锁、不可变 registry snapshot、选定实例 guard、当前权限检查、管理资源 allowlist 与直接 MCP 接口均保留已复审输入逻辑。

组合 lifespan 测试发现并修正一处相互作用：Native close 未知不能跳过独立 external-configuration/runtime 关闭。这些清理在 `finally` 中执行，Native 异常和保留的 journal lease 不变；仅关闭成功才发出 `gate.shutdown_complete`，不把未知执行报告为已终止。新增组合测试覆盖成功、未知关闭、Core 排除及 catalog/group migrations 共存。

## 包管理器支持

| 阶段 | 支持 | 明确限制 |
|---|---|---|
| 官方固定工具准备 | npm 9–11、pnpm 8–11、Yarn Classic 1.22，校验 integrity／engine | 禁 latest、全局安装、Corepack、自动下载 Node 和项目指定 image |
| 冻结离线依赖安装 | npm registry lock v2/v3、pnpm 8/9 受审 v3 store、Yarn Classic 1.22 registry mirror/cache | pnpm 10/11 package-ID store、Yarn Berry、workspace/link/patch/Git/custom-origin/弱完整性缓存仍拒绝 |
| 离线构建 | 选定、已校验 npm/pnpm/Yarn `run build`，包括支持的 build-only 项目 | 禁任意命令／路径／image、网络／秘密继承或 manager 替代 |
| Python | Native 之外既有 upload/direct legacy 路径 | Git/profile Python sandbox 缓存不支持 |
| Docker Core | 既有 gateway/catalog/OAuth/group control plane | 无 engine/socket、项目执行、远端 worker/deploy 或 stdio 桥接 |

## 验证合同

最终结果须标明精确集成候选 SHA。输入已有 benchmark、截图及完整回归计数是其记录 SHA 的历史证据，不是当前组合树的验收。执行 frozen Python/npm 准备、Ruff、mypy、完整 backend、前端 type/UX、Vitest、两个前端 build、身份／版本、Compose 语法及空白检查。构建静态资源时，不并行运行读取这些资源的 backend/browser 用例。

Backend 回归包含 OAuth A/B、普通／management 资源、直接 MCP/HTTP 兼容、catalog/group 权限与派发锁、配置／runtime／migrations，以及 Native acquisition/journal/cleanup 全套。包验证需从构建 wheel 执行 schema 验证子进程，移除 checkout import path，确认 deadline/取消子进程被回收，并从同一 artifact 导入 Native 模块。实际 Linux frozen worker、本地假数据浏览器验证如执行，单独报告证据。

真实 rootless Podman namespace/controller、受审 image/cache、凭据／provider／client 和 nx5 部署仍由操作员／根代理验收。缺少已配置宿主前提时，四项 opt-in Native host 测试保持 skip，不降级 host shell。合成集成成功不表示 Docker 用户交付／构建／部署／启动链完成。

## 已记录的验证检查点

初始组合生产源码与完整测试检查点为 **`31b7cca9155d36094250a47bc7f688797b8217a7`**。证据导出 `75a033881d19d5225c0adbc3cf2f4916822c6fbe` 仅修改文档。随后 OAuth 恢复改动具有下述独立前端检查点；初始结果仍绑定其记录来源。版本仍为 0.4.4，不表示已生产部署。

| 检查点上的验证 | 结果 |
|---|---|
| 完整 backend | 2,126 passed、7 skipped、0 failed；954.48 秒 |
| 前端 | 74 个文件中的 439 项 Vitest 用例通过；冻结 npm 安装、type/UX 检查、Console/OAuth 构建通过 |
| 合成 Chromium 浏览器 | 196 项常规用例通过；最初跳过的 11 项规模用例随后启用 5,000 服务／50,000 工具夹具并全部通过 |
| 安装 wheel 与 Linux frozen worker | 14 个真实 schema 子进程全部回收，覆盖超时／取消与后续复用；2 项 native 入口探测和 6 项已安装 wheel 的 Native 模块导入通过；排除 checkout |
| 静态／仓库检查 | Ruff、mypy（158 个源码文件）、仓库身份、版本、Compose 配置与空白检查通过 |

仓库内证据：[完整验证记录](../benchmarks/gate-feature-integration-validation-31b7cca.json)、[合并／源码 blob 溯源](../benchmarks/gate-feature-integration-provenance-31b7cca.json)、[wheel／frozen worker 观测与产物校验和](../benchmarks/gate-feature-integration-package-workers-31b7cca.json)、[完整 backend 输出](../benchmarks/gate-feature-integration-backend-31b7cca.log)。

导出保留观测结果与原始 runner 记录的哈希。临时绝对路径替换为具名相对路径，用于说明导入与命令，不是下载链接；本次文档导出不发布二进制。数据全部为合成输入，不含真实凭据。七项 backend skip 为四项操作员准备的 Podman 用例与三项固定外部 Playwright MCP 安装用例，与已执行的 207 项 Console/OAuth 浏览器用例不同。根代理已独立复审检查点上的真实合并祖先、源码 blob、关闭修复及迁移／锁组合，无新增 P1/P2。真实宿主、凭据／provider／client、正式发行包与 nx5 验收仍待完成。

## OAuth 响应丢失集成检查点

后续组合生产源码与前端测试检查点为 **`a3b57f708ae3d848382e46ee9c9b85ccae8e5722`**，包含已独立复审的 `9af3ddb` 恢复修复。范围更新已提交但响应丢失时，Console 保留草稿、标记结果未知并阻止核对／保存；明确刷新读取实际已保存 grant、当前目录并核验保留选择后才解锁，读取失败继续锁定。旧确认不能重放，后续编辑需按实际版本取得新确认，配额草稿保留。详见[响应丢失场景](oauth-catalog-scaling.md#保存已提交但响应丢失)。

该精确集成检查点上，冻结 npm 安装、前端 type/UX 检查、74 个文件中的 **439 项 Vitest 用例**及 Console/OAuth 两份构建均通过。启用 5,000 服务／50,000 工具夹具后，`oauth-grants`、`oauth-consent`、`oauth-paged-catalog` 三份浏览器 spec 的 **98 项用例全部通过**，耗时 **291.19 秒**，无 skip、失败、重试或 flaky；两个真实提交后丢失响应的用例均通过。

后端沿用 `31b7cca` 的 **2,126 passed / 7 skipped**，没有重新执行完整后端。`src/`、`tests/`、`scripts/`、Python 依赖定义／锁和 npm 依赖定义／锁的 Git tree 记录与该检查点完全一致。旧 wheel／frozen worker 观测仍绑定原源码 SHA 与产物哈希。该前端检查点未包含重新打包；后续新包验收见下。

仓库内可读[集成验证及全部 98 项逐例结果](../benchmarks/gate-feature-integration-validation-a3b57f7.json)与[输入 blob／后端继承证明](../benchmarks/gate-feature-integration-provenance-a3b57f7.json)。记录保留根代理对 `31b7cca` 组合及 `9af3ddb` 恢复的独立复审来源，两次均无新增 P1/P2。后续文档导出不改变产品或前端检查点。浏览器执行仍为合成验收；真实 Podman、provider／client、nx5 及完整平台发行矩阵验收单列。

## 最新 wheel 与 Linux native 包验收

最新 0.4.4 候选包从 **`ed34c5a474747b2f0933b8fbee7fccf193ee7315`** 构建，该树与已测产品 **`a3b57f708ae3d848382e46ee9c9b85ccae8e5722`** 仅有文档差异。标准 native builder 使用固定 **CPython 3.13.15、Node 22.23.2、PyInstaller 6.22.2**、冻结依赖及官方 Node archive 校验和，生成完整 Linux x86_64 archive、启动脚本、BUILD-INFO、SPDX SBOM 与第三方许可。未执行发行或部署。

| 新产物 | SHA-256 | 字节 |
|---|---|---:|
| `lingshu_gate-0.4.4-py3-none-any.whl` | `023f39a0bbf3830d8e1a41280face4feb429e117679e07effe07603a2412c8d4` | 1,785,586 |
| `lingshu-gate-v0.4.4-linux-x86_64.tar.gz` | `314f6ff0c9b6d072c629e126875c02a20a23493efeffbf90cc5e3321ddd179ec` | 33,843,127 |

wheel、隔离安装与严格解包 native 中的全部 **97 份 Console 和 3 份 OAuth 文件**，均与当前 dist 及 `a3b57f7` 浏览器已测构建逐字节一致。恢复 chunk `external-connections-page-5G7cff7c.js` 的 SHA-256 为 `f590c4b7289fd21e299bdfb32cec47c25aa18c5e6a35798f02197ceaf3605c90`；两个实际启动包都通过 HTTP 提供该精确内容，含未知保存及已保存版本读取代码。wheel 全部 RECORD 条目与 native 的 453 项 BUILD-INFO 文件记录均通过；archive 校验和、有界解包及 glibc 2.35 上限检查通过，包含并核对了 200 个 SPDX package 与 196 项第三方许可记录。

新安装 wheel 与新 native executable 通过 **14 项真实 schema 子进程用例**，覆盖超时／取消／回收及后续复用；**2 项 native worker 入口探测**、**6 项 Native 模块导入**及 **4 项 CLI 版本／帮助探测**均通过。两个真实包进程的 readiness／health／恢复 chunk HTTP 检查通过，均已停止并回收。OAuth 保持默认关闭并返回 HTTP 404；native readiness smoke 与最终 wheel／archive 身份检查也通过。隔离测试不启动 Podman engine 或项目 job，不使用真实凭据。

首次 wheel 核对拒绝了忽略目录 `build/lib` 中的 141 份旧 Console 与 2 份旧 OAuth 文件。只清理已核实的生成目录后重建、重装，最终多余／缺失文件为零。首次离线依赖解析缺少固定 `annotated-doc` metadata，随后按导出的精确版本和哈希验证完成安装。记录保留这些准备阶段失败与修复，未改变产品源码。

仓库内证据：[新包哈希、工具链与完整静态资源清单](../benchmarks/gate-feature-integration-packages-ed34c5a.json)、[新 wheel／native schema worker](../benchmarks/gate-feature-integration-package-workers-ed34c5a.json)、[实际包／CLI smoke](../benchmarks/gate-feature-integration-package-http-smoke-ed34c5a.json)。候选二进制及 SHA256SUMS 保留于 cloud 的忽略目录 `dist/candidates/ed34c5a`；本次证据导出不发布二进制。完整后端仍沿用 `31b7cca`。真实 Podman、外部 Playwright MCP、provider／client、nx5、其他平台及完整正式发行矩阵仍未验。
