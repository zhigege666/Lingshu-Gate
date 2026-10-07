# Console 交付 API

这些接口要求 `operations.manage`；普通工具授权不赋予部署权限。测试仅用合成的本地项目，不启动隧道、不注册 OAuth、不授予外部持久授权，也不部署生产服务。

## 最终配置与确认

`POST /v1/builds/{build_id}/deploy/preview` 接受 `server_id`、`start`（默认 false）、`overwrite`（默认 false）、`manifest_patch`、`credential_policy`（默认 `preserve_existing`，或 `require_none`）。补丁递归合并到成功构建的 Manifest；只提交用户相对生成配置的改动，避免上传阶段的完整配置覆盖构建产物设置。部署补丁不能替换制品绑定的 `launch.type`、`launch.command`、`launch.cwd`。数组按整体替换，`null` 删除对象字段；受管凭据保留策略可能仍保留被补丁删除的引用。

预览返回脱敏最终 `manifest`、`changed_fields`、`config_digest`、`expected_previous_config_digest`、`expected_credential_binding_digest`、`credential_state`、`interrupts_existing_service`。这是静态检查，不是下游连接探测；预览不写部署记录或服务配置。

确认后调用 `POST /v1/builds/{build_id}/deploy`，提交原始补丁及预览的两个 `expected_*` 字段，同时提交 `expected_config_digest=preview.config_digest`。实际部署必须提交候选摘要；客户端需要先预览再提交。覆盖现有目标始终要求正确的旧配置摘要，凭据继承要求已验证的绑定摘要。冲突返回 HTTP 409，需要重新预览与确认。不要将预览的掩码 Manifest 作为补丁写回；掩码补丁在计算摘要前即被拒绝。

最终合并配置在应用运行态前只保存一次。受管凭据引用和用户 Slot 声明复用已有交付保留检查，不从掩码响应复制秘密值。部署历史保存脱敏配置及加密旧快照。摘要检查与配置写入共享单 Core 修改锁，但文件、运行态和 SQLite 不构成一个事务。失败报告实际补偿结果；`rollback_succeeded=null` 表示未知，不能当成功。

`start=false` 会应用停止运行态，即使替换的是正在运行的服务。`start=true` 必须达到 `running` 才能报部署成功。这是可能中断服务的替换，不是热更新。仅 `rollback_available=true` 时提供手动回滚，不承诺自动恢复。回滚快照必须通过校验并匹配目标。

## 可恢复的个人草稿

`GET /v1/delivery-drafts/{upload_id}` 返回当前运维用户的草稿；不存在时返回空默认值和 `revision=0`。`PUT` 使用 `expected_revision` 整体替换草稿，字段为 `manifest_patch`、`server_id`、`build_id`、`deployment_id`、`overwrite`、`start`、`project_root`、`runtime_override`。返回版本加一，旧版本写入返回 HTTP 409。构建必须属于该上传，部署必须属于所提供的构建。

草稿独立于服务 Manifest 加密存储，并按运维用户及上传隔离。保存草稿不修改服务配置或运行态。已知敏感环境变量或 HTTP Header 名要求 `${credential:id}` 引用，拒绝掩码值和 `user_credential_values`；普通环境设置正常保留。名字检查不能识别所有秘密，因此整个草稿加密存储，审计事件不包含草稿内容。上传删除后对应草稿不可访问；加密草稿随本地数据目录保留策略管理。

## 验证

运行针对性的合同测试：

```bash
uv run pytest -q tests/test_real_delivery_journey.py tests/test_console_deployment_api.py tests/test_delivery_drafts.py tests/test_build_deploy_reliability.py tests/test_project_delivery_mcp.py tests/test_mcp_configuration_service.py tests/test_mcp_config_atomicity.py tests/test_build_request_boundary.py tests/test_build_execution_boundary.py
```

`D01` 打包仅依赖 Python 标准库的 MCP 服务，真实执行上传、构建、草稿、预览、启动部署，以 `2026-07-28` 协议发现一个工具并通过真实 stdio 进程调用。保存 `apply=true,start=true` 后必须读到改变的配置标记和不同进程号。另有临时后端场景验证手动回滚启动失败后磁盘与运行态保持一致。难以确定性触发的失败另用故障注入覆盖。这些场景不接入外部 OAuth 身份，不访问公网服务。

`D02` 构建并启动产物 v1，执行一个无依赖且明确退出码为 7 的本地 Node 构建脚本，确认构建失败后旧服务仍运行，进程号、标记、产物路径和磁盘配置均不变。随后构建第二份 Python 产物，预览并确认替换，真实调用新进程读到 v2 且保留所选运行设置，再显式手动回滚到有效加密快照的 v1。两份 Python 产物均使用当前协议真实 stdio；失败构建不执行安装或网络操作。
