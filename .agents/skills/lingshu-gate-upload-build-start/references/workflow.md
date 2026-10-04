# Automated delivery workflow

## Source routing

Choose one source first: local trusted project → ZIP; explicit HTTPS repository → Git plan/import then the same owned upload; existing external HTTP MCP → external configuration plan/apply. External configuration does not enter packaging, build, deploy or remote-process start. Read the external contract below and use the exact currently authorized target/actions.

## Stages and confirmation points

| Stage | Read-only input | Write operation | Required summary | Stop condition |
|---|---|---|---|---|
| Local packaging | Stable project root and exclusions | Temporary snapshot and local ZIP | Included files, manifest digest, sizes, ZIP SHA-256, and entry markers | Limit exceeded, sensitive path or content, link, or untrusted source |
| Upload | ZIP digest | Begin, chunk, and commit | Target Lingshu Gate instance, ZIP digest, and total size | Digest, size, or offset conflict |
| Plan | `upload_id` | None | 所选运行时、`project_root`、准确命令和计划指纹 | 预检错误、相关阻断项或无效计划；其他运行时工具缺失仅作提示 |
| Build | Confirmed plan | `build_create` | `steps=[]` 时仅 `copy_tree` 制品封装；存在命令时说明代码执行、依赖安装、网络和超时影响 | Terminal state other than success |
| Deploy | Successful build and redacted credential state | `deploy_build` | `server_id`, overwrite choice, prior configuration digest, credential-binding digest, and the exact combined startup/refresh scope | Source, plan, configuration, or credential digest conflict |
| Verify startup | Configuration digest | `server_start` | `server_id`, configuration digest, and automatic-refresh choice | State other than running, failed health, or failed tool refresh |
| Refresh tools | Running server and configuration digest | `server_refresh_tools` | Tool snapshot and classification-change counts | Untrusted definition, digest conflict, or unexpected permission expansion |

Use a separate `idempotency_key` for every write operation. A retry of the same operation must preserve both the inputs and the key. When inputs change, create a new key and repeat confirmation if the stage requires `confirmed`. The `begin` call establishes the upload confirmation boundary; subsequent `chunk` and `commit` calls do not accept `confirmed`. A deploy call may include overwrite, startup, and refresh only when the operator confirmed that exact combined scope; a later standalone start or refresh has its own confirmation.

用户已明确一次授权覆盖同一来源、目标 Server 与列明的上传、制品生成、覆盖、启动和刷新操作时，各写入工具仍分别传入 `confirmed=true`，后续阶段不重复询问。若计划出现授权外的安装或构建命令、摘要冲突、凭据变更或新工具分类发布，应在该新增范围执行前另行确认；新增工具分类仍需人工核对读写权限。

Run local packaging with PowerShell 7 or later while the project tree is stable. The script first performs a fail-closed path scan across the complete tree, then scans included files for high-confidence secret content and copies them into a system-temporary snapshot. It rejects control characters or ambiguous ZIP paths, `.env*`, `.netrc`, `.git-credentials`, `id_rsa`, `id_ed25519`, `settings.xml`, `gradle.properties`, `.docker/config.json`, credential directories, certificate or key extensions, and high-confidence token content. Any match stops the run and removes temporary output. The content scan is heuristic; a human must review the complete `included_files` list. Never bypass a rejection by excluding the matched content and continuing.

## Suggested idempotency keys

Use traceable values that contain no secrets, for example:

```text
delivery-20260812-upload-begin-a1b2c3d4
delivery-20260812-chunk-00000000-a1b2c3d4
delivery-20260812-build-a1b2c3d4
delivery-20260812-deploy-a1b2c3d4
delivery-20260812-refresh-tools-a1b2c3d4
```

Never reuse a key from an older project, source digest, or plan.

## Polling

- Wait one second before the first build-status request, then follow the returned `poll_after_ms`.
- Pass each `next_sequence` as the next request's `after_sequence`.
- When `has_more=true`, fetch the next page immediately so logs are not lost.
- Stop build polling only when `terminal=true`.
- After an MCP transport timeout, resume status checks with the saved resource identifier; do not create the resource again.
- `operation_interrupted` means completion of the original idempotent operation is unknown. Do not replay with a new key automatically. Retain `operation_id`, reconcile any already-known resource identifier or operator audit state, and require a human decision.

## Startup completion criteria

Completion requires all of the following:

1. Deployment is successful.
2. Server `status=running`.
3. `desired_state=running`.
4. Health is not failed.
5. MCP initialization and tool discovery succeed for the target.
6. Classification reconciliation returns `effective_permissions_expanded=false` and `counts.needs_review=0`; retired tools remain inactive.

If the process is running but item 5 or 6 is not verified, use this acceptance conclusion: "The server process is running; delivery acceptance is partially complete." Do not claim that startup or automated delivery is complete.

## Confirmed tool preparation and Git acquisition

A requested HTTPS Git source is resolved/planned before a separate confirmed acquisition. The imported snapshot joins the existing owned upload and keeps install/build/deploy/start/cancel boundaries. Missing dependency tools may proceed only through the exact-version preparation step shown in the confirmed plan and a reviewed isolated executor. This explicit step includes official source/integrity, selected install egress, deadline and executor cache scope. An unavailable adapter, unsupported manager/lock or incompatible Node version stops work; no host bootstrap or silent replacement is allowed. Project overrides remain actor-owned revisioned drafts, not global configuration.

## Confirmed external HTTP configuration

Read target status for update → offline plan → review normalized manifest/actions/digests/expiry → confirmed apply → poll operation → inspect target. A remote probe is separately explicit; save-only performs no HTTP contact. Connection/discovery is separately selected in the bound plan, never remote process startup. `enabled` and future `auto_start` are independent. Refresh quarantines classifications without publishing or adding grants.

Same-request retry preserves the idempotency key; a single-use plan cannot create two configurations. Plans bind actor, current Console session or API token, target, prior raw-file digest, credentials and action choices. Current permissions/credentials/trust are rechecked during application. Saved-but-disconnected targets need a reviewed update plan, not a duplicate create. Cancellation retains saved configuration and cleans only this attempt's Gate connection. Unknown completion/cleanup or a successor connection requires reconciliation, with no automatic replay or stop.
