# 0.4.5 候选验证与发行门禁

[English](../release-validation-0.4.5.md) · [发行指南](releases.md) · [发行摘要](../../packaging/release-notes.md) · [准确证据](../benchmarks/gate-release-0.4.5-2ef739b.json) · [PR #55](https://github.com/zhigege666/Lingshu-Gate/pull/55)

产品候选冻结在 `2ef739b5a9f72e8a7a01c7044f20b5d766de415c`，准确 main 基线为 `8941738096ab69c0b9fa014f39ff9749cca64822`。独立 `test/gate-release-0.4.5-evidence-20261007` 分支仅修改本双语报告与历史/当前 JSON 证据，不改变 PR #55 head，也不取消其 CI。本地前端/后端/浏览器全集保留实际 7c7e39f 溯源。本 head 仅加入 CI 安装修复，产品/runtime/UI/包输入与 7c7 字节相同；新构建包、打包回归、安装 wheel/native 探针及当前 CI 均绑定 2ef739b。不以更早的包或后续证据提交冒充此构建 SHA。CI 的 PR merge checkout 为 `d49696e29d92f1627160ab18b77b560175826d85`；已 fetch 后比较，产品 head 与该 checkout 的完整 tree 相同。

## 范围与打包修复

本候选将唯一版本源递增至 0.4.5，最小适配遗漏提交 `4c61cb4fa9301805386122e27a2e88098c0770fc` 的账户菜单行为及 `8ff92ef5694f47faed30b3a38c288c72ccbf3551` 的分类变化说明。受控菜单在 Escape、外部点击、选择与导航时关闭；Escape/选择恢复触发按钮焦点。内置角色按中英文翻译，去除空项及重复项，自定义名称保持纯文本，全空列表回退主角色。分类说明展示已知变化字段、过滤未知字段，并解释未记录历史定义的情况，不把缺少证据当成已证 schema 差异；审核与发布仍为独立动作。

后端策略、权限、依赖、当前 tokens/页头操作/搜索尺寸及 CSS 不变。保留 Vite 8/Rolldown、两入口 `mangle: false` 与 Console `base: "/"`。发行指南已对齐真实固定的 PyInstaller 6.22.3。两次准确 APT 镜像/索引超时后，本 head 将完整官方浏览器依赖安装移至昂贵后端之前，使用本次拥有的签名校验 Ubuntu primary/updates/security 源、有界网络等待/重试及普通 runner 用户下载浏览器；产品 smoke 断言和 180 秒命令保持。

已整合的 [wheel 修复](wheel-build-validation.md) 解决 setuptools 向 `build/lib` 增量复制、再把完整树安装入 wheel 的残留。Vite 只清源码静态目录，native 清理不清此缓存，原候选因此多出 143 个旧文件。正式 setuptools PEP 517 hook 使用本次拥有的干净复制/安装/归档 staging，每层比对完整 Console/OAuth 清单，校验归档路径及每项 RECORD 摘要/尺寸，然后原子替换已验证输出。既有 build/native/自定义/用户数据树保留，仅清理本次创建的 staging/输出临时文件。sdist 携带 hook 与已构建静态资源。本版本 PR 未再修改 hook，已在新源码实际重跑回归。

## 已执行本地检查

| 检查 | 准确结果及溯源 |
|---|---|
| 冻结依赖同步/导出、版本、Ruff、mypy、源码/历史身份、Compose config、空白 | 通过；Python 3.13.15、uv 0.11.33、Node 22.23.2/npm 10.9.8；mypy 158 文件；requirements 导出字节完全相同 |
| 前端检查、单测、两份 Vite 构建 | 本地产品 7c7：75 文件/455 项通过；Console 115 + OAuth 3 个静态文件 |
| 后端全集 | 本地产品 7c7：2311 通过、7 跳过、134 subtests 通过；5 个既有 JUnit property 警告 |
| 必需浏览器 smoke | 本地产品 7c7：29 通过，零失败/跳过/flaky；包含 10 个根入口及双语菜单/角色/分类用例；16 个账户菜单视口/主题/语言组合 |
| 根入口真实 HTTP | 7c7 源码 fixture 及 2ef 新隔离安装 wheel 各验证 261 请求，含 114 对当前/旧 Console 文件、HTML/JSON 协商、跳转、API 鉴权、OAuth 关闭及路径边界 |
| 打包回归 | 156 通过；两个静态根实际两轮 PEP 517 fixture wheel A→B，保留旧 lib/bdist；缺失/额外/变动文件、路径/符号链接/FIFO/用户数据边界、最终 zip/RECORD 损坏、sdist/editable 与 native 合同 |
| 当前仓库 PEP 517 直接 wheel 与 sdist→wheel | 离线通过，两个 wheel 字节相同；完整静态清单及每项 RECORD 校验通过；setuptools.build_meta 84.0.0 |
| 新 Linux x86_64 native | 正式构建器、归档身份、标准解包及 readiness 通过；PyInstaller 6.22.3；解包静态文件与当前 Vite 输出相同 |
| 安装 wheel 与 frozen native schema worker | 每包 9 项：有效/本地 ref、无效/不支持/远程 ref 拒绝、真实父 dispatcher、deadline/cancel 终止及槽位复用；子进程全部回收；worker 入口不创建服务 runtime |
| 回收 | 所有本次 HTTP 进程回收、监听关闭、runtime 临时目录移除；7c7 后端结束审计没有残留本次 runtime 目录或 pytest 进程；私有 wheel staging 移除 |

后端 7 跳过为未提供固定安装的 3 个外部 Playwright MCP peer opt-in，以及要求 operator 准备 rootless Podman/镜像/tmpfs 的 4 个真实宿主用例，均不计通过。历史固定 peer follow-up 保留自己的 SHA。Vite chunk/config-loader 与后端 JUnit 警告保留在原日志。

JSON 保存当前 118 个文件的完整静态清单，其规范 SHA-256 为 `95bf75f824b5d0770931666340a1b4a3156fc660eba46e81154176d566b60902`。新 Vite 输出、直接/sdist wheel、已安装 wheel 与 Linux native 解包的文件集合和字节完全一致。

## 私有包摘要

| 制品 | 字节 | SHA-256 |
|---|---:|---|
| `lingshu_gate-0.4.5-py3-none-any.whl`（直接及 sdist 派生） | 1923055 | `099aea2df45506c0975ea620e528fbe17d43193aeb08df3547b583952fe5353c` |
| `lingshu_gate-0.4.5.tar.gz` | 2136451 | `8d74105e35f1af813917adbbf622a3b5c980926ddc2687488ee0a9e6d7f8243a` |
| `lingshu-gate-v0.4.5-linux-x86_64.tar.gz` | 36315093 | `af98eb535cbd9e279c66a1a6722e443fd956aabca228fa78f2068e60e1c088d0` |

这些仅为保存 cloud 环境中的私有候选，未上传正式发行资产。JSON 记录原日志摘要、准确命令、构建工具、包清单及回收；不含敏感 fixture 数据或 runner 绝对路径。

## 准确 CI 检查点

在 `2026-10-07 20:37:50 UTC` 观察，分支 head 为 `2ef739b5a9f72e8a7a01c7044f20b5d766de415c`，实际 checkout 为 `d49696e29d92f1627160ab18b77b560175826d85`。未复用取消或旧 head 结果。

| 工作流 | 状态/结论 |
|---|---|
| [Continuous integration](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487) | completed / success |
| [Release artifacts](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322) | completed / success |
| [Container images](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428302) | completed / success |
| [Code scanning](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428324) | completed / success |

| 当前准确源码/兼容任务 | 实际状态与日志结果 |
|---|---|
| [Source checks](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112981013531) | completed / success; Python 3.12.14 pytest 2311 通过 / 7 跳过 / 134 subtests; 前端 455; 浏览器 29 |
| [Python 3.11](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112993170545) | completed / success; Python 3.11.17 pytest 2311 通过 / 7 跳过 / 134 subtests |
| [Python 3.13](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112993170553) | completed / success; Python 3.13.16 pytest 2311 通过 / 7 跳过 / 134 subtests |
| [CI result](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/113004203758) | completed / success |

| 平台/部署包任务 | 状态/结论 |
|---|---|
| [Docker Compose bundle](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690636) | completed / success |
| [Native macos-arm64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690722) | completed / success |
| [Native linux-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690742) | completed / success |
| [Native macos-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690752) | completed / success |
| [Native linux-aarch64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690753) | completed / success |
| [Native windows-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690786) | completed / success |

五种 native 均在自身平台验证包身份、校验解包及 readiness，Linux 另执行 glibc 基线门禁。PR release quality 实际运行 194 个发行工程测试；容器契约实际执行 Core 构建/检查/readiness/critical 漏洞检查及 QEMU 原生/仿真执行，不是仅检查文档。

Compose 仅执行本地、生产及打包 Compose 文件的模型/config 检查。Core readiness 通过 GitHub runner 上安全镜像的 `docker run` 验证；这些结果不表示 nx5 部署、真实 rootless Podman 准备/readiness 或真实 OAuth 客户端验收通过。

历史 7c7 源码 CI 第 1、2 次均通过前端 455 项及 Python 3.12 后端 2311/7/134，随后在 Ubuntu APT 镜像/索引阶段 exit 124，未到 Chromium 下载。浏览器断言及 Python 3.11/3.13 均未运行，两个失败及原日志摘要保留；未原样重跑第三次。必要的 2ef739b 修复只改 `.github/workflows/backend.yml`，本地 35 个既有 CI 契约测试及 YAML/Shell 顺序检查通过。真实新 CI runner 已在后端前通过完整官方依赖/字体安装及 Chromium 下载；当前准确 head 源码工作流为 **completed / success**。此 head 的浏览器 smoke、两项完整 Python 兼容任务及 CI result 门禁均已终结成功；准确版本/数量与日志证明保存于 JSON。

已下载 Windows、两个 macOS 与 Compose 制品，核对 GitHub ZIP 原始摘要、内层 SHA256SUMS、完整 BUILD-INFO 清单及 SPDX SBOM。两个 macOS 的 118 静态字节均与 Linux 相同；Windows 同为 118 路径且全部 JS/CSS 字节一致，但两个 HTML/两个 SVG 的 CR/CRLF 文本换行不同。其自身声明摘要有效，去除 CR 后与 Linux 文本相同；不声称这四项跨平台字节相同。两个 Linux CI ZIP 超过本地下载工具 32 MiB 上限，未在本环境独立下载；其 CI 校验/解包/readiness 日志及 artifact 元数据，与本地新建并完整检查的 Linux 包分别记录。

JSON 逐项记录条件跳过：PR 中 tag-only Core 镜像候选/离线镜像/发布任务、仅 main push 的多架构 Core 镜像任务、平台限定 Delivery Skill/OpenSSL/glibc 步骤，以及 PR quality 中由源码 CI 负责的分支。跳过正式任务不代表已发布。

## 阻断与独立范围

任何当前必需源码、浏览器、包/静态/RECORD、worker/回收或 CI 失败均阻断验收。main 合并/tag/release 由发行负责人控制；版本变化推入 main 会自动创建 tag 并派发发行。正式验收仍要求全部必需任务、11 项准确资产、总/内层校验和、SBOM、准确源码/工作流来源证明及发行标题/正文回读。PR artifact 仅为候选。

下述已授权隔离宿主检查增加了真实临时源码/wheel HTTP 及 MCP fixture，并保留原 active 服务。未执行原服务切换、真实 Podman 准备/readiness、真实 ChatGPT OAuth 客户端或多机器联调，Native 执行与 OAuth 默认状态不变。父任务报告 PR49 更广浏览器仍属历史失败：默认 475 项中 418 通过/55 跳过/2 失败；optional 27 通过/3 跳过/7 失败。归因未证，不声称全站或 optional 全绿。早期 launcher 路径/locator/checkout mode 准备失败及修正均保留准确源码 SHA；追加 wheel 探针也保留初次缺离线索引元数据及 development driver 缺 `httpx` 的准备失败，修正前均未运行对应产品断言。

## 已授权隔离宿主检查，2026-10-08

[宿主证据](../benchmarks/gate-release-0.4.5-host-isolation-2ef739b.json) 记录通过 HTTPS Git 新拉取准确 `2ef739b5a9f72e8a7a01c7044f20b5d766de415c` 与 tree `716da35e388aab6784d8b41d6ae4e79a4c17f948`，沿用已授权测试身份，新建私有目录、venv/cache 及空 fixture。未复用原服务目录、凭据或业务数据库。实际宿主工具为 Python 3.14.4、Node 22.22.1、npm 9.2.0、uv 0.11.33；生产/release 依赖冻结，pytest/HTTP driver 按 uv.lock 准确摘要安装。这是追加宿主 smoke，不扩大发布的 Python 兼容矩阵。

| 已执行检查 | 准确结果 |
|---|---|
| 两份 Vite 构建 | 04:26:24 UTC 通过；Console 115 + OAuth 3；静态规范 SHA 仍为 `95bf75f824b5d0770931666340a1b4a3156fc660eba46e81154176d566b60902` |
| 打包及 schema 回归 | 143 + 13 通过，零失败/error/skip；含真实两轮 A→B wheel、两个静态根、缺失/额外/路径/RECORD 边界及 native 打包合同 |
| 合成 D01/D02 | 2 通过；真实本地 stdio 交付/reapply、失败构建保留及制品替换/回滚均限于可删除 fixture |
| 直接 wheel 与 sdist→wheel | 通过；宿主两个 wheel 字节相同，完整静态清单及每项 RECORD 验证通过 |
| 源码及已安装 wheel HTTP | 各通过 261 请求/114 对当前与旧 Console 文件，health 0.4.5；根协商、跳转、未授权 API/MCP、OAuth 关闭及路径穿越拒绝通过 |
| 已安装 wheel schema worker | 9 项通过；deadline/cancel 终止并回收本次子进程，槽位复用通过；worker 入口未创建服务 runtime |
| 已安装 wheel TCP MCP | 36 次真实 loopback RPC、6 个按需入口；initialize/discover/list → search/describe/invoke → 分块上传/plan/build/deploy/start/refresh/status → 真实下游 stdio 调用；过期 schema 与错误参数拒绝通过 |
| 清理及原服务 | 临时服务/peer 全部回收、监听关闭；04:46:43 UTC 按固定且受保护的清单清理生成目录，保留 tracked 源码/Git 与证据。04:48:30 UTC 原服务仍 active/running、health 200/版本 0.4.4，PID、unit/启动摘要及保护目录身份/属主/权限均相同 |

新增合成工具正确保持 `needs_review=1`、`effective_permissions_expanded=false`，未发布分类或新增授权。已明确授权的管理员 fixture 调用验证 runtime dispatch，不代表用户发布或 OAuth 验收。**Deployment and process startup succeeded; delivery acceptance remains incomplete.** 随后已删除该临时 fixture。

| 新宿主制品 | 字节 | SHA-256 |
|---|---:|---|
| 直接及 sdist 派生 wheel | 1923055 | `a9234933cce5cbb1f8553fbf9c0a2540ff5641700aac19fde3fd6ffa0ea672c8` |
| sdist | 2137280 | `2c4e0a72b2ddc99701727a845547e6259e36dc071acb470f16ac77798ad406c8` |

wheel 的全部 283 个成员内容（含 RECORD）与此前 cloud wheel 相同。归档摘要差异仅来自 281 个 ZIP external-attribute 字段继承的 checkout 文件模式（样本为 0600 与 0644）。仅在内存归一化这些属性即可得到 cloud wheel 的准确 `099aea2d…5353c` 摘要；实际宿主候选未修改。仅比较元数据，未转传原 handoff 包。

保留准备历史：最初 uv pip 传输达到 600 秒 deadline；从同一官方文件有界续传并验证 PyPI SHA 后本地安装。未使用的全开发工具下载主动停止，随后完成聚焦的冻结准备。首次 installed-runtime requirements 解析达到 180 秒 deadline，未到产品运行；改在同一拥有的 venv 按冻结 uv.lock 安装后成功，并核对适用的 committed requirements 版本。额外 help 诊断尝试读取非本次配置路径并被权限拒绝；已停止该诊断，未改变权限或配置例外。未重试 Library 403。未执行宿主 native 重建、Podman 准备、宿主产品全集、真实 OAuth 客户端、多机器联调、main 合并、tag 或正式发布；此前 cloud/CI 保留各自溯源。

## 升级边界

根入口“无新增迁移”比较只针对已整合 be30 至 6663203。正式 v0.4.4 升级至本组合版本还包含工具目录/分组迁移；保留配置、数据、凭据及签名密钥，做好一致备份，并保留 SQLite 单 writer 及旧包。历史基准、截图、不可变 tag 保留原溯源；第三方 `typing-inspection==0.4.4` 不是 Gate 版本。
