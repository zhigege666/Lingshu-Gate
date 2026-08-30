# Automated delivery workflow

## Stages and confirmation points

| Stage | Read-only input | Write operation | Required summary | Stop condition |
|---|---|---|---|---|
| Local packaging | Stable project root and exclusions | Temporary snapshot and local ZIP | Included files, manifest digest, sizes, ZIP SHA-256, and entry markers | Limit exceeded, sensitive path or content, link, or untrusted source |
| Upload | ZIP digest | Begin, chunk, and commit | Target Lingshu Gate instance, ZIP digest, and total size | Digest, size, or offset conflict |
| Plan | `upload_id` | None | Runtime, `project_root`, exact commands, and plan fingerprint | Preflight or validation blocks |
| Build | Confirmed plan | `build_create` | Code execution, dependency installation, network, and timeout impact | Terminal state other than success |
| Deploy | Successful build and redacted credential state | `deploy_build` | `server_id`, overwrite choice, prior configuration digest, credential-binding digest, and the exact combined startup/refresh scope | Source, plan, configuration, or credential digest conflict |
| Verify startup | Configuration digest | `server_start` | `server_id`, configuration digest, and automatic-refresh choice | State other than running, failed health, or failed tool refresh |
| Refresh tools | Running server and configuration digest | `server_refresh_tools` | Tool snapshot and classification-change counts | Untrusted definition, digest conflict, or unexpected permission expansion |

Use a separate `idempotency_key` for every write operation. A retry of the same operation must preserve both the inputs and the key. When inputs change, create a new key and repeat confirmation if the stage requires `confirmed`. The `begin` call establishes the upload confirmation boundary; subsequent `chunk` and `commit` calls do not accept `confirmed`. A deploy call may include overwrite, startup, and refresh only when the operator confirmed that exact combined scope; a later standalone start or refresh has its own confirmation.

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
