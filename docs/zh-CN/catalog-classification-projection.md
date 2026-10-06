# 目录分类数据投影

[English](../catalog-classification-projection.md)

开发分支 `test/gate-catalog-memory-20261006` 源自精确源码 `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`。本次只把 `AccessControlStore.visible_tool_contracts` 改为目录专用分类读取；管理分组目录、variant 成员页及按需分组路由共用该投影。

同步、分类审查、普通工具判定和 OAuth 快照消费者继续使用未改动的完整分类读取。实际目录消费者需要十列：`server_id`、`tool_id`、`fingerprint`、`status`、`effective_access`、`reviewed_by`、`reviewed_at`、`destructive`、`idempotent`、`open_world`。SQL 不再读取 `evidence_json`、分析/来源字段、显示名称及创建/更新时间；结构归一化命中缓存时，指纹与人工审查的安全字段仍需读取。

此变更仅缩窄行宽，保持 250 工具分块、当前用户/grant/token/OAuth 校验、指纹/发布检查及人工审查契约分组。仍对整个受限候选集鉴权后再排序和分页，不缓存授权结果。请求 50,000 工具仍执行 200 次分类 SELECT；本次没有消除完整分组快照构建。

首批集中回归 95 项在 50.75 秒通过：`test_catalog_classification_projection.py`、`test_mcp_group_cache_api.py`、`test_catalog_group_adapter.py`、`test_access_control.py`。真实 HTTP 目录/variant 测试为两个工具各设置 2 MiB 合成 evidence，并用 SQLite 列访问器拒绝十列之外的任何分类读取；冷/暖响应与旧完整读取一致，完整同步仍保留 evidence。25 种授权/审查场景比较完整行与窄列契约投影；多批次测试覆盖 501 个 key、重复 key 和缺失 key。

同规模对照和 scale 结果将在实际执行后另行记录。分类分配降低不等于全套 cgroup OOM 已解决，之前的累计 RSS 也不构成泄漏证据。本次不包含生产连接、真实凭据、SSH、merge、tag 或 release。
