# Project delivery

[简体中文](zh-CN/project-delivery.md) · [Documentation index](README.md)

Project Delivery moves one explicitly trusted MCP project through deterministic packaging, resumable upload, preflight, build planning, build execution, deployment, startup, and tool-classification reconciliation.

It is an execution workflow, not an untrusted-code sandbox. Use a native Gate deployment under a dedicated operating-system account. Docker Core intentionally rejects local build execution and managed stdio startup.

## Safety model

- The operator selects and trusts the exact project root.
- The complete included-file list is reviewed before upload.
- Upload, build, deployment, overwrite, startup, cancellation, and abandonment have explicit confirmation boundaries.
- Every write has an idempotency key. A retry reuses a key only when all inputs are identical.
- SHA-256 digests bind the archive, source, build plan, deployed configuration, credential references, and discovered tool snapshot.
- Build commands come from the reviewed plan. The create operation does not accept arbitrary replacement commands.
- Existing credential references are preserved only when their redacted binding digest matches.
- Tool refresh never expands effective permissions automatically.

## Bundled Delivery Skill

The repository-owned Skill is located at:

```text
.agents/skills/lingshu-gate-upload-build-start/
```

Invoke it as `$lingshu-gate-upload-build-start` after configuring the target Gate instance in an environment that loads repository Skills. Before use, review:

- `SKILL.md` for mandatory boundaries and orchestration behavior;
- `references/workflow.md` for stage transitions and polling;
- `references/mcp-contract.md` for exact inputs, outputs, and stable error codes.

The Skill automates bounded mechanics but cannot supply operator trust or confirmation.

## Deterministic local package

Use PowerShell 7 or later while the project tree is stable:

```powershell
pwsh -File .agents/skills/lingshu-gate-upload-build-start/scripts/New-LingshuGateProjectBundle.ps1 `
  -ProjectRoot /path/to/trusted-project `
  -OutputPath /path/outside/project-root/project.zip
```

The output path must be outside the project root. The script rejects links, sensitive path families, high-confidence secret content, more than 3,000 files, more than 200 MiB of source, or a ZIP larger than 50 MiB. It excludes common version-control, dependency, and build-output directories and creates the archive from a temporary snapshot.

The content scan is heuristic, not proof that a project contains no secrets. Review every `included_files` entry and the reported file-list and ZIP SHA-256 values. Do not bypass a rejection by excluding the flagged secret and continuing.

## Workflow

| Stage | Read or plan | Confirmed write | Evidence retained |
|---|---|---|---|
| Package | Stable source tree and local scan | Local ZIP creation | Included files, sizes, entry markers, file-list digest, ZIP digest |
| Upload | Target, size, ZIP digest | Begin; bounded chunk/commit continuation | `transfer_id`, `upload_id`, `source_sha256` |
| Preflight | Source and runtime inspection | None | Checks and detected project root |
| Plan | Exact install/build steps | None | Commands, timeouts, network impact, `plan_fingerprint` |
| Build | Poll incremental state and logs | Create or cancel | `build_id`, terminal state, final log cursor |
| Deploy | Successful build and target state | New deployment or bound overwrite | `deployment_id`, `config_digest`, redacted credential state |
| Start | Deployed configuration | Start | Observed running and health state |
| Reconcile | Discovered tool definitions | Refresh tools | `tool_snapshot_digest`, change counts, review state |

### 1. Upload

After reviewing the bundle and confirming upload:

1. Call `gate_project_upload_begin` with filename, total bytes, archive SHA-256, a new idempotency key, and `confirmed=true`.
2. Send chunks at the returned `next_offset` through `gate_project_upload_chunk`; bind every chunk to its SHA-256 and a distinct idempotency key.
3. Resume from the server's returned offset after a network interruption.
4. Call `gate_project_upload_commit` only after every byte is accepted.

The begin call establishes confirmation for its bounded upload session. Chunk and commit do not accept `confirmed`. Never print `data_base64` or put the complete archive in one argument.

### 2. Preflight and plan

Call `gate_build_preflight`. Stop if its status is not `ok`. Then call `gate_build_plan` and show the operator:

- resolved runtime and project root;
- exact steps and commands;
- whether dependency installation and network access are involved;
- source SHA-256, timeouts, and plan fingerprint.

