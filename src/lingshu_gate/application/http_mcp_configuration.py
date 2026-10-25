"""HTTP management policy layered on the existing external operation engine."""

from __future__ import annotations

import re
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from lingshu_gate.application.external_mcp_configuration import (
    ExternalConfigPlanInput, _control_lock, _digest, _error, _json, _now,
)
from lingshu_gate.domain.http_mcp_management import HttpMcpPlanInput
from lingshu_gate.endpoint_security import private_http_origin
from lingshu_gate.mcp_config_store import McpConfigConflict
from lingshu_gate.mcp_http_trust import McpHttpTrustConflict, McpHttpTrustUpdate
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.project_delivery_mcp import _parse_input
from lingshu_gate.registry import ToolInvocationContext

if TYPE_CHECKING:
    from lingshu_gate.application.external_mcp_configuration import ExternalMcpConfigurationService


def _unreconciled_deletion(service: ExternalMcpConfigurationService, server_id: str) -> bool:
    row = service.database.query_one(
        "SELECT p.plan_json,e.result_json,e.status FROM external_mcp_config_operations e "
        "JOIN external_mcp_config_plans p ON p.id=e.plan_id "
        "WHERE json_extract(p.plan_json,'$.server_id')=? AND json_extract(p.plan_json,'$.management_contract')='http_v1' "
        "AND (e.status='success' OR json_extract(e.result_json,'$.requires_reconciliation')=1) ORDER BY e.rowid DESC LIMIT 1",
        (server_id,))
    return bool(row and row["status"] != "success" and json.loads(row["plan_json"])["mode"] == "delete")


