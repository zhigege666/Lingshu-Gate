# 干净 wheel 暂存验证

[English](../wheel-build-validation.md) · [开发指南](local-development.md#发行检查)

这是独立测试分支上的未发布打包修复。精确 base：`98d945a37839e6cbd4619245dcee3e66c7ae7ffe`；恢复输入：
`3e774c9c6ed5444b67506af84a022520ac5cb687`；最终已测试构建检查点：
`a186c9ad5de44e98f39552c0bca09a8c0dabd97c`，分支为 `test/gate-clean-wheel-20261006`，版本仍为 `0.4.4`。
运行时与 UI 源码树保持产品检查点 `a3b57f708ae3d848382e46ee9c9b85ccae8e5722` 的字节。

## 根因与修复

setuptools 81 增量复制 package-data 到 `build/lib`，随后把整个目录复制进 wheel 安装暂存树。
Vite 只清理源静态目录，native/PyInstaller 清理不处理 `build/lib`，因此同工作树普通构建可再次带入旧 hash。
此前集成证据记录了 141 个旧 Console 文件和两个旧 OAuth 文件。

恢复输入已隔离包复制。独立复现还确认默认 `build/bdist.<platform>/wheel` 中的旧文件会继续进入最终 wheel。
完整修复保留 setuptools PEP 517 后端，为包复制、wheel 安装和归档生成分别使用私有暂存目录。
复制、安装和最终归档阶段均校验两个静态目录的完整清单及 SHA-256，并校验最终 zip 路径和每条 RECORD
的哈希、大小，通过后才原子替换输出。原子替换仅覆盖 wheel hook 的发布步骤，
不宣称 setuptools `build_meta` 最外层制品移动为全事务。只删除本次创建的私有暂存或输出临时文件，
保留已有缓存、原生制品、用户指定的构建路径和用户数据目标。editable 安装无需前端；非 editable wheel 拒绝 `--skip-build`。
sdist 携带构建钩子及已生成资源，可继续常规 wheel 链路。

## 实际执行证据

| 检查 | 结果 |
|---|---|
| wheel、发行、自动化和 CI 相关测试 | 200 通过，零失败/跳过 |
| ruff、mypy、仓库身份、版本、空白 | 通过；mypy 覆盖 158 个源码文件 |
| 基线 A→B 复现 | 如预期失败：第二轮两个目录同时包含 A/B |
| 修复后整仓 A→B 双构建 | 第二轮只有 B、无 A；旧 lib/bdist 缓存与测试用户文件完整保留 |
| 同一源码树两个并发整仓 wheel | 通过，B 成品哈希一致，私有暂存已清理 |
| 缺失/额外/变更文件、路径边界、失败重试 | 通过，含最终 zip/RECORD 故障与输出符号链接目标保留 |
| 最新 web、常规 PEP 517 sdist→wheel/直接 wheel | 通过，两种 wheel 的哈希和载荷一致 |
| dist/wheel/安装 wheel/提取 Linux native 静态文件 | 97 Console + 3 OAuth，清单及 SHA-256 完全一致，并匹配原 browser 验收清单 |
| wheel RECORD / Python 载荷 / native BUILD-INFO | 校验 265 / 158 / 457 条 |
| native 归档、标准提取/readiness 和 glibc | 通过，最高 glibc 需求 2.35 |
| schema IPC/超时/取消/复用及直接入口 | 14 个真实验证子进程 + 4 次直接探测，全部回收 |
| wheel/native CLI 及 loopback HTTP | 均通过，97 个 Console 文件 HTTP 字节完全一致，服务进程已回收 |
| `35a2dd5` 固定 Playwright MCP peer 补验 | 3 通过，零失败/跳过，仅 loopback 握手和工具列表 |

完整 backend 的 2126 通过、7 跳过沿用 `31b7cca`；frontend 的 439 单测和 98 browser 用例沿用
`a3b57f7`，本次未重跑这些完整套件。新构建的 100 个静态文件精确匹配既有产品清单。
打包测试和候选 smoke 为本次实际执行，loopback smoke 中 native executor 保持禁用。

## 固定 peer 补验

已在统一候选 `35a2dd508b173a62d0d8572e2fbd6592217f0c36`、
`test/gate-feature-integration-20261005` 分支实际执行原始 `tests/test_mcp_playwright_interop.py`
三个 opt-in，测试文件未修改：**1.07 秒内 3 通过，零失败/跳过**。
本次自建临时安装使用精确 `@playwright/mcp@0.0.83`、`playwright-core@1.64.0-alpha-1790635538000`
及 peer 声明的同版本 `playwright@1.64.0-alpha-1790635538000`。禁用安装脚本和浏览器下载，使用独立空浏览器
缓存，peer 带 `--isolated`，未提供已有用户 profile。

真实 peer 对现代 `2026-07-28` discovery 返回 HTTP 400、JSON-RPC null id 及 `-32000`
（`Bad Request: Server not initialized`）；显式现代模式未 initialize。
manifest 版本省略和 `auto` 两项均执行 `server/discover` → `initialize` → `notifications/initialized`
→ `tools/list` → `DELETE`，协商为 `2025-11-25`、列出 25 个工具，每个会话仅 initialize 一次。
没有 `tools/call`。一个 module-scoped peer 及观察到的后代全部回收，loopback 监听关闭；未观察到浏览器进程，
独立浏览器缓存保持为空。保存脱敏证据后已清理本次安装、pytest 数据、浏览器缓存和观察脚本，
未删除已有共享 Node/npm 缓存。

- [固定版本、真实响应、请求顺序与清理](../benchmarks/gate-playwright-mcp-interop-35a2dd5.json)
- [原始测试脱敏日志](../benchmarks/gate-playwright-mcp-interop-35a2dd5.log)

历史完整 backend 结果仍为 2126 通过/7 跳过，本次未重跑全套。单独补验只关闭三个 peer opt-in；
原有四项 Podman 主机用例仍未执行，未报通过。产品代码、测试、依赖、版本及上述私有包哈希保持不变。

## 私有候选哈希

| 制品 | SHA-256 |
|---|---|
| 直接与 sdist 派生 wheel | `696bde45fccca195560fbe200df53378f7dc2bd3e7886a59dfab01c6d78b5fb0` |
| sdist | `f6f54e022dddecb9c5243513307c2fc0ee06d173b6f83fd12ad3f23c3c8b4fc3` |
| Linux x86-64 native 归档 | `c416244eb5cae39a7400480583ede8246403227a49fa6c3c69b76bdd51738d93` |

候选仅保存在已保存 cloud 环境的忽略目录 `dist/candidates/gate-clean-wheel-20261006`。
这些哈希属于私有候选，不是正式发布资产。

- [验证及沿用/未跑检查](../benchmarks/gate-clean-wheel-validation-a186c9a.json)
- [连续/并发构建及基线/输入复现](../benchmarks/gate-clean-wheel-repeated-build-a186c9a.json)
- [完整静态清单与包哈希](../benchmarks/gate-clean-wheel-packages-a186c9a.json)
- [worker 入口及回收](../benchmarks/gate-clean-wheel-package-workers-a186c9a.json)
- [安装 wheel/native HTTP](../benchmarks/gate-clean-wheel-package-http-smoke-a186c9a.json)
- [相关测试日志](../benchmarks/gate-clean-wheel-validation-a186c9a.log)

## 剩余范围

真实 nx5/rootless Podman 验收等待 root 连接恢复与安全主机配置批准。真实凭据/provider/client、四项 Podman
主机用例、其他 OS/架构及正式发行矩阵均未执行；三项固定 Playwright MCP peer opt-in 已由上述补验完成。
基线 requirements 导出仍仅在 jsonschema 的 `via` 注释上存在文本差异，所有版本及哈希相同；未改锁文件或
导出文件，此注释差异在本次打包修复范围之外。未 merge main、tag、release、SSH、变更权限或发布正式 0.4.4 资产。
