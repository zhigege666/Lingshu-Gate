# OAuth 目录扩展 — 开发候选

[English](../oauth-catalog-scaling.md) · [内置 OAuth](builtin-oauth.md)

本候选位于 `test/oauth-catalog-paged-20261005`，结合已验收范围选择 UI、既有 grant 验证和公共按需目录；公共输入已纳入 `3947ae4171d27d2e693ea3f505e49cf6b12fa752`。原 UI 与阶段 A 分支保持不变。此次仅源码整合，不代表发行发布或真实客户端验收。

## 阶段 A：已保存 grant 的认证

原令牌验证先投影所有者的全部可用工具，再检查 5,000 工具目录上限，最后才与已保存 grant 求交。回归已复现：所有者新增到超过 5,000 候选后，原本有效的单工具 grant 收到 HTTP 401。

验证现只使用数据库 grant 的明确工具 ID，以一次原子注册表查询取得这些定义。当前所有者权限、已发布分类、资源、client/grant/family/JWT scope 上限及保存的快照仍是权威。缺失、未发布、变化或撤权的目标不进入 principal；已签名 JWT 的 `tools`/`tool_ids` 声明不能增加目标。存储 grant 超过 5,000 工具或 100 MCP 时，在注册表读取前即拒绝。原有刷新和期限规则保留，刷新后的 bearer 接受同样的有界验证。

单工具调用也只同步该定义，避免丢弃一个包含全部分类表的返回值；其他分类列表 API 的返回合同保持原样。当前验证、`refresh_verified_principal` 和管理授权均复用 `OAuthServer._grant_tools`，不重建 owner 全目录。原子查找返回冻结定义的副本，调用方不能绕过新 revision 修改注册策略或 schema。

## 历史阶段 A 证据

以下结果属于源代码 `d460f5461196c6d45416e1c25cf3e41743e20ac0`，基于 main `d4786fd368e932bc758ea29da1a597c9d9551794`，不是后续公共集成或阶段 B 的测量。

规模及原子注册表专项共 16 项通过。假数据准确包含 5,000 个服务和 50,000 个已发布工具：在所选目标符合既有上限时签发 grant，再新增剩余目录。覆盖原 bearer 与 refresh 后 bearer、已选调用成功、未选调用拒绝、发布/权限撤回、client/family 上限、已签名工具声明伪造及存储选择限额。被测认证及调用期间禁止全注册表与全分类列表投影。既有 OAuth、实时范围、管理资源、委托权限、外部 OAuth 和访问控制回归另有 246 项通过；Ruff、mypy（116 源文件）、web 构建、源码版本及仓库标识检查均通过。

| 已保存 grant 工具数 | 每次验证读取定义数 | 全注册表投影次数 | 验证中位耗时（ms） | Refresh + 验证（ms） | 验证增量峰值（bytes） |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 0 | 7.400 | 137.953 | 19,466 |
| 100 | 100 | 0 | 9.110 | 135.054 | 406,203 |
| 5,000 | 5,000 | 0 | 205.035 | 344.464 | 21,617,711 |

以上是作者实际执行的合成测量，不是生产延迟保证。验证耗时为未开启分配跟踪的 3 次执行中位数；峰值来自另一次 `tracemalloc` 执行，排除假数据构建和已驻留的 50,000 工具注册表。刷新耗时包含签名与验证。可在源码检出中运行 `uv run pytest -q -s tests/test_oauth_catalog_scaling.py tests/test_registry_concurrency.py` 复现。

## 阶段 B：已实现私有候选目录

配置共享候选 port 后，业务 grant 响应明确声明 `scope_catalog_mode: "paged"`，Console 使用 `GET /v1/auth/oauth/grants/{grant_id}/scope-catalog`，不会将旧接口的部分 `tools` 数组当成完整目录。旧 scope-options 在原有上限内保持合同；公网首次同意仍有原来的目录上限。

私有目录支持 `view=tools|groups|unavailable`、最多 100 项、关键词检索、精确 MCP ID 与已发布读写筛选。每页明确返回 `complete: false`、不透明 `next_cursor`、稳定 `catalog_revision`、CSRF、grant/client scope 上限、当前令牌族上限，以及全目录/匹配的准确工具/读/写/MCP 数量。Keyset 分页可遍历整个候选目录，不受 offset 上限限制。整组数量覆盖服务全部可授权成员，即使搜索或只读筛选仅匹配部分工具。响应不含 schema 或 description。整页 JSON（含票据/数量）受 `max_bytes` 8–64 KiB 约束，只移除完整项，并用游标继续读取余项。

`POST .../scope-selection` 是绑定会话/Origin/CSRF 的只读解析器。`all` / `read` 按整个当前可授权目录替换草稿，不受展示筛选/分页限制；`read` 只含已发布 `read` 分类。`groups` 加入或清除明确 MCP；清除仅查看有界草稿/已保存 IDs。`ids` 独立于本页核验明确草稿 IDs。响应保留完整的明确 `tool_ids`、`available_ids`、通用 `unavailable_ids`、服务端权威已选/差异/写数量和最多 100 MCP 已选数量。摘要元数据最多核验 100 个指定 ID（默认 50 个），预算为 2–64 KiB；ID 数组保留完整有界选择，摘要预算不是整响应预算。超过 5,000 工具或 100 MCP 返回结构化超限错误，不返回部分选择，不修改 grant。

