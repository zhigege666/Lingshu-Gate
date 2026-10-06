# OAuth Console 密度 — 开发候选

[English](../oauth-console-density.md) · [内置 OAuth](builtin-oauth.md) · [目录扩展](oauth-catalog-scaling.md)

`test/gate-oauth-density-20261006` 基于整合源码 `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`，修改两个内置 OAuth Console 视图及展示测试。后端授权、公共同意、外部身份配置和依赖锁保持整合源码的合同。本候选不执行发行、部署或真实客户端验收。

## 调整授权范围

居中编辑器使用紧凑标题、客户端名称及状态；已选/可授权数量只在列表统计展示。授权规则按需展示已保存、客户端和令牌族的 scope 上限。到期、速率和并发位于表格上方，label 与控件同行。全目录只读/全部/自定义、清空及刷新均为明确操作；搜索、MCP 和权限筛选只影响展示。刷新保留未保存 IDs 与限额，以后新增服务不会自动加入；只读选择仍仅依据已发布 `read` 分类。

工具行使用固定紧凑 MCP 列、单行名称、复选框和常驻读写标记。原游标按工具引用排序，一页可能跨 MCP 边界；固定列能识别每行，无需伪造整组边界、重复未经核对的组计数或改变目录顺序。独立 MCP 整组视图仍选择一项服务的全部可授权工具，展示服务端确定的已选/可授权及读写计数。

悬停或聚焦展示 Tool ID；激活名称打开只读详情，可复制完整 ID、查看 MCP 身份与已发布权限。同名工具保留唯一可访问 ID。少量短且不同的 MCP 名称使用单选，长名称、重复名称或更大集合使用可搜索精确 ID 选项。分页选择器每次最多读取 15 个本人可见组。原生加载更多/重试按钮位于 MCP listbox 之外：Tab 进入操作，Enter/Space 激活，Shift+Tab 返回筛选框，Escape 仅关闭菜单并恢复筛选焦点；最后一个操作后的 Tab 进入下一筛选控件。分页失败后重试同一游标，保留已加载组和范围草稿，不获取整个工具定义目录。

页脚将新增/移除/新增写工具数与取消、保存授权并列。保存仍先执行原服务端预览，明确确认完整差异后才写入。当前本人检查、scope 上限、单次确认、CSRF、版本 CAS 和到期/配额不可扩张保持不变。保存结果未知时，明确重读实际已保存状态并核对保留草稿前，继续禁止再次预览/写入；重读失败保留保护。

## 已配置 OAuth 管理

紧凑状态行展示已保存 OAuth 状态、实际签名密钥读取状态及已读取客户端数量。只有成功读取并确认已保存的 OAuth 已启用、地址已保存、有活动密钥及已启用客户端时，才隐藏四步指引；隐藏不代表外部连接验证。

桌面布局左侧 40% 用于地址与签名操作，右侧 60% 用于客户端表。Label 与字段同行；客户端支持搜索、每页 25 行、40 px 单行和整行倍数高度的表内滚动。鼠标或键盘激活客户端名称打开只读详情，展示精确回调、scope 和资源；其中“编辑客户端”进入原编辑器。移除每行重复的详情按钮，保留完整 ID 复制、轮换及启用/停用操作。关闭详情或编辑后，焦点返回名称。

活动签名密钥数量只在顶部状态行展示；下方签名区保留操作与真实读取中/错误/缺少密钥状态。已启用配置说明先停用并保存才能修改地址；待保存停用时地址仍锁定，保留原确认。独立管理连接只常驻一句用途/授权说明，固定路径、四个工具及精确目标同意细节保留在接入指引和实际启用确认中。指引仍集中说明 TLS/回调/接入规则及最后已保存配置的端点。

手动 resource 归属、修改地址前关闭规则、签名密钥确认/回读、无密钥禁止启用、客户端轮换/停用确认及一次性 secret 确认均保留原处理函数。真实错误在页内持续展示并可恢复。独立管理资源仍默认关闭并要求精确目标授权；外部身份页面不属于此次布局变更。

## 已执行验证及作者证据

固定代码检查点为 `fdcb3545aa88d1ccb3a961fca3e2c47055bfb105`，延续此前 `2a84ea4` 代码 / `4fc96c8` 证据交付。整合负责人复核该交付后提出六项视觉收尾，并发现键盘分页问题；本检查点实现这些修正，最终独立复核仍待完成。后续证据提交只更新文档及合成 PNG/JSON 文件。全部当前截图均按新代码 SHA 重拍，两张 `7d145c2` 基线单列保留；密度夹具另记录已构建 Console 入口 SHA256。[制品清单](../images/console/oauth-density/manifest.json)记录每个证据文件的摘要。

| 已执行检查 | 结果 |
|---|---|
| 前端源码及行为 | Check 通过；74 文件的 441 测试在 18.23 秒内通过；两个构建通过。保留既有 OAuth 大 chunk 提示。 |
| 固定 SHA 的完整选定浏览器回归 | 206 项通过，无跳过，耗时 10.8 分钟：密度/键盘 26、本人授权 70、公共同意 15、真实分页目录 17、配置前置条件 26、客户端管理六、管理资源 40、外部身份六。 |
| 授权后端针对性回归 | 此前 `2a84ea4` 检查点的内置 OAuth、范围目录、live scope 和分页目录共 183 项在 223.05 秒内通过。本次重新核对后端源码/测试及依赖锁与整合基线逐字节一致，沿用该结果；未重跑后端套件。 |
| 源码/配置约束 | 本次仓库身份、未变更的 0.4.4 版本、指南链接和空白检查通过；此前冻结 Python/npm 依赖验证通过，本次锁文件未变更。未修改授权 API 或信任边界。 |

