---
name: lingshu-gate-upload-build-start
description: Deliver trusted MCP projects through Lingshu Gate with auditable packaging, upload, build, deployment, startup, credential preservation, and tool-classification review. Use when a user asks to upload, build, deploy, start, overwrite, or refresh an MCP project through Lingshu Gate. Require explicit confirmation immediately before each remote mutation or code-execution scope.
---

# Lingshu Gate project delivery

Orchestrate delivery with Lingshu Gate's atomic MCP tools. Automation does not bypass confirmation. It provides deterministic packaging, resumable chunk uploads, idempotent retries, polling, and bounded failure handling.

## Mandatory boundaries

- Process only the project root that the user explicitly selected and trusts.
- Never upload tokens, `.env` files, private keys, credential files, or unreviewed build artifacts. The script's content scan is only a heuristic gate; it cannot prove that unknown or obfuscated secrets are absent. A human must review the complete `included_files` list before upload.
- Build only from the install and build steps returned by `gate_build_plan`; return those plan inputs unchanged to `gate_build_create`.
- Upload, build, deployment, overwrite, startup, cancellation, and session abandonment are distinct write scopes. Show a summary and obtain explicit confirmation immediately before each applicable write. A deploy call may include overwrite, startup, and refresh only when that exact combined scope was shown and confirmed; a later standalone start or refresh requires a new confirmation.
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

1. Call `gate_build_preflight`. If its status is not `ok`, report the checks and next action; do not create a build.
2. Call `gate_build_plan`, defaulting to `run_install=true` and `run_build=true`.
3. Show the exact runtime, `project_root`, steps and commands, dependency-install behavior, timeouts, `source_sha256`, and `plan_fingerprint`.
4. State explicitly that the build executes code from the uploaded bundle and that dependency installation may access the network.

After build confirmation, call `gate_build_create`. Return the plan inputs unchanged: `upload_id`, `runtime_override`, `project_root`, `run_install`, `run_build`, `source_sha256`, and `plan_fingerprint`. Also provide a bounded timeout, a new idempotency key, and `confirmed=true`. Any drift in the plan inputs causes a fingerprint conflict.

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
- Blocked preflight or plan: do not create a build.
- Build failure: preserve the `build_id` and incremental logs; do not retry automatically. After fixing the source, create a new ZIP, digest, and plan.
- Idempotency conflict: a key cannot bind different parameters. Generate a new key and repeat the applicable confirmation.
- `operation_interrupted`: completion of the original idempotent operation is unknown. Stop automatic execution, retain its `operation_id`, and reconcile any resource identifiers already known from prior responses or operator audit. Use a new key only after an operator confirms that repeating the write is safe.
- Deployment or startup failure: report `deployment_id`, `server_id`, `config_applied`, `runtime_started`, and compensation results. Do not claim that the old configuration was restored unless the service explicitly reports successful compensation and a status check confirms it.
- Credential-preservation failure: for `credential_binding_digest_required`, `credential_binding_digest_conflict`, `credential_binding_invalid`, reference conflicts, or slot conflicts, do not retry the overwrite. Read the redacted state again and obtain confirmation again. Never ask the user to put a secret into a tool argument.
- Tool-refresh failure: the previous registry snapshot should remain unchanged. Report `tool_refresh_failed`, confirm that the server still runs, and retry explicitly with a new idempotency key. A classification awaiting review is not a refresh failure.
- Every operator-initiated rollback, stop, or delete requires separate explicit confirmation; compensation already documented as part of a confirmed deploy remains inside that deploy scope.

## Output

The final report must include the source SHA-256, file-list SHA-256, plan fingerprint, `credential_state.binding_digest`, `tool_snapshot_digest`, transfer/upload/build/deployment/server identifiers, classification-change counts, each stage's state, final log cursor, whether any idempotent request was replayed, and verified versus unverified items. When deployment and process startup succeeded but discovery or classification review remains incomplete, use this exact acceptance conclusion: "Deployment and process startup succeeded; delivery acceptance remains incomplete." Never output secrets, base64 chunks, complete stdout/stderr, or internal absolute filesystem paths.

Before running the complete delivery sequence, read [workflow.md](references/workflow.md). When constructing tool calls or handling failures, read [mcp-contract.md](references/mcp-contract.md) for exact fields and stable error codes.