刷新保留草稿 IDs 和限额，重验可用性，快捷模式回到“自定义”；以后新增服务不会自动选入。失败保留草稿。不可见目标不返回名称或服务元数据；仅对本人当前可访问工具分页解释不可授权原因。管理员 API Token 可按现有管理员策略调用未发布 MCP，但 OAuth 在发布前排除；普通 writer 没有该旁路，因此诊断不披露那些定义。

预览和保存携带 `catalog_revision`，使用独立版本票据，复用当前本人/会话、发布、grant/client/resource 版本、精确目标摘要、单次确认、版本 CAS、期限/配额只能收紧和原子脱敏审计。令牌及刷新令牌族保持原 scope。同步后 registry 增量返回冲突，包括 SQL 读取前刚入队的变化；不能把旧索引页当成新 generation 发出。策略 epoch、当前角色/权限及已到期本人资源授权使旧候选失效；重启更换候选 incarnation。变化/过期游标明确冲突，UI 要求刷新，不悄悄重启。

## 共享归属与文件边界

| 归属 | 责任 |
|---|---|
| `ToolCatalog` | 原 SQLite `gate_tool_catalog`/FTS 增量索引、registry 队列及策略 epoch；仅增加只读 revision marker。没有第二套索引或 registry。 |
| `ports/oauth_candidate_catalog.py` / `OAuthCandidateCatalog` | 在共享索引上进行无 schema、当前本人 SQL 投影，准确计数、keyset 分页及有界草稿/全局/整组解析。 |
| `OAuthServer` | grant/client/resource/session 上限、同步 generation 检查、cursor/CSRF 绑定及原预览/保存事务。 |
| 私有 OAuth 路由 | 严格请求类型、安全错误、请求体/查询预算、限流准入及明确分页能力。 |
| 分页 picker / grant 编辑器 | 本页与完整已选 IDs 分离；明确解析操作、保留草稿、有界原因页及权威差异数量。 |

Console 在 OAuth 路由启动时不再预取旧全定义 `/v1/tools`。概览、工具、调用和服务页在真正消费时读取，也支持从 OAuth 导航进入。此处消除候选编辑期间无关的全 schema 请求，并未把这些独立旧页面改为分页。

## 当前执行范围

HTTP 套件使用精确 5,000 服务 / 50,000 工具，遍历全部 50 个 MCP 整组页，从已保存 grant 和首页之外检索小集合，并禁止请求期间全 registry/分类投影。独立 5,000 工具/100 MCP 与 101 MCP 用例覆盖两个不变选择上限。回归覆盖新发布/未发布服务、管理员 API Token 对比、隐藏目标、旧已缩小令牌族、本人/发布/client/grant/resource 变化、同步竞争、CSRF/会话归属、配额不能扩大和单次保存。

可选 loopback 浏览器夹具使用合成管理员，以及真实 catalog/session/selection/preview/save HTTP，具有 5,000 服务 / 50,000 工具。四种桌面尺寸、中英两种语言检查 label 同行、表格空间、页脚可见及页面溢出。只在最终保存注入网络失败以验证草稿恢复，不 mock 目录或解析器；独立导航检查只为无关的旧工具页 mock 一个定义。作者浏览器证据见下；独立 UI 复核和真实客户端验收保持分列。

## 源码冻结前的作者浏览器证据

冻结前大目录共 11 项全部通过：8 个真实布局、2 个真实整组/刷新/超限/保存恢复流程和 1 个导航检查。作者实际打开全部 8 张截图；PNG 与测量 JSON 已放在 `docs/images/console/oauth-catalog/`。[英文 1600×900](../images/console/oauth-catalog/paged-en-US-1600x900.png) 与[中文 1600×900](../images/console/oauth-catalog/paged-zh-CN-1600x900.png) 展示紧凑编辑器。全部 label 与控件同行，body/document 溢出为零，页脚始终可见。8 个真实 OAuth 布局用例没有旧 scope-options 或 `/v1/tools` 请求。

| 视口 | 英文 / 中文完整可见行数 | Body / document 溢出 |
|---|---:|---:|
| 1600×900 | 8 / 8 | 0 / 0 |
| 1920×1080 | 13 / 13 | 0 / 0 |
| 2560×1080 | 13 / 13 | 0 / 0 |
| 2560×1440 | 15 / 15 | 0 / 0 |

构建后从 `web/` 复现：`GATE_E2E_OAUTH_CATALOG_SCALE=1 npm exec -- playwright test e2e/oauth-grants.spec.ts e2e/oauth-paged-catalog.spec.ts`；加 `e2e/oauth-consent.spec.ts` 复核未变化的同意流程。后端候选专项为 `uv run pytest -q tests/test_oauth_paged_catalog.py tests/test_oauth_scope_catalog.py`，后端完整命令为 `uv run pytest -q`。固定提交的最终执行结果与这些冻结前作者截图分列交付；独立 UI 验收仍由设计负责人完成。

未修改或验证真实 Plane 分类、ChatGPT 授权/缓存、生产 grant、真实凭据、SSH、发行 tag 或制品。