After build confirmation, return the plan inputs unchanged to `gate_build_create`, together with the source digest, fingerprint, timeout, new idempotency key, and `confirmed=true`. Input drift causes a conflict instead of silently rebuilding a different plan.

### 3. Build

Poll `gate_build_status` using `after_sequence` and at most 200 log records. Save each returned `next_sequence` and request only incremental logs. An MCP request timeout does not prove build failure; continue querying the existing `build_id`.

Proceed only when the build reaches terminal `success`. Cancellation is a separate confirmed write and remains incomplete until status becomes terminal.

### 4. Deploy and start

Before deployment, show the build, source and plan digests, artifact and manifest summary, target server ID, overwrite choice, current configuration digest, redacted credential-binding digest, missing credential items, startup choice, and tool-refresh choice.

For a new target, deploy with `overwrite=false`. For an overwrite:

1. read `gate_server_status`;
2. bind `expected_previous_config_digest`;
3. when credentials exist, use `credential_policy=preserve_existing` and return `expected_credential_binding_digest` unchanged;
4. stop and request a new review if either digest changes.

Deployment defaults to `start=false`. Immediate startup can be part of the confirmed deploy operation. If startup is separate, obtain a new confirmation and call `gate_server_start` with the exact deployed `config_digest`.

### 5. Reconcile tools

After the process reports running, verify health and discovery. Refresh with `gate_server_refresh_tools` only after confirmation and with the current configuration digest.

Accept the refresh only when `effective_permissions_expanded=false`. New, changed, missing, or reappearing tools remain inactive or `needs_review` until a human reviews and publishes their classifications.

Delivery is complete only when deployment succeeds, the observed state is running, health is not failed, discovery succeeds, and classification reconciliation does not expand access. Otherwise report partial completion precisely.

## Tool contract

| Tool | Kind | Confirmation and digest boundary |
|---|---|---|
| `gate_project_upload_begin` | Write | `confirmed=true`; archive size and SHA-256 |
| `gate_project_upload_chunk` | Write continuation | Transfer, offset, chunk SHA-256, idempotency key |
| `gate_project_upload_commit` | Write continuation | Complete confirmed transfer and source SHA-256 |
| `gate_project_upload_abort` | Destructive write | Separate `confirmed=true` |
| `gate_build_preflight` | Read | Upload, runtime override, project root |
| `gate_build_plan` | Read | Preflight inputs plus install/build choices |
| `gate_build_create` | Execution write | `confirmed=true`; source digest and plan fingerprint |
| `gate_build_status` | Read | Build ID and incremental log cursor |
| `gate_build_cancel` | Destructive write | Separate `confirmed=true` |
| `gate_deploy_build` | Destructive write | `confirmed=true`; source, plan, prior config, and credential digests |
| `gate_deployment_status` | Read | Deployment ID and compensation state |
| `gate_server_start` | Execution write | `confirmed=true`; expected configuration digest |
| `gate_server_status` | Read | Runtime, health, config digest, redacted credentials |
| `gate_server_refresh_tools` | Execution write | `confirmed=true`; config digest and tool-snapshot result |

The exact JSON Schemas returned by `tools/list` are authoritative for a running version. Unknown fields are rejected.

## Failure recovery

- Chunk offset or digest conflict: resume only from the authoritative next offset; start a new transfer if content differs.
- Blocked preflight or plan: do not create a build.
- Build failure: preserve the build ID and incremental logs; change the source, then create a new archive and plan.
- Idempotency conflict: never bind different inputs to an existing key.
- Interrupted operation with unknown completion: inspect the returned resource state before deciding whether a new write is safe.
- Deployment or startup failure: report whether configuration was applied, runtime started, and compensation was attempted or confirmed.
- Credential digest conflict: read redacted state again and repeat operator review; never request a secret in a tool argument.
- Tool refresh failure: preserve the accepted snapshot and report the running state separately from refresh state.

Rollback, stop, delete, force termination, and retry after uncertain completion all require an explicit operator decision.

## Completion report

Record source and file-list SHA-256 values, plan fingerprint, redacted credential-binding digest, tool-snapshot digest, transfer/upload/build/deployment/server identifiers, classification-change counts, each stage state, final log cursor, idempotent replays, and verified versus unverified acceptance checks. Never include secrets, base64 chunks, complete process output, or internal absolute paths.
