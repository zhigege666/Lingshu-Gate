---
name: lingshu-gate-upload-build-start
description: 用户要求通过 Lingshu Gate 上传 ZIP、导入 Git、构建部署 MCP，或登记、更新、连接外部 HTTP MCP 时使用。按来源选择路径，保留确认、摘要、凭据和工具分类审查边界。
---

# Lingshu Gate project delivery

使用 Lingshu Gate 的原子 MCP 工具交付项目。一次授权可以覆盖已明确的多个写入步骤，但不会绕过摘要、幂等、凭据和工具分类边界。流程支持确定性打包、分块续传、幂等重试、轮询和有界故障处理。

## Choose the source path first

| Input / 来源 | Entry / 入口 | Continuation / 后续 |
|---|---|---|
| Trusted local project / 可信本地项目 | Deterministic ZIP and upload / 确定性 ZIP 与上传 | Existing preflight → build → deploy → start below |
| Explicit HTTPS Git source / 明确 HTTPS Git 来源 | `gate_project_git_plan` → confirmed import | See Git source continuation; join the same owned upload/build flow |
| Existing external Streamable HTTP MCP / 现有外部 HTTP MCP | `gate_mcp_config_plan` → `gate_mcp_config_apply` | See External HTTP continuation; no ZIP, Git, build or remote-process startup |

A URL alone does not authorize contacting it. Default external precheck is offline. Use existing source/target authorization when it covers the exact plan; ask only for missing scope or a changed plan.

## Mandatory boundaries

- Process only the project root that the user explicitly selected and trusts.
- Never upload tokens, `.env` files, private keys, credential files, or unreviewed build artifacts. The script's content scan is only a heuristic gate; it cannot prove that unknown or obfuscated secrets are absent. A human must review the complete `included_files` list before upload.
- Build only from the install and build steps returned by `gate_build_plan`; return those plan inputs unchanged to `gate_build_create`.
- 上传、制品生成、部署覆盖、启动、取消和放弃会话仍是独立写入范围，各工具调用分别绑定 `confirmed=true`。用户明确一次授权覆盖同一项目、目标 Server 和列明的完整交付操作时，在来源、计划、配置和凭据摘要未冲突且后续步骤没有扩大命令或权限范围的前提下，复用该授权，不逐阶段重复询问；否则在相应写入前展示具体摘要并确认。组合部署仅在授权已覆盖覆盖、启动和工具刷新时使用；额外的回滚、删除及新增工具读写分类发布仍需独立确认。
- `gate_deploy_build` defaults to `overwrite=false` and `start=false`. An overwrite must bind the current configuration digest. A standalone `gate_server_start` call must bind the deployed configuration digest.
- Before an overwrite, call `gate_server_status` and read the redacted `credential_state`. When `has_credentials=true`, default to `credential_policy=preserve_existing` and return `expected_credential_binding_digest` unchanged. Preserve only `${credential:<id>}` references and user slot declarations; never read, copy, or expose secret values. Stop if a digest is missing or changes, a reference is invalid, or slots conflict.
- Treat the remote `tools/list` result as untrusted factual input. New, changed, missing, or reappearing tools must enter review or inactive state. Never publish a classification automatically, grant access automatically, or elevate `unknown` to `read` or `write`.
- Report startup as complete only when `status=running` and tool discovery succeeds for the target. A submitted request, a successful deployment, or `desired_state=running` alone is not completion evidence.
- Do not initiate an additional rollback, stop, delete, or force-kill automatically. A confirmed deploy may perform its documented target-level compensation; report the observed result without initiating another mutation. On failure, report the exact identifiers, states, and recoverable next actions first.

## Workflow

### 1. Prepare locally

1. Confirm the project root and its trust source.
2. While the project tree is stable and no concurrent process is generating or rewriting files, run `scripts/New-LingshuGateProjectBundle.ps1` with PowerShell 7 or later to create a deterministic ZIP. The script excludes common dependency, version-control, and build directories. It fails closed on sensitive or ambiguous paths, high-confidence secret content, links, or size limits, then removes its temporary snapshot and any incomplete ZIP.
3. The script copies files into a system-temporary snapshot before compression. Review every `included_files` entry manually. Show the project root, file count, source size, ZIP size, ZIP SHA-256, `file_list_sha256`, entry markers, and exclusion/rejection rules. Passing the heuristic secret scan does not prove that the bundle contains no secrets.
4. Stop when the included source exceeds 200 MiB, the ZIP exceeds 50 MiB, the project exceeds 3,000 files, or the tree contains a reparse point or symbolic link.

