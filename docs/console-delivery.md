# Console delivery API

These endpoints require `operations.manage`. Ordinary tool grants do not grant deployment access. All examples use synthetic local projects. No tunnel, OAuth registration, external authorization, or production deployment is performed by these APIs' tests.

## Final configuration and confirmation

`POST /v1/builds/{build_id}/deploy/preview` accepts the deployment request: `server_id`, `start` (default false), `overwrite` (default false), `manifest_patch`, and `credential_policy` (`preserve_existing` by default, or `require_none`). The patch recursively merges into the successful build's manifest. Send only user changes relative to the generated manifest; a full upload manifest could otherwise discard build-generated settings. Artifact `launch.type`, `launch.command`, and `launch.cwd` cannot be replaced through the deployment patch. Arrays replace the corresponding array in full; `null` removes an object field. Credential preservation may retain managed references despite a patch deletion.

Preview returns the redacted final `manifest`, `changed_fields`, `config_digest`, `expected_previous_config_digest`, `expected_credential_binding_digest`, `credential_state`, and `interrupts_existing_service`. Preview performs static checks, not a downstream connection probe. It does not write a deployment or configuration.

After confirmation, call `POST /v1/builds/{build_id}/deploy` with the original patch and preview's two `expected_*` fields; also send `expected_config_digest=preview.config_digest`. The candidate digest is mandatory for deployment; clients must preview before submitting. Existing targets always require the correct previous configuration digest. Credential preservation requires the verified binding digest. Conflicts return HTTP 409 and require a new preview and confirmation. Never submit preview's masked manifest as the patch: masked patch values are rejected before digest calculation.

The final merged manifest is saved once, before runtime application. Managed credential references and user slot declarations use the existing delivery preservation checks; raw secret values are not copied from a masked response. Deployment history stores a redacted manifest and encrypted prior snapshot. Configuration writes and the digest check share a single-Core mutation lock. Files, runtime, and SQLite are not one transaction. Deployment failures report the observed compensation status; `rollback_succeeded=null` means unknown, not success.

`start=false` applies a stopped runtime, even when replacing a running service. `start=true` must reach `running` before deployment is successful. This is replacement with an interruption, not hot reload. Manual rollback is available only when `rollback_available=true`; it is never promised to restore automatically. A rollback's protected snapshot must validate and match the target.

## Resumable private drafts

`GET /v1/delivery-drafts/{upload_id}` returns the current operator's draft, or empty defaults with `revision=0`. `PUT` replaces it using `expected_revision` and the fields `manifest_patch`, `server_id`, `build_id`, `deployment_id`, `overwrite`, `start`, `project_root`, and `runtime_override`. The returned revision increments by one. Stale revisions return HTTP 409. Builds must belong to the upload; deployments must belong to the supplied build.

Drafts are encrypted independently of service manifests and isolated by operator plus upload. Saving a draft does not change service configuration or runtime. Known sensitive environment/header names require `${credential:id}` references; masked values and `user_credential_values` are rejected. Ordinary environment settings are retained. Name-based rejection cannot identify every possible secret, so the whole draft is encrypted at rest and never included in audit payloads. Deleted uploads make their drafts inaccessible; encrypted draft retention follows local data-directory retention.

## Verification

Run the focused contract checks with:

```bash
uv run pytest -q tests/test_real_delivery_journey.py tests/test_console_deployment_api.py tests/test_delivery_drafts.py tests/test_build_deploy_reliability.py tests/test_project_delivery_mcp.py tests/test_mcp_configuration_service.py tests/test_mcp_config_atomicity.py tests/test_build_request_boundary.py tests/test_build_execution_boundary.py
```

`D01` packages a standard-library-only Python MCP service, performs real upload/build/draft/preview/deploy with startup, advertises protocol `2026-07-28`, discovers one tool, and invokes it through the real stdio process. Saving with `apply=true,start=true` must return a changed configuration marker and a different process ID. Additional temporary backend tests exercise failed manual rollback and require disk/runtime consistency after compensation. Fault-injection tests separately cover failures which are difficult to produce deterministically. None of these scenarios accepts an external OAuth identity or contacts a public service.

`D02` builds and starts artifact v1, executes a dependency-free local Node build script that deliberately exits 7, and verifies the original service is still running with the identical PID, marker, artifact path and disk configuration. It then builds a second Python artifact, previews and confirms replacement, observes v2 from the new process while retaining the selected runtime setting, and explicitly rolls back to v1 using the valid protected snapshot. Both Python artifacts use current-protocol real stdio; the failing build performs no install or network operation.