def plan_http_configuration(service: ExternalMcpConfigurationService, arguments: dict[str, Any],
                            context: ToolInvocationContext) -> dict[str, Any]:
    body = _parse_input(HttpMcpPlanInput, arguments)
    target = body.manifest.get("id") if body.manifest is not None else body.server_id
    if not isinstance(target, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", target) is None:
        raise _error("external_config_invalid", "An exact server ID is required.")
    service._authorize(context, tool_id="gate_http_mcp_plan", target_id=target, action=body.mode)
    trust = service.configs.http_trust_store
    if trust is None:
        raise _error("http_management_unavailable", "HTTP management policy storage is unavailable.")
    with _control_lock(service.configs.mutation_lock):
        if body.mode in {"create", "update"}:
            assert body.manifest is not None
            manifest = service._normalize(ExternalConfigPlanInput(mode=body.mode, manifest=body.manifest,
                expected_config_digest=body.expected_config_digest, connect=body.connect,
                refresh_tools=body.refresh_tools, timeout_seconds=body.timeout_seconds), managed_http=True)
        else:
            try:
                manifest = service.configs.load_manifest(target)
            except (KeyError, ValueError):
                raise _error("external_config_target_unavailable", "The saved external configuration is unavailable.") from None
            if manifest.launch.type != "external" or manifest.transport.type != "streamable_http":
                raise _error("external_config_invalid", "This operation only manages an existing external HTTP configuration.")
        actual = service._config_digest(manifest.id)
        if (body.mode == "create" and actual is not None) or (body.mode != "create" and actual != body.expected_config_digest):
            raise _error("config_digest_conflict", "The saved configuration changed; read its current digest and plan again.")
        if body.connect and not manifest.enabled:
            raise _error("external_config_invalid", "An explicitly requested connection requires enabled=true.")
        previous = service.configs.load_manifest(target) if actual is not None else None
        if body.mode in {"revoke_trust", "restore_trust"} and not private_http_origin(manifest.transport.endpoint or ""):
            raise _error("http_trust_not_applicable", "This service does not use a private clear-text HTTP origin.")
        trust_plan = trust.plan_configuration(target, manifest.transport.endpoint,
            action="restore" if body.mode == "restore_trust" else "auto",
            previous_endpoint=previous.transport.endpoint if previous else None, creating=body.mode == "create")
        if body.connect and not trust_plan["connection_allowed"]:
            raise _error("http_trust_revoked", "Connection permission was revoked; use an explicit restore_trust plan.")
        if body.mode in {"create", "update"}:
            validation = validate_mcp_manifest(service.settings, service.configs,
                manifest.model_dump(mode="json", exclude={"manifest_path"}),
                expected_id=target if body.mode == "update" else None, http_trust_plan=trust_plan)
            checks = [{"name": item["name"], "severity": item["severity"], "message": item["message"]} for item in validation["checks"]]
            if not validation["ok"]:
                return {"status": "blocked", "validation": {"ok": False, "checks": checks}, "network_contacted": False}
        else:
            checks = []
        credential_revisions = service._credential_revisions(manifest) if body.mode not in {"delete", "revoke_trust"} else {}
        if body.mode not in {"delete", "revoke_trust"}:
            service.configuration.validate_http_credentials(manifest)
        impact: dict[str, Any] = {}
        if body.mode == "create" and _unreconciled_deletion(service, target):
            impact["reconcile_prior_delete"] = True
        if body.mode == "delete":
            group_count = service.database.query_one("SELECT COUNT(DISTINCT group_id) AS n FROM mcp_group_members WHERE server_id=?", (target,))
            binding_count = service.database.query_one("SELECT COUNT(*) AS n FROM user_downstream_credentials WHERE server_id=?", (target,))
            assert group_count is not None and binding_count is not None
            impact = {
                "tool_count": sum(item.metadata.get("server_id") == target for item in service.runtime.registry.list_definitions()),
                "group_count": group_count["n"],
                "personal_credential_bindings": binding_count["n"],
                "shared_credentials_deleted": False, "remote_service_uninstalled": False,
            }
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        payload = {"management_contract": "http_v1", "mode": body.mode,
                   "manifest": manifest.model_dump(mode="json", exclude={"manifest_path"}),
                   "manifest_digest": service.runtime._manifest_digest(manifest), "server_id": target,
                   "expected_config_digest": actual, "credential_revisions": credential_revisions,
                   "http_trust_plan": trust_plan, "connect": body.connect, "refresh_tools": body.refresh_tools,
                   "timeout_seconds": body.timeout_seconds, "expires_at": expires}
        if context.auth_type == "oauth":
            payload.update(oauth_connection_digest=service._connection_digest(context), target_revision=context.oauth_target_revision)
        plan_id, digest = uuid4().hex, _digest(payload)
        with service.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            service._authorize(context, tool_id="gate_http_mcp_plan", target_id=target, action=body.mode, connection=connection)
            connection.execute("DELETE FROM external_mcp_config_plans WHERE expires_at<? AND NOT EXISTS "
                               "(SELECT 1 FROM external_mcp_config_operations e WHERE e.plan_id=external_mcp_config_plans.id)", (_now(),))
            count = connection.execute("SELECT COUNT(*) FROM external_mcp_config_plans WHERE actor_id=? AND expires_at>=? AND consumed_by IS NULL",
                                       (context.actor_id, _now())).fetchone()[0]
            if count >= 16:
                raise _error("external_config_plan_limit", "Too many active plans; wait for an earlier plan to expire.")
            connection.execute("INSERT INTO external_mcp_config_plans VALUES(?,?,?,?,?,?,NULL,?)",
                (plan_id, context.actor_id, service._principal_digest(context), digest, _json(payload), expires, _now()))
    return {"status": "ready", "plan_id": plan_id, "plan_digest": digest, "mode": body.mode,
            "server_id": target, "instance_id": target, "expected_config_digest": actual,
            "manifest_digest": payload["manifest_digest"], "expires_at": expires,
            "validation": {"ok": True, "checks": checks}, "network_contacted": False,
            "manifest": {key: value for key, value in manifest.safe_dict().items() if key != "manifest_path"},
            "http_trust": {key: value for key, value in trust_plan.items() if key != "endpoint"},
            "connection_target": manifest.transport.endpoint, "impact": impact,
            "connect": body.connect, "refresh_tools": body.refresh_tools, "timeout_seconds": body.timeout_seconds,
            "remote_process_started": False, "effective_permissions_expanded": False}


def run_http_configuration(service: ExternalMcpConfigurationService, operation_id: str, plan: dict[str, Any],
                           context: ToolInvocationContext, cancel: threading.Event, deadline: float,
                           result: dict[str, Any]) -> None:
    """Called inside the existing worker and target lock; share its finalizer."""
    trust = service.configs.http_trust_store
    if trust is None:
        raise _error("http_management_unavailable", "HTTP policy storage is unavailable.")
    service._check(context, cancel, deadline, plan)
    target = str(plan["server_id"])
    if service._config_digest(target) != plan["expected_config_digest"]:
        raise McpConfigConflict("Configuration changed after planning")
    trust.check_plan(plan["http_trust_plan"])
    manifest = McpServerManifest.model_validate(plan["manifest"])
    mode = plan["mode"]

    def before_mutation() -> None:
        service._check(context, cancel, deadline, plan)
        if service._config_digest(target) != plan["expected_config_digest"]:
            raise McpConfigConflict("Configuration changed after planning")
        trust.check_plan(plan["http_trust_plan"])

    def remove_runtime(check: Any = before_mutation) -> Any:
        return service.runtime.remove_external_configuration(target, cancel=cancel, deadline=deadline, before_remove=check)

    if mode == "delete":
        response, removed = service.configuration.delete(target, remove_runtime=remove_runtime, remove_group_memberships=True)
        del response
        result.update(config_applied=True, config_deleted=True, config_digest=None, http_trust=trust.get(target),
                      removed_personal_credential_bindings=removed, shared_credentials_deleted=False,
                      connection_state="removed", discovery_state="removed", status="success")
        return
    if mode == "revoke_trust":
        before_mutation()
        policy = trust.update(target, McpHttpTrustUpdate(origins=[], expected_revision=plan["http_trust_plan"]["expected_revision"], confirmed=True), actor_id=context.actor_id)
        result.update(trust_applied=True, http_trust=policy, connection_state="revoked", discovery_state="invalidated")
        service._progress(operation_id, result)
        remove_runtime(lambda: service._check(context, cancel, deadline, plan))
        result["status"] = "success"
        return
    service.configuration.validate_http_credentials(manifest)
    remove_runtime()
    if mode == "create" and _unreconciled_deletion(service, target):
        before_mutation()
        # An interrupted deletion may have removed its file before retiring
        # published classifications. A new incarnation must never inherit them.
        service.configuration.cleanup_deleted_metadata(target)
        result["reconciled_prior_delete"] = True
    if mode == "restore_trust":
        before_mutation()
        policy = trust.apply_saved_configuration(plan["http_trust_plan"], actor_id=context.actor_id)
        result.update(trust_applied=True, http_trust=policy, config_digest=service._config_digest(target))
        service.configuration._bind_saved_http_credentials(manifest)
    else:
        request = McpConfigSaveRequest(manifest=plan["manifest"], apply=False, start=False,
                                      expected_config_digest=plan["expected_config_digest"])
        prepared = service.configuration.prepare_user_credentials(request,
            existing_server_id=target if mode == "update" else None, http_trust_plan=plan["http_trust_plan"])
        before_mutation()
        try:
            if mode == "create":
                service.configuration.create(request, user_id=context.actor_id, prepared=prepared, http_trust_plan=plan["http_trust_plan"])
            else:
                service.configuration.update(target, request, user_id=context.actor_id, prepared=prepared, http_trust_plan=plan["http_trust_plan"])
        except Exception:
            # The config file and trust database are not a shared transaction.
            # Report durable file changes even when a later step failed.
            if service._config_digest(target) != plan["expected_config_digest"]:
                result.update(config_applied=True, config_digest=service._config_digest(target), requires_reconciliation=True)
            raise
        policy = trust.get(target)
        result.update(config_applied=True, config_digest=service._config_digest(target), http_trust=policy,
                      trust_applied=policy["revision"] != plan["http_trust_plan"]["expected_revision"])
    service._progress(operation_id, result)
    saved_digest = result["config_digest"]
    expected_policy = trust.get(target)

    def current() -> None:
        service._check(context, cancel, deadline, plan)
        if service._config_digest(target) != saved_digest:
            raise McpConfigConflict("Saved configuration changed during the operation")
        live = trust.get(target)
        if (live["revision"], live["server_binding"], live["state"]) != (
                expected_policy["revision"], expected_policy["server_binding"], expected_policy["state"]):
            raise McpHttpTrustConflict("HTTP permission changed during the operation")
        service.configuration.validate_http_credentials(manifest, allow_pending=False)

    current()
    if not plan["http_trust_plan"]["connection_allowed"]:
        result.update(connection_state="revoked", discovery_state="not_requested", status="success")
        return
    result["_runtime_applying"] = True
    service.runtime.apply_external_configuration(service.configs.load_manifest(target), cancel=cancel, deadline=deadline, before_apply=current)
    result["_runtime_loaded"], result["_runtime_applying"] = True, False
    if plan["connect"]:
        result["connection_state"] = "connecting"
        service._progress(operation_id, {key: value for key, value in result.items() if not key.startswith("_")})
        reconciliation: dict[str, Any] = {}
        discovery: dict[str, Any] = {}

        def reconcile(definitions: list[Any]) -> None:
            current()
            reconciliation.update(service.access.reconcile_server_tools(target, definitions, context.actor_id))

        server = service.runtime.connect_external_if_manifest_digest(target, plan["manifest_digest"], cancel=cancel, deadline=deadline,
            operation_id=operation_id, before_connect=current, before_replace=reconcile, discovery=discovery,
            credential_revisions=plan["credential_revisions"])
        if server.status != "running":
            current()
            raise _error("external_config_connect_failed", "Configuration saved; the external connection did not become ready.")
        result.update(connection_state="connected", discovery_state="succeeded", **discovery, counts=reconciliation["counts"],
                      classification_state="needs_review" if reconciliation["counts"]["needs_review"] else "ready")
    current()
    result["status"] = "success"