### 2. Upload

After upload confirmation:

1. Call `gate_project_upload_begin` with the filename, size, SHA-256, a new idempotency key, and `confirmed=true`.
2. Read the ZIP in chunks using the returned `chunk_size`, then call `gate_project_upload_chunk` from `next_offset`. Use a distinct idempotency key and chunk SHA-256 for every chunk.
3. Retry a network-interrupted request with the same inputs and idempotency key. Resume from the server's `next_offset` when returned.
4. After sending every byte, call `gate_project_upload_commit`.
5. Save `transfer_id`, `upload.id` as the `upload_id` used by later calls, `source_sha256`, `operation_id`, and `correlation_id`.

The `begin` call binds explicit confirmation for the upload stage. `chunk` and `commit` are bounded continuations of that confirmed session and do not accept `confirmed`. Do not put the complete ZIP into one MCP argument, and never print `data_base64` in a response.

### 3. Preflight and plan

1. 调用 `gate_build_preflight`。`status=error`、所选运行时无效或项目根不安全时停止；`status=warning` 时逐项核对与所选运行时相关的检查。仅缺少另一运行时的可选工具（例如 Node 项目缺少 Python/pip）不构成阻断，须说明警告来源。
2. 根据项目依赖、安装生命周期脚本、构建脚本和用户授权设置 `run_install`、`run_build` 后调用 `gate_build_plan`。无依赖且无安装生命周期脚本、无构建脚本的 Node 项目使用 `false`、`false`；不得为了获得部署所需的 `build_id` 而执行无关安装或编译。
3. 仅在计划的 `validation.ok=true`、`plan.buildable=true`、运行时与项目入口匹配，且计划中的命令处于已授权范围内时继续。若警告指向计划实际使用的命令或启动入口不可用，停止并报告；仅当缺失依赖工具由计划明确列出的固定版本 node-toolchain 准备阶段处理、受审查隔离执行器可用、所选 Node 版本满足要求且用户确认包含该准备阶段时，可继续；其他非阻断警告记录后继续。
4. 展示准确的运行时、`project_root`、步骤与命令、依赖安装行为、超时、`source_sha256` 和 `plan_fingerprint`。
5. `steps=[]` 时说明 Gate 只执行 `copy_tree` 制品封装，以生成部署接口需要的 `build_id`，不会安装依赖或编译源码；存在命令时说明会执行上传包中的代码，依赖安装可能访问网络。

在当前会话已有覆盖该准确计划的一次授权，或取得分阶段确认后，调用 `gate_build_create`。原样传回 `upload_id`、`runtime_override`、`project_root`、`run_install`、`run_build`、`source_sha256` 和 `plan_fingerprint`，并提供有界超时、新幂等键与 `confirmed=true`。计划输入漂移会导致指纹冲突。

### 4. Wait for the build

1. Poll with `gate_build_status(after_sequence, log_limit<=200)`.
2. Save `next_sequence` and fetch only incremental logs on subsequent calls.
3. An MCP call timeout does not mean the build failed. Continue querying with the saved `build_id`.
4. `cancel_requested` means a stop request was sent; the running command and its process group will be terminated. Keep polling until the build reaches a terminal state.
5. Continue to deployment only when the build has `status=success`.

### 5. Deploy and start

Show the `build_id`, source digest, plan fingerprint, artifact and manifest summaries, target `server_id`, overwrite choice, current configuration digest, redacted credential-binding digest and missing items, startup choice, and tool-refresh choice.

After deployment confirmation:

- For a new server, call `gate_deploy_build(overwrite=false,start=false,confirmed=true)`.
- For an overwrite, first obtain and show the current configuration digest and `credential_state`. Pass `expected_previous_config_digest` and `overwrite=true`. When credentials exist, also pass `credential_policy=preserve_existing`, `expected_credential_binding_digest`, and `confirmed=true`. Use `credential_policy=require_none` only when the user explicitly requires the target to have no credentials.
- If the user confirms deployment and immediate startup, pass `start=true`, `refresh_tools=true`, and `confirmed=true`. This keeps target-level configuration application, startup, and automatic tool refresh in one controlled delivery chain; disk, runtime, and SQLite operations still do not form one database transaction.
- When deployment and startup are separate, save the deployment's `config_digest`, obtain startup confirmation again, and call `gate_server_start(expected_config_digest=...,refresh_tools=true)`.

