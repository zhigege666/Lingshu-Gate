# Git/network integration notes

Functional execution remains incomplete; see [adapter and infrastructure scope decision](git-executor-decision.md). The current patch is the control/UI/plan implementation plus the proposed execution contract, not a working Git/install delivery feature.

Review fixes add persisted coordinator restart interruption/capacity release, a corrected nine-column Git import insert, live profile-reference cleanup, and exact tool pins consumed by the existing local stdio/managed HTTP clients and manifest preflight. Additional shared integration points: `mcp_manifest.py`, `mcp_manifest_validation.py`, `mcp_stdio_client.py`, `mcp_managed_http_client.py`, plus source/build deletion transactions. No auth/session code or new worker/remote runtime was changed. The build-worker decision remains pending and does not include a remote MCP runtime/bridge/deployment system.

The follow-up execution-boundary repair removes version probes from both read-only manifest validation routes. `config.py` adds an immutable service-owned administrator tool registry; pinned startup uses registered Node/JS CLI paths, never project commands/PATH. Validation inspects metadata only and marks versions unverified. Merge this new Settings field/environment parsing deliberately; no schema or auth/session migration is added by the repair.

[简体中文](zh-CN/git-network-integration.md)

Base: `362fffccfbc28a362f7f3431759319128cdbabd1` (main). Branch: `feat/git-import-network-settings`. No commits, push, PR, deployment or real credentials.

Shared integration points to merge deliberately with the independent built-in OAuth work:

- `database.py`: registers a uniquely named additive Git/network migration. Merge both migration registrations; do not replace either schema.
- `access_control.py`: adds independent settings-management and network-invocation permission codes. Preserve OAuth permissions.
- `main.py`: composes settings/import services and their routes/tools; no external authentication module edits.
- Console route catalog, navigation translations and `App.tsx`: add System settings; preserve OAuth settings tabs/routes when integrating.
- `build_deploy.py`, `build_preflight.py`, `build_plan.py`, `project_delivery_mcp.py`: extend existing delivery provenance/plans. Preserve confirmation, ownership, digest, idempotency, token and classification checks.

The production safe executor is absent. This is an explicit release blocker for real Git/network execution, not a reason to loosen local/Core execution. Tests are supplied but not run in this static-only task. The final evidence record will enumerate static checks and remaining acceptance gaps.

Additional shared files: `application/delivery_drafts.py` and the Console delivery draft/components add a revisioned package-manager override; the bundled Delivery Skill contract describes the same confirmed preparation stage and Git continuation. Preserve OAuth additions when merging `SECURITY*`, README/docs navigation and paired release documentation. Production composition still injects no network executor.

The independent OAuth review is changing session purpose checks and interaction capacity, with further changes to `auth.py` and session migrations. This branch does not edit `auth.py`, `external_auth.py`, or OAuth/session tables. During integration, retain both sets of uniquely named migrations and preserve the revised session/scope checks when composing these routes. Review `main.py`, `database.py`, `access_control.py`, and navigation together against the final OAuth branch; this worktree has not been merged with it or functionally verified against it.
