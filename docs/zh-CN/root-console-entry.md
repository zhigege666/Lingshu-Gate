# 根路径 Console 入口候选

[English](../root-console-entry.md)

`test/gate-root-entry-20261007` 的独立实测源码为
`77d0815756ab4b03ccc66155dfc2ce6c758c8b5a`，基于
`227db541871ef8753390760d323414efbbe94d7c`。版本保持 0.4.4。本阶段保留 hash
导航，未进行 clean paths 迁移或发布。

| 入口 / 请求 | 行为 |
|---|---|
| 浏览器导航到 `/` | 既有 Console 登录页/界面 |
| `/` 未指定偏好或 `Accept: */*` | 既有服务 JSON |
| `/` 显式可接受 `application/json` | 即使同时列出 HTML，也优先得到 JSON |
| `/` 两种表示都不可接受 | 406；`q=0` 排除相应媒体范围，通配符不能覆盖 |
| `/v1/meta` | 不受 Accept 影响，提供相同服务 JSON |
| `/console`、`/console/`、`/console/index.html` | 不缓存的 307 跳到 `/`，保留 query 与浏览器片段 |

既有 JSON 字段保留，`console` 现指向 `/`，`meta` 标识 `/v1/meta`。HTML、JSON
及根入口错误均发送 `Vary: Accept`、`Pragma: no-cache` 和 `Cache-Control:
no-store, no-cache, must-revalidate, max-age=0`。HTML 的 ETag 不会使随后 JSON
请求复用缓存的 HTML。

新 bundle 使用 `/assets/` 及三个现有图标的明确路由；当前文件仍可从旧
`/console/assets/` 与图标路径取得，字节一致。带 hash 的 bundle 一年 immutable
缓存，其他资源一小时缓存。两种命名空间仅服务包内 Console 树中的常规文件。
路径穿越、不安全语法、越界符号链接、循环链接、缺文件及目录均返回 404。
缺 HTML 返回 404，JSON 元信息仍可用。未增加 catch-all SPA 回退，API、MCP、
OAuth、发现、OpenAPI 与探针保留各自 handler；`/oauth/consent` 与
`/oauth/assets/` 继续独立。

保存的 cloud Linux 工作区中实际执行：

| 检查 | 结果 |
|---|---|
| 冻结 Python 依赖同步 | 通过 |
| 冻结前端安装、check 与单元 | 通过，74 文件 441 项 |
| 正式 Console 与公开 OAuth 构建 | 均通过，保留既有大 chunk 提示 |
| 根入口 / startup / probes / composition / OAuth / packaging / MCP / configuration / bootstrap | 420 passed、0 failed、0 skipped；174.68 s |
| 上述后端中的根入口专项 | 64 passed |
| 八份选定 Chromium spec | 112 passed、0 failed、0 skipped、0 flaky；单 worker、零 retries |
| 上述 browser 中的根入口专项 | 10 passed，该 spec 未 mock API 或资源响应 |
| Ruff、Mypy、标识、版本及 Compose 配置 | 通过，Mypy 检查 158 源码文件，版本保持 0.4.4 |

后端及 browser fixture 使用 CPython 3.13.15，浏览器工具为 Node 24.19.0、npm
11.9.0、系统 Chromium 151.0.7922.173。真实根入口双语检查验证重复 query key、
编码值、hash 目标、登录后位置、刷新及原生后退/前进均保留。Cookie path、
HttpOnly、SameSite 及 viewer 拒绝保持。其他 spec 包含 mock 展示状态，也包含
真实 loopback 登录、权限及绑定请求的一次性 CSRF。browser 临时根已删除，
监听已关闭。先前十项根入口诊断与 112 项重叠，不另行相加。

首轮 browser 在页面断言前出现 112 项启动错误，原因是临时路径超过 Chromium
Unix socket 长度限制。改用短名称的专属磁盘临时目录后通过，未修改产品或断言
绕过失败。首次标识扫描包含 ignored 工作区临时目录中的 pytest 归档及 npm
缓存；仅将本任务输出移到 checkout 外，保留日志，原完整标识检查随后通过。
版本检查直接文件调用无法导入 `scripts`，改用其 Python module 入口后通过。

清单包含 Console 97 文件、OAuth 三文件，规范化 SHA-256 为
`28e5f475bfd27138fe80f238aec5f7fa6df77ff614f2f5401419405573b40a8b`。
OAuth 三文件与此前 be30 清单完全相同。未重建或改标 wheel、sdist、native
二进制；本源码未跑完整后端、全站浏览器、其他 Python/平台、Podman、真实
ChatGPT OAuth 或正式发布矩阵。新源码 nx5 部署验收由主线程负责。本任务未
操作 SSH、生产、main 或 tag，未修改授权及 CSRF 逻辑。

PR #51 的 CI 修复由另一任务负责。主线程最新补充到达前，已将中间源码
`63cab1c5b9f2a8eb6503fcee9193055c55262a2d` 仅本地试合，无冲突，两个
`builtin-oauth` 指南也自动合并。随后主线程报告仍有三项 high CodeQL，要求等待
终稿。该试合未推送，已保留在本地旁支并撤出本候选，当前运行代码仍为已实测的
77d0815。本任务未修改 PR #51 head，不构成最终组合验收；仍需对齐最终修复
源码、复验相关差异，尤其成对 OAuth 文档，不声称已核对终稿合并冲突。

[结构化证据及完整清单](../benchmarks/gate-root-entry-77d0815.json) 记录源码 hash、
命令及范围。[规范化日志](../benchmarks/gate-root-entry-77d0815.log) 保留实际输出，
省略具体主机路径和 fixture 密码。
