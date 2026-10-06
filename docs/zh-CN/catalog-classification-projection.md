# 目录分类数据投影

[English](../catalog-classification-projection.md)

开发分支 `test/gate-catalog-memory-20261006` 源自精确源码 `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`。本次只把 `AccessControlStore.visible_tool_contracts` 改为目录专用分类读取；管理分组目录、variant 成员页及按需分组路由共用该投影。

同步、分类审查、普通工具判定和 OAuth 快照消费者继续使用未改动的完整分类读取。实际目录消费者需要十列：`server_id`、`tool_id`、`fingerprint`、`status`、`effective_access`、`reviewed_by`、`reviewed_at`、`destructive`、`idempotent`、`open_world`。SQL 不再读取 `evidence_json`、分析/来源字段、显示名称及创建/更新时间；结构归一化命中缓存时，指纹与人工审查的安全字段仍需读取。

此变更仅缩窄行宽，保持 250 工具分块、当前用户/grant/token/OAuth 校验、指纹/发布检查及人工审查契约分组。仍对整个受限候选集鉴权后再排序和分页，不缓存授权结果。请求 50,000 工具仍执行 200 次分类 SELECT；本次没有消除完整分组快照构建。

首批集中回归 95 项在 50.75 秒通过：`test_catalog_classification_projection.py`、`test_mcp_group_cache_api.py`、`test_catalog_group_adapter.py`、`test_access_control.py`。真实 HTTP 目录/variant 测试为两个工具各设置 2 MiB 合成 evidence，并用 SQLite 列访问器拒绝十列之外的任何分类读取；冷/暖响应与旧完整读取一致，完整同步仍保留 evidence。25 种授权/审查场景比较完整行与窄列契约投影；多批次测试覆盖 501 个 key、重复 key 和缺失 key。

生产修复检查点为 `93d70525e848a571c429ef80e77f5513640bceb4`。[原始对照测量](../benchmarks/catalog-classification-projection-5000-50000.json) 包含四个依次执行的独立 Linux 进程，均使用 5,000 个服务 ID、50,000 条分类/工具记录。基线回放 exact `7d145c2` 的未改动完整 loader，其余投影和当前 grant 代码一致。每阶段有五次普通暖延迟采样和一次单独 tracemalloc 分配探测。两种模式的分类/权限摘要一致；隐藏一个服务并设置单工具 `none` 覆盖后，均返回 49,989 个有权工具。

| 每行合成 evidence 负载 | Loader | 分类读取 median / p95 ms | 分类分配峰值 MiB | 权限投影 median / p95 ms | 权限分配峰值 MiB |
|---|---|---:|---:|---:|---:|
| 1 KiB | 完整，18 列 | 485.163 / 500.562 | 116.99 | 720.222 / 732.491 | 128.72 |
| 1 KiB | 目录，10 列 | 292.721 / 302.221 | 40.69 | 548.533 / 552.283 | 52.42 |
| 8 KiB | 完整，18 列 | 806.650 / 820.633 | 458.79 | 1177.183 / 1272.946 | 470.52 |
| 8 KiB | 目录，10 列 | 376.018 / 479.708 | 40.69 | 664.621 / 743.522 | 52.42 |

分别在独立进程复现两种模式；再将 `--evidence-bytes` 改为 `8192` 重复：

```bash
uv run --frozen python scripts/benchmark_catalog_classification_projection.py --mode complete --evidence-bytes 1024 --samples 5 --output complete.json
uv run --frozen python scripts/benchmark_catalog_classification_projection.py --mode catalog --evidence-bytes 1024 --samples 5 --output catalog.json
```

测量仅涵盖分类/权限投影，不含配置文件加载和完整分组快照。本次 Linux cgroup 为 16 GiB 内存、四个 CPU 等效额度，与 nx5 验收环境不同。按表格顺序，四个进程生命周期 `ru_maxrss` 为 467,260／330,924／817,048／332,052 KiB，包含 fixture、全部样本和分配探测，不是单请求 RSS。原三个完整 HTTP scale 用例保持不变，独立进程执行后另记结果。分类分配降低不等于全套 cgroup OOM 已解决，之前的累计 RSS 也不构成泄漏证据。本次不包含生产连接、真实凭据、SSH、merge、tag 或 release。

新增多批次回归的初始 fixture 缺少分类必填字段；基准初始 fixture 缺少 grant 必填 `created_by`。已在通过回归/正式测量前修正两处设置错误，未改变产品行为。
