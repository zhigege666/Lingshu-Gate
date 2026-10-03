# Git/network integration notes

[简体中文](zh-CN/git-network-integration.md) · [Validation record](release-validation.md)

The 0.4.0 candidate integrates the Git/network branch with main `d500116548a90e4edaa0bfa0e0c1138afe45354a`, including built-in OAuth PR #42. The original Git branch base was `362fffccfbc28a362f7f3431759319128cdbabd1`; PR #43 retains that history through a merge of main, without rewriting the OAuth branch.

**Production Git acquisition, proxy probes, tool preparation and configured network installs remain unavailable.** Production composition supplies no `SafeNetworkExecutor`. This release contains the settings, policy, plan, API/UI and integration contract. Synthetic adapter tests do not supply a production isolation boundary. See [the execution gap](git-executor-decision.md).

Shared integration points retained in the combined tree:

- `database.py` registers `0004_gate_git_network` and `0007_auth_session_purpose`. The independent OAuth store registers `0006_builtin_oauth` and `0008_oauth_interaction_capacity`. Keep both registration paths and all uniquely named migrations.
- `main.py`, `access_control.py`, Console routing, navigation and translations compose both features. Settings administration, network invocation and existing delivery permissions remain separate; built-in and external OAuth retain their own guarded tabs and session purposes.
- `build_deploy.py`, `build_preflight.py`, `build_plan.py`, `project_delivery_mcp.py`, `application/delivery_drafts.py` and the Delivery Skill extend the existing upload/build/deploy/start chain. Ownership, confirmation, digest, idempotency, token and classification checks remain required.
- `config.py`, `mcp_manifest.py`, `mcp_manifest_validation.py`, `mcp_stdio_client.py` and `mcp_managed_http_client.py` share the reviewed administrator tool registry and exact manager pins. Read-only validation inspects metadata without executing programs; only authorized native startup performs bounded probes. Core does neither.
- Source/build deletion transactions, README/documentation indexes and `SECURITY*` retain both features' boundaries. Docker Core remains unprivileged and has no engine socket.

Git review fixes preserve the explicitly selected project root through reanalysis, audit successful plan creation without recording source URLs or proxy values, sweep at most 100 expired unused plans per pass and limit unused plans to 32 per actor / 256 globally. Any referenced import retains its plan provenance, including failed or cancelled imports. Restart interruption and capacity release do not claim termination of an absent executor.

Integration tests cover the real HTTP audit path, nested snapshots, manager/lockfile validation, redaction, permissions, cancellation/timeouts, reference/version retention, and failure without replacing the old deployment. OAuth string secrets remain redacted while JSON-RPC reserved negative integer error codes remain intact. Browser regressions cover explicit external-mode navigation and loading a historical build's project before deployment confirmation. Executed results and remaining real-network acceptance gaps are recorded separately in the [validation record](release-validation.md).

No production deployment, user Git/proxy connection, SSH operation, external account setup or real credential provisioning is part of this release preparation. Implementing and independently reviewing an isolated worker remains a separate infrastructure decision; no local fallback or remote MCP bridge was added.
