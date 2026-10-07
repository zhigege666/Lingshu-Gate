# 根路径 Console 入口候选

[English](../root-console-entry.md)

`test/gate-root-entry-20261007` 的合并实测源码为
`689b4f9eb9e1836431376dd4f84a67f9fd3edacd`。它以普通 merge 合并根入口父提交
`84c4b8bcf364eef33d8e4fafafce22866c936a31` 与明确已审的 PR51 head
`71f2a25db196f126a4f7e7e0a0b9e8ac952d7181`；核对时远端 head 与指定 SHA 一致。
没有冲突，两份 OAuth 指南自动合并，保留私有 Console 代理边界及浏览器绑定说明。
根入口实现与 `77d0815` 逐字节一致，导入的修复文件与 `71f2a25` 逐字节一致。
版本保持 0.4.4，保留 hash 导航，未进行 clean paths 迁移或发布。

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

保存的 cloud Linux 工作区在合并源码上实际重跑：

| 检查 | 结果 |
|---|---|
| 冻结 Python 同步与 pip 导出 | CI 固定 uv 0.11.33 通过；导出与 `requirements.lock` 逐字节一致 |
| 冻结前端安装、check 与单元 | 通过，74 文件 441 项 |
| 正式 Console 与公开 OAuth 构建 | 均通过，保留既有大 chunk 提示 |
| 22 份选定后端模块 | 859 passed、0 failed、0 skipped；JUnit 耗时 328.189 s |
| 上述后端中的根入口专项 | 64 passed |
| 上述后端中的合成 native executor 回归 | 203 passed；未使用真实 Podman 宿主 |
| 八份选定 Chromium spec | 112 passed、0 failed、0 skipped、0 flaky；单 worker、零 retries |
| 上述 browser 中的根入口专项 | 10 passed，该 spec 未 mock API 或资源响应 |
| Ruff、Mypy、标识、版本及 Compose 配置 | 通过，Mypy 检查 158 源码文件，版本保持 0.4.4 |

后端选择覆盖根入口协商与旧 Console 兼容、startup/probes/composition、内置及
管理 OAuth、打包、MCP HTTP/协议/配置、认证 bootstrap、Git 获取、基准报告及六份
合成 native executor 模块，包括导入的 cookie 绑定、公开错误字段、token/密码哈希、
TLS/配置和对象流回收回归。这些是合并源码的结果，未累加此前检查点的通过数。

后端及 browser fixture 使用 CPython 3.13.15，浏览器工具为 Node 24.19.0、npm
11.9.0、系统 Chromium 151.0.7922.173。真实根入口双语检查验证重复 query key、
编码值、hash 目标、登录后位置、刷新及原生后退/前进均保留。Cookie path、
HttpOnly、SameSite 及 viewer 拒绝保持。其他 spec 包含 mock 展示/OAuth 状态，也
包含真实 loopback 登录、权限及绑定请求的一次性 CSRF。browser 临时根已回收，
监听已关闭。

首次固定 uv 工具初始化尝试用户 home 下默认工具目录，因只读在应用检查前退出。
将 `UV_TOOL_DIR` 与 `UV_TOOL_BIN_DIR` 指向专属验证目录后通过，HOME、仓库策略和
产品断言均未改。所有验证生成物均放在 checkout 外，本轮浏览器无需重试。

重建清单包含 Console 97 文件、OAuth 三文件，规范化 SHA-256 为
`28e5f475bfd27138fe80f238aec5f7fa6df77ff614f2f5401419405573b40a8b`。
全部 100 文件与 `77d0815` 清单逐字节一致。未重建或改标 wheel、sdist、native
二进制；本合并源码未跑完整后端、全站浏览器、其他 Python/平台、真实 Podman、
真实 ChatGPT OAuth 或正式发布矩阵。新源码 nx5 部署验收由主线程负责。

未修改安全工作流、告警状态或策略。导入的 PR51 修复收紧 TLS、浏览器 cookie
反射及公开协议错误；scope、权限、人工密码/token 哈希算法与 CSRF 边界保持。
已知 token 哈希及 Git 夹具告警仍须有权限的维护者独立正式 triage。本任务没有
dismiss 告警，没有对合并 SHA 跑 CodeQL，也不声称 GitHub 所有检查全绿。详见
[PR51 独立修复证据](pr51-ci-validation.md)。仅写本候选分支，PR51、main、tag、
生产和 SSH 不在本任务范围。

[合并源码结构化证据及完整清单](../benchmarks/gate-root-entry-integration-689b4f9.json)
记录源码保留、命令与范围。[合并源码规范化日志](../benchmarks/gate-root-entry-integration-689b4f9.log)
保留实际输出，省略具体主机路径及生成的 bootstrap 凭据。
[此前独立根入口证据](../benchmarks/gate-root-entry-77d0815.json) 与
[原日志](../benchmarks/gate-root-entry-77d0815.log) 作为历史检查点保持原样；此前未
推送的中间 CI 试合已由此次精确已审源码的合并取代。

## Native readiness smoke 补充修复

修复源码 `63e31a9ec1eaebd3cceb7a65c8d50f3fab5a9acd` 修正了 `8f3f946` 上五个平台均失败的 Release smoke 契约。
已独立读取原始 Linux/Windows 日志。旧脚本访问 `/console` 时没有 HTML Accept，
跳转后的根路径正确返回 JSON；资源正则也仍要求 `/console/` 前缀。新检查明确请求
根路径 HTML，保留机器 JSON 验证，并逐一验证旧入口只有一次 307、最终根 URL、
重复 query、HTML 类型及相同正文。必须同时有 JS 与 CSS；每个引用资源均检查
状态、类型及非空内容，旧资源别名还须字节一致。资源校验保留并加强。

相关后端/打包回归 176 项通过，包含 29 项新增 loopback HTTP 回归；先前 31 项
native 子集与此总数重叠。实际重新执行正式 web/native 构建、归档身份验证、安全
解包及 Linux x86_64 frozen readiness smoke，CPython 3.13.15/PyInstaller
6.22.2 均通过。候选归档 SHA-256 为
`dc5386253dd3e164a125156a76aabcdcc38a871104dfe1de9182b5e6b86990b9`。包内全部 100 个静态文件与最新 web 构建及上述清单一致。
产品/web 源码、锁、版本、安全工作流保持不变。该包仅为未发布的本地候选，其他
平台 native 与新精确 head 的 GitHub CI 须分别核对；本任务未切换 nx5 服务。
真实宿主/客户端验收及告警正式 triage 保持独立。

[Native smoke 修复证据](../benchmarks/gate-root-native-smoke-63e31a9.json) 与
[规范化日志](../benchmarks/gate-root-native-smoke-63e31a9.log) 保存原始失败、实际
前后 HTTP 探测、测试命令及候选清单。未将旧 head 的 CI、Code scanning、Container
成功推断为新 head 的结果。
