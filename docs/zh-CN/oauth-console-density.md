# OAuth Console 密度 — 开发候选

[English](../oauth-console-density.md) · [内置 OAuth](builtin-oauth.md) · [目录扩展](oauth-catalog-scaling.md)

`test/gate-oauth-density-20261006` 基于整合源码 `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`，修改两个内置 OAuth Console 视图及展示测试。后端授权、公共同意、外部身份配置和依赖锁保持整合源码的合同。本候选不执行发行、部署或真实客户端验收。

## 调整授权范围

居中编辑器使用紧凑标题、客户端名称、状态及已选数量；授权规则按需展示已保存、客户端和令牌族的 scope 上限。到期、速率和并发位于表格上方，label 与控件同行。全目录只读/全部/自定义、清空及刷新均为明确操作；搜索、MCP 和权限筛选只影响展示。刷新保留未保存 IDs 与限额，以后新增服务不会自动加入；只读选择仍仅依据已发布 `read` 分类。

工具行使用固定紧凑 MCP 列、单行名称、复选框和常驻读写标记。原游标按工具引用排序，一页可能跨 MCP 边界；固定列能识别每行，无需伪造整组边界、重复未经核对的组计数或改变目录顺序。独立 MCP 整组视图仍选择一项服务的全部可授权工具，展示服务端确定的已选/可授权及读写计数。

悬停或聚焦展示 Tool ID；激活名称打开只读详情，可复制完整 ID、查看 MCP 身份与已发布权限。同名工具保留唯一可访问 ID。少量短且不同的 MCP 名称使用单选，长名称、重复名称或更大集合使用可搜索精确 ID 选项。分页选择器每次最多读取 15 个本人可见组，保留明确加载更多和重试操作，不获取整个工具定义目录。

页脚将新增/移除/新增写工具数与取消、保存授权并列。保存仍先执行原服务端预览，明确确认完整差异后才写入。当前本人检查、scope 上限、单次确认、CSRF、版本 CAS 和到期/配额不可扩张保持不变。保存结果未知时，明确重读实际已保存状态并核对保留草稿前，继续禁止再次预览/写入；重读失败保留保护。

## 已配置 OAuth 管理

紧凑状态行展示已保存 OAuth 状态、实际签名密钥读取状态及已读取客户端数量。只有成功读取并确认已保存的 OAuth 已启用、地址已保存、有活动密钥及已启用客户端时，才隐藏四步指引；隐藏不代表外部连接验证。

桌面布局左侧 40% 用于地址与签名操作，右侧 60% 用于客户端表。Label 与字段同行；客户端支持搜索、每页 25 行和表内滚动。完整 ID 可以复制，精确回调、scope 和资源在只读详情展示。接入指引集中说明 TLS/回调/接入规则及最后已保存配置的端点。关闭这些详情恢复键盘焦点，不改变状态。

手动 resource 归属、修改地址前关闭规则、签名密钥确认/回读、无密钥禁止启用、客户端轮换/停用确认及一次性 secret 确认均保留原处理函数。真实错误在页内持续展示并可恢复。独立管理资源仍默认关闭并要求精确目标授权；外部身份页面不属于此次布局变更。

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