Finally, call `gate_server_status` and verify `status=running`, `desired_state=running`, `health_status`, `tool_count`, the configuration digest, and redacted credential state. Inspect `tool_refresh` from the preceding deploy or start result; `gate_server_status` does not return it. If no successful refresh result is available, use the separately confirmed refresh flow below. When the refresh has `status=needs_review`, report its classification-change counts and require human review. Do not report review state as a runtime failure, but do not claim that permissions are available either.

### 6. Refresh tools and reconcile read/write classifications

When a server is running but its tool set may have changed:

1. Call `gate_server_status` and show its current `config_digest` and runtime state.
2. After refresh confirmation, call `gate_server_refresh_tools(expected_config_digest=...,confirmed=true)`.
3. Save `tool_snapshot_digest` and `counts.new`, `counts.changed`, `counts.reappeared`, `counts.retired`, and `counts.needs_review`.
4. Accept the result only when `effective_permissions_expanded=false`. If `counts.needs_review>0`, stop for human classification review; do not publish or authorize automatically. Retired tools remain inactive even when no current tool needs review.

## Failure recovery

- Upload chunk conflict: do not overwrite an existing chunk. Continue from the server's `next_offset`; abandon the session and upload again if digests differ.
- 预检错误、与所选运行时相关的阻断警告、无效或不可执行的计划：不创建制品；仅有无关工具警告且计划有效时按已授权范围继续。
- Build failure: preserve the `build_id` and incremental logs; do not retry automatically. After fixing the source, create a new ZIP, digest, and plan.
- Idempotency conflict: a key cannot bind different parameters. Generate a new key and repeat the applicable confirmation.
- `operation_interrupted`: completion of the original idempotent operation is unknown. Stop automatic execution, retain its `operation_id`, and reconcile any resource identifiers already known from prior responses or operator audit. Use a new key only after an operator confirms that repeating the write is safe.
- Deployment or startup failure: report `deployment_id`, `server_id`, `config_applied`, `runtime_started`, and compensation results. Do not claim that the old configuration was restored unless the service explicitly reports successful compensation and a status check confirms it.
- Credential-preservation failure: for `credential_binding_digest_required`, `credential_binding_digest_conflict`, `credential_binding_invalid`, reference conflicts, or slot conflicts, do not retry the overwrite. Read the redacted state again and obtain confirmation again. Never ask the user to put a secret into a tool argument.
- Tool-refresh failure: the previous registry snapshot should remain unchanged. Report `tool_refresh_failed`, confirm that the server still runs, and retry explicitly with a new idempotency key. A classification awaiting review is not a refresh failure.
- Every operator-initiated rollback, stop, or delete requires separate explicit confirmation; compensation already documented as part of a confirmed deploy remains inside that deploy scope.

## Output

For ZIP/Git delivery, the final report must include the source SHA-256, file-list SHA-256, plan fingerprint, `credential_state.binding_digest`, `tool_snapshot_digest`, transfer/upload/build/deployment/server identifiers, classification-change counts, each stage's state, final log cursor, whether any idempotent request was replayed, and verified versus unverified items. When deployment and process startup succeeded but discovery or classification review remains incomplete, use this exact acceptance conclusion: "Deployment and process startup succeeded; delivery acceptance remains incomplete." For external HTTP use the separate output fields below. Never output secrets, base64 chunks, complete stdout/stderr, or internal absolute filesystem paths.

Before running the complete delivery sequence, read [workflow.md](references/workflow.md). When constructing tool calls or handling failures, read [mcp-contract.md](references/mcp-contract.md) for exact fields and stable error codes.

## External HTTP continuation