普通工具表行高为 40 px。精确 `7d145c2` 的 1600×900 [范围基线](../images/console/oauth-density/baseline-scope-en-US-1600x900.png)有七行完整 45 px 工具行，第八行部分可见；新视图有九行完整工具。[已配置页面基线](../images/console/oauth-density/baseline-infrastructure-en-US-1600x900.png)仍展示大块步骤，签名操作位于首屏之外。这两张基线截图故意不满足新增密度要求，用于对照，不属于基线测试通过声明。

| 桌面尺寸 | 完整工具行，英文 / 中文 | 完整客户端行，英文 / 中文 | 客户端滚动区高度 | 范围 body 纵向 / 文档横向溢出 |
|---|---:|---:|---:|---:|
| 1600×900 | 9 / 9 | 5 / 5 | 200 px | 0 / 0 |
| 1920×1080 | 13 / 13 | 9 / 9 | 360 px | 0 / 0 |
| 2560×1080 | 13 / 13 | 9 / 9 | 360 px | 0 / 0 |
| 2560×1440 | 22 / 22 | 11 / 11 | 440 px | 0 / 0 |

每个已测范围 label 均单行且与控件同行。已配置页面的 label 也与控件同行，横向溢出为零；四个尺寸均能看到指引/登记/签名/客户端操作/管理开关。61 客户端夹具核验实测 40 px 行、整行倍数滚动高度、无遮挡完整第五行、每页 25 行、表格底行可访问及分页/搜索滚动复位。真实大目录布局单独计量 MCP 整组行：两个语言均为 9、14、14、15 行完整行，body/横向溢出为零，未读取旧 scope-options 或工具全定义表。

| 桌面尺寸 | 范围截图 | 已配置管理截图 |
|---|---|---|
| 1600×900 | [English](../images/console/oauth-density/scope-en-US-1600x900.png) · [中文](../images/console/oauth-density/scope-zh-CN-1600x900.png) | [English](../images/console/oauth-density/infrastructure-en-US-1600x900.png) · [中文](../images/console/oauth-density/infrastructure-zh-CN-1600x900.png) |
| 1920×1080 | [English](../images/console/oauth-density/scope-en-US-1920x1080.png) · [中文](../images/console/oauth-density/scope-zh-CN-1920x1080.png) | [English](../images/console/oauth-density/infrastructure-en-US-1920x1080.png) · [中文](../images/console/oauth-density/infrastructure-zh-CN-1920x1080.png) |
| 2560×1080 | [English](../images/console/oauth-density/scope-en-US-2560x1080.png) · [中文](../images/console/oauth-density/scope-zh-CN-2560x1080.png) | [English](../images/console/oauth-density/infrastructure-en-US-2560x1080.png) · [中文](../images/console/oauth-density/infrastructure-zh-CN-2560x1080.png) |
| 2560×1440 | [English](../images/console/oauth-density/scope-en-US-2560x1440.png) · [中文](../images/console/oauth-density/scope-zh-CN-2560x1440.png) | [English](../images/console/oauth-density/infrastructure-en-US-2560x1440.png) · [中文](../images/console/oauth-density/infrastructure-zh-CN-2560x1440.png) |

作者实际查看了上述全部 16 张当前截图、两张未修改基线、两个当前深色长内容范围和两个当前深色管理截图。另查看了真实分页 1600×900 示例、原生键盘分页焦点截图（[English](../images/console/oauth-density/selector-keyboard-en-US-1600x900.png)、[中文](../images/console/oauth-density/selector-keyboard-zh-CN-1600x900.png)），以及全部四张丢响应/回读截图：[English 未知](../images/console/oauth-density/save-unknown-en-US-1600x900.png)、[English 回读](../images/console/oauth-density/save-reconciled-en-US-1600x900.png)、[中文未知](../images/console/oauth-density/save-unknown-zh-CN-1600x900.png)、[中文回读](../images/console/oauth-density/save-reconciled-zh-CN-1600x900.png)。八个真实分页布局都有自动几何证据，未声称手动查看了其余六张。独立设计复核及真实 Gate/Plane/ChatGPT 验收由整合负责人继续完成；本任务未修改生产凭据、授权、服务、SSH 会话、发行 tag 或发行制品。

## 复现展示及行为证据

先构建，再在 `web/` 执行：

```bash
GATE_E2E_OAUTH_CATALOG_SCALE=1 \
GATE_IDENTITY_EVIDENCE_DIR=/tmp/gate-identity-evidence \
GATE_OAUTH_SCREENSHOT_DIR=/tmp/gate-oauth-evidence \
GATE_UI_SOURCE_SHA=<tested-code-commit> \
npm exec -- playwright test \
  e2e/oauth-density.spec.ts e2e/oauth-grants.spec.ts e2e/oauth-consent.spec.ts \
  e2e/oauth-paged-catalog.spec.ts e2e/oauth-setup.spec.ts \
  e2e/oauth-management.spec.ts e2e/oauth-management-resource.spec.ts \
  e2e/external-identity-layout.spec.ts
```

密度夹具使用 137 工具、六个 MCP 和 61 客户端的模拟 OAuth 响应。真实分页场景通过 loopback HTTP 使用 5,000 MCP 和 50,000 工具，覆盖已提交保存响应丢失、重读失败及后续独立确认更新。外部身份回归需要明确启用证据选项。合成截图、作者查看、独立设计复核及真实 Gate/ChatGPT 验收分列报告。
