# 保留策略与清理

运行日志、事件、调用记录分别持久保存独立保留天数，默认均为 7 天。管理能力 `retention.manage` 默认仅内置管理员具备。服务整体日志读取权限或 `operations.manage` 本身不授予保留策略管理权。

HTTP 字段为 `runtime_logs_retention_days`、`events_retention_days`、`call_records_retention_days`，均为 1–3650 的整数；内部依次对应 `logs_days`、`events_days`、`invocation_audits_days`。同一 CAS revision 也保护 `payload_mode`，初始为 `metadata_only`；可选 `redacted` 模式见[调用记录指南](invocation-recording.md)。

## 默认关闭

```dotenv
LINGSHU_GATE_RETENTION_WORKER_ENABLED=false
LINGSHU_GATE_RETENTION_INTERVAL_SECONDS=3600
```

这是部署设置，不能在浏览器切换。worker 关闭时，立即清理返回 `409 retention_worker_disabled`，不创建任务。保存策略不会运行清理。启用 worker 是独立部署决定：经过配置间隔后，按已保存策略执行定时清理。删除不可恢复。本轮实现验证未启用任何真实环境；测试仅使用独立临时数据库与合成记录。

## 预览、保存和执行分离

1. `GET /v1/retention/policy` 返回策略、revision 和部署 `worker_enabled` 状态。
2. `POST /v1/retention/preview` 可携带完整候选策略，只读统计符合条件的记录，不写数据库。响应包含固定 UTC cutoff、候选策略、当前 revision、缩短的领域及有效 5 分钟的 preview ID。数量是当前快照估算，不是对记录的预留。
3. `PUT /v1/retention/policy` 携带 `expected_revision`。缩短任一天数还必须携带匹配的 `preview_id` 和 `confirmed:true`；后端核对候选策略、版本与有效期。取消确认不发送修改请求。并发修改返回 409。保存自身不排队清理。
4. 立即清理需要先对**已保存策略重新预览**，再独立确认 `POST /v1/retention/jobs`，携带 `preview_id`、`expected_revision`、`confirmed:true`。后端使用预览绑定的固定 cutoff。202 只表示任务已排队，不表示删除成功。
5. `GET /v1/retention/jobs/{id}` 返回 `queued`、`running`、`retry`、`succeeded`、`failed`、`cancelled` 状态、各表已删除数量与安全错误码。`POST /v1/retention/jobs/{id}/cancel` 停止后续批次，不能恢复已经删除的记录。

preview ID 仅保存在进程内存，重启后须重新预览；它不是授权令牌，每个接口都会重新检查管理能力。具备该能力的管理员共享管理范围。策略 revision 变化后，旧任务会在下一个删除批次前取消。

## UTC、批次与恢复

迁移 `0002_retention_and_invocation_payloads` 添加策略、任务、租约表、UTC 表达式索引及可选 payload 表。条件严格为 `julianday(created_at) < julianday(cutoff)`：带时区偏移的时间按 UTC 比较，恰好位于边界的记录保留，非法旧时间不会被选中。每个事务最多删除一个领域的 200 条记录，内部批量参数限制为 1–1000。删除调用审计时，启用的外键将级联删除对应 `invocation_payloads`；运行日志与事件独立处理。

SQLite 租约防止并发 worker 同时清理，30 秒后过期以支持崩溃恢复；租约与批次变更共同提交。失败批次回滚，延迟 5 秒重试，累计 3 次失败后停止。取消在批次间检查，关闭进程前等待当前有限事务完成。这不代表支持多 Core SQLite 部署；仍遵循单写入者、单 Core 架构。启用不可恢复清理前，应使用现有部署备份流程。

`tests/test_retention.py` 覆盖默认值/CAS、只读预览、缩短确认、UTC/索引/边界、小批次、租约接管、重试、取消、payload 级联、真实认证 HTTP 接口、worker 关闭时拒绝和临时数据库启用执行。UI 确认与真实部署启用属于独立验收层。
