# MCP tool contract quick reference

## Tools

| Tool | Type | Key inputs | Key outputs |
|---|---|---|---|
| `gate_project_upload_begin` | Write | `filename`, `size_bytes`, `sha256`, `idempotency_key`, `confirmed` | `transfer_id`, `chunk_size`, `next_offset` |
| `gate_project_upload_chunk` | Write | `transfer_id`, `offset`, `data_base64`, `chunk_sha256`, `idempotency_key` | `accepted_bytes`, `next_offset`, `complete` |
| `gate_project_upload_commit` | Write | `transfer_id`, `idempotency_key` | `upload.id`, `source_sha256`, `source_size_bytes` |
| `gate_project_upload_abort` | Destructive write | `transfer_id`, `idempotency_key`, `confirmed` | `status=aborted`, `transfer_id` |
| `gate_build_preflight` | Read | `upload_id`, `runtime_override?`, `project_root?`, `refresh?` | `status`, `checks`, `tools` |
| `gate_build_plan` | Read | Preflight fields, `run_install`, `run_build` | `plan`, `validation`, `plan_fingerprint` |
| `gate_build_create` | Execution write | `upload_id`, `runtime_override?`, `project_root?`, `run_install`, `run_build`, `timeout_seconds`, `source_sha256`, `plan_fingerprint`, `idempotency_key`, `confirmed` | `build_id`, `status`, `poll_after_ms` |
| `gate_build_status` | Read | `build_id`, `after_sequence`, `log_limit` | `terminal`, `logs`, `next_sequence` |
| `gate_build_cancel` | Destructive write | `build_id`, `idempotency_key`, `confirmed` | `status`, `build_id`, `terminal`, `poll_after_ms` |
| `gate_deploy_build` | Destructive write | `build_id`, `source_sha256`, `plan_fingerprint`, `server_id?`, `overwrite`, `start`, `expected_previous_config_digest?`, `credential_policy`, `expected_credential_binding_digest?`, `refresh_tools`, `idempotency_key`, `confirmed` | `deployment_id`, `config_digest`, `credential_state`, `tool_refresh`, `server` |
| `gate_deployment_status` | Read | `deployment_id` | Deployment, configuration-application, runtime, and compensation state |
| `gate_server_start` | Execution write | `server_id`, `expected_config_digest`, `refresh_tools`, `idempotency_key`, `confirmed` | Running state and `tool_refresh` |
| `gate_server_status` | Read | `server_id` | Desired state, runtime, health, `tool_count`, `config_digest`, and redacted `credential_state` |
| `gate_server_refresh_tools` | Execution write | `server_id`, `expected_config_digest`, `idempotency_key`, `confirmed` | `status`, `tool_snapshot_digest`, `counts`, `effective_permissions_expanded` |

The upload confirmation boundary starts with `gate_project_upload_begin(confirmed=true)`. `chunk` and `commit` continue the confirmed caller-owned session and do not accept `confirmed`. Other execution, cancellation, abandonment, deployment, or startup writes require `confirmed=true` when their schema specifies it.

When creating a build, `runtime_override`, `project_root`, `run_install`, and `run_build` must exactly match the plan request that produced `plan_fingerprint`. Returning only the source digest and fingerprint is insufficient.

Normal build and deployment failure summaries use `failure_message`. A top-level `error` is always a structured business error containing `code`, `message`, `retryable`, `next_action`, and `details`. Deployment status also returns `config_applied`, `runtime_started`, `rollback_attempted`, `rollback_succeeded`, and `rollback_error`; `rollback_succeeded=null` means that the outcome is unknown. `gate_server_status` reports runtime, configuration, and redacted credential state, but it does not return `tool_refresh`; retain that value from deploy/start or call the separately confirmed refresh tool.

Every write also requires the caller to have `tools.invoke`, `operations.manage`, and a token scope that permits writes. A non-admin caller must additionally satisfy published-tool classification, delivery-tool grants, and object-owner or target-server grants. An admin may bypass classification and resource grants, but cannot bypass explicit control permissions or token scope. Annotations are client hints, not a substitute for server-side authorization.

## Common stable error codes

- Upload: `invalid_archive_name`, `invalid_chunk_encoding`, `invalid_chunk_size`, `chunk_digest_mismatch`, `chunk_out_of_order`, `chunk_offset_conflict`, `upload_size_exceeded`, `upload_incomplete`, `digest_mismatch`, `invalid_archive`, `upload_not_found`, `upload_transfer_not_found`, `upload_transfer_expired`, `upload_transfer_not_open`, `upload_transfer_state_conflict`, `upload_staging_inconsistent`, `upload_already_committed`, `upload_commit_in_progress`, `upload_commit_recovery_conflict`.
- Source and plan: `upload_provenance_missing`, `preflight_failed`, `build_plan_blocked`, `source_digest_conflict`, `plan_fingerprint_conflict`.
- Build: `build_not_found`, `build_not_ready`, `build_create_failed`, `build_not_cancellable`.
- Deployment: `build_not_ready`, `invalid_server_id`, `server_conflict`, `previous_config_digest_required`, `previous_config_digest_conflict`, `previous_config_missing`, `deployment_not_found`, `deploy_failed`.
- Credentials: `credential_binding_digest_required`, `credential_binding_digest_conflict`, `credential_binding_missing`, `credential_binding_invalid`, `credential_reference_conflict`, `credential_slot_conflict`, `existing_credentials_not_allowed`, `candidate_credentials_not_allowed`.
- Startup and refresh: `server_config_not_found`, `config_digest_conflict`, `runtime_manifest_digest_conflict`, `server_not_loaded`, `server_not_found`, `server_start_failed`, `tool_refresh_failed`.
- Authorization and ownership: `delivery_resource_not_found_or_forbidden`, `target_server_not_found_or_forbidden`.
- General: `invalid_arguments`, `idempotency_conflict`, `operation_in_progress`, `operation_interrupted`, `operation_completion_conflict`, `internal_error`.

`operation_interrupted` means that the original operation's completion state is unknown and the request must not be replayed automatically. Retain its `operation_id`, reconcile any already-known resource identifiers or operator audit state, and require an operator decision before a new key is used. `upload_transfer_state_conflict` and `upload_commit_recovery_conflict` likewise require state reconciliation instead of a blind restart. These are the common codes the Skill needs to route; they are not an exhaustive list of dynamic preflight failures.

Errors use an MCP tool result with `isError=true` and `structuredContent.error`, containing `code`, `message`, `retryable`, `next_action`, and `details`. Do not interpret a business failure as a JSON-RPC protocol error.