1. Use an active administrator Console session, a Gate API token, or a separately enabled and explicitly consented built-in `/mcp/manage` OAuth connection with `operations.manage` (plus `tools.invoke` for apply, cancel or a remote probe). Management OAuth must already authorize this exact server ID/create-update action and the selected configuration tool. Ordinary business/external OAuth, delegated read scope or an operator role does not grant configuration authority. Never reconnect as an administrator or enable/provision a management connection automatically.
2. For update, call `gate_mcp_config_status(server_id=...)` and retain the raw-file `config_digest`; do not substitute `gate_server_status`'s canonical manifest digest. Keep masked endpoint/header fields unchanged to preserve their existing bindings. No secret read is needed.
3. Call `gate_mcp_config_plan(mode=create|update,manifest=...,expected_config_digest=... for update)`. Only external + Streamable HTTP is supported. Default `enabled=true`, `auto_start=false`, `connect=false`, `refresh_tools=false`. A connection is a Gate HTTP session, not remote process startup; `auto_start` is separate future Gate-start policy.
4. Use only existing managed credential references. Do not submit secret values, local paths, commands, new personal credential slots or permission changes. Private HTTP requires its existing separate administrator trust entry; the plan cannot create trust.
5. Default precheck contacts no network. Only a specifically authorized probe uses `probe=true,probe_confirmed=true`; it has a bounded request deadline, closes its temporary session, and does not alter the registry.
6. Show target/mode, caller-known endpoint (service responses mask it), manifest and plan digests, prior config digest, expiry, timeout, future startup policy, and exact `connect`/`refresh_tools` choices. Update replaces the current Gate connection. Refresh requires connect and does not publish classifications or grants.
7. Apply within five minutes using the same management connection, exact `plan_id`, `plan_digest`, action flags, fresh idempotency key and `confirmed=true`. Do not expand an existing authorization. A plan is single use; identical retry keeps its exact inputs/key.
8. Poll `gate_mcp_config_status(operation_id=...)` until `terminal=true`. Retain `config_applied`, `config_digest`, `connection_state`, `discovery_state`, error/reconciliation and cleanup states. A queued request or a saved configuration does not prove connection/discovery success.
9. On failure, keep the saved configuration. Read target status and prepare an explicit update with its current digest; never retry a create to repair a failed connect. Cancel requires its own authorized scope and `confirmed=true`; poll the target operation. Cancellation/failure closes only this attempt's Gate session, never a remote process or successor connection.
10. `interrupted`, unknown cleanup or superseded ownership requires operator reconciliation. Never replay an uncertain operation, reconnect, delete, or overwrite automatically. Tool review/publication retains its independent confirmation.

For management OAuth, retain one verified issuer/resource/client/grant/family connection and current exact-target policy. A business connection is never upgraded. Missing scope, tool or target authority stops the workflow; do not change credentials, trust or consent to work around it. The owner may separately confirm target changes in the private Console; those keep JWT/family scope ceilings and invalidate existing plans, so obtain and review a new plan before applying. Actual client management-scope requests remain unverified. See [management contract](../../../docs/oauth-external-management-design.md).

管理 OAuth 必须是已明确启用并独立同意的 `/mcp/manage` 连接，持有当前精确目标/创建更新操作及工具权限；不升级业务连接。缺少 scope、工具或目标时停止，不自动换管理员、生成凭据、修改信任或扩大同意。本人可另在私有 Console 确认目标变更，但 JWT/令牌族 scope 保持，旧计划失效；应用前须重新取得并核对计划。真实客户端管理 scope 请求仍未联调。

Report `plan_id`, plan/manifest/config digests, `operation_id`, `server_id`, current `instance_id` (currently the same 1:1 target), persistence/connection/discovery/cleanup states, tool snapshot and review counts when present, idempotent replay, and remaining acceptance gaps. Do not invent build/deploy IDs, remote process state, discovery from target status, or effective tool access. Lock/HTTP deadlines are cooperative; OS DNS and SQLite contention retain existing lower-level limits.

## Git source continuation

For an explicitly requested Git source, use `gate_project_git_plan` first. Only HTTPS is supported; inspect the exact full commit, host policy, network revisions, digest and deadlines. `safe_executor_unavailable` or `runtime_role_execution_blocked` stops execution; never use host Git/Core privilege or HTTP proxy variables as an SSH substitute. `gate_project_git_import` requires a separate source-acquisition confirmation and idempotency key. Poll/cancel the existing import ID; do not re-resolve a moving ref or replay an uncertain write. The resulting owned upload continues through the same preflight/BuildPlan/build/deploy/start workflow and independent confirmations. Review source inventory/digests before install/build; source scanning remains heuristic.

Node manager selection is bounded to exact npm 9–11, pnpm 8–11 and Yarn Classic 1.22 versions with compatible locks; pnpm 11 additionally requires actual Node >=22.13. Yarn Berry/pnpm 12 have no fallback. Multiple locks with a unique declaration/explicit override are preserved with a warning; genuine conflicts return `recommended_choices`. Save a chosen `package_manager_override` in the actor's revisioned delivery draft and pass it unchanged in plan/create. `node-toolchain` verifies/prepares the exact official distribution in an executor-owned version/integrity cache before frozen installs, with the selected install proxy/registry, no tool lifecycle/global configuration or unplanned Corepack/pnpm/Yarn/Node download. Show this stage and project/dependency lifecycle execution in build confirmation. Build-cache tools and networking are not automatically forwarded to runtime MCP; confirm runtime prerequisites before start.
